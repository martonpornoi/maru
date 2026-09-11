"""Current combined person conflicts, including undisclosed cross-edition work/rest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.identity.queries import (
    MAX_PERSON_REFERENCE_BATCH,
    edition_person_conflict_key,
    resolve_active_verified_person_references,
)
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.inputs import canonical_digest, require_uuid
from maru.programme.release_queries import collect_programme_release_person_references
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)
from maru.scheduling.catalogs import MAX_CONFLICTS
from maru.scheduling.person_obligation_references import (
    resolve_published_person_conflict,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_candidate_queries import load_release_candidate_source

from .models import ShiftCommitment
from .programme_person_conflicts import (
    ProgrammePersonConsequence,
    ProgrammePersonObligation,
    evaluate_programme_person_conflicts,
)
from .programme_references import lock_programme_staffing_scope
from .programme_release_queries import _authorize, load_programme_retained_work_source
from .programme_staffing_queries import ProgrammeStaffingUnavailableError
from .shift_queries import MAX_SHIFT_COMMITMENTS, MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.placement_queries import ProgrammePlacementReadRequest
    from maru.programme.release_queries import ProgrammeReleasePeople
    from maru.scheduling.release_candidate_queries import (
        SchedulingReleaseCandidateSource,
    )


@dataclass(frozen=True, slots=True)
class _Commitment:
    id: UUID
    demand_id: UUID
    account_id: UUID
    starts_at: datetime
    ends_at: datetime
    rest_ends_at: datetime
    command_version: int
    status: str


@dataclass(frozen=True, slots=True)
class ProgrammeCombinedPersonSource:
    """Complete minimized current person and rest consequences, never calendars.

    Attributes
    ----------
    candidate_revision_id
        Exact selected immutable candidate whose obligations were evaluated.
    person_state
        Satisfied, blocked, unavailable or owner-proven not_applicable.
    rest_state
        Current retained-rest consequence with the same complete-source distinction.
    consequences
        Only affected selected occurrences and edition-bounded conflict keys.
    evidence_digest
        Fingerprint of complete current sources, not a portable approval token.
    """

    candidate_revision_id: UUID
    person_state: str
    rest_state: str
    consequences: tuple[ProgrammePersonConsequence, ...]
    evidence_digest: str


_COMMITMENT_FIELDS = tuple(_Commitment.__dataclass_fields__)


def _selected_work(
    request: ProgrammePlacementReadRequest, demand_ids: tuple[UUID, ...]
) -> tuple[_Commitment, ...]:
    rows = tuple(
        ShiftCommitment.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            demand_id__in=demand_ids,
            status__in=("claimed", "confirmed"),
        )
        .order_by("id")
        .values(*_COMMITMENT_FIELDS)[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(rows) > MAX_SHIFT_COMMITMENTS:
        raise ProgrammeStaffingUnavailableError
    return tuple(_Commitment(**row) for row in rows)


def _bound_work(
    request: ProgrammePlacementReadRequest,
    candidate: SchedulingReleaseCandidateSource,
    programme_authorizer: ProgrammeAuthorizer,
) -> tuple[dict[UUID, set[UUID]], tuple[str, ...]]:
    occurrences: dict[UUID, set[UUID]] = {}
    digests = []
    for placement in candidate.placements:
        source = load_programme_retained_work_source(
            ProgrammeStaffingReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                placement.occurrence.item_id,
                request.correlation_id,
                request.source_channel,
            ),
            occurrence_id=placement.occurrence.id,
            authorizer=programme_authorizer,
        )
        digests.append(source.evidence_digest)
        for identifier in source.demand_ids:
            occurrences.setdefault(identifier, set()).add(placement.occurrence.id)
        if len(occurrences) > MAX_SHIFT_DEMANDS:
            raise ProgrammeStaffingUnavailableError
    return occurrences, tuple(digests)


def _host_obligations(
    request: ProgrammePlacementReadRequest,
    candidate: SchedulingReleaseCandidateSource,
    people: ProgrammeReleasePeople,
) -> tuple[ProgrammePersonObligation, ...]:
    by_host = {row.host_id: row for row in people.selected_hosts}
    obligations = []
    for placement in candidate.placements:
        for presence in placement.hosts:
            host = by_host.get(presence.host_id)
            if host is None or host.item_id != placement.occurrence.item_id:
                raise ProgrammeStaffingUnavailableError
            obligations.append(
                ProgrammePersonObligation(
                    edition_person_conflict_key(
                        edition_id=request.edition_id, account_id=host.account_id
                    ),
                    placement.occurrence.id,
                    host.host_id,
                    "host",
                    presence.starts_at,
                    presence.ends_at,
                    presence.ends_at,
                )
            )
    return tuple(obligations)


def _global_work(
    account_ids: set[UUID],
    obligations: tuple[ProgrammePersonObligation, ...],
) -> tuple[_Commitment, ...]:
    if not obligations:
        return ()
    # This narrowly authorized global-by-account query preserves the existing
    # Workforce claim/rest contract. No foreign tenant labels, scope IDs or reasons
    # are selected or disclosed. No foreign edition/aggregate locks are acquired.
    rows = tuple(
        ShiftCommitment.objects.filter(
            account_id__in=account_ids,
            status__in=("claimed", "confirmed"),
            starts_at__lt=max(row.rest_ends_at for row in obligations),
            rest_ends_at__gt=min(row.starts_at for row in obligations),
        )
        .order_by("id")
        .values(*_COMMITMENT_FIELDS)[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(rows) > MAX_SHIFT_COMMITMENTS:
        raise ProgrammeStaffingUnavailableError
    return tuple(_Commitment(**row) for row in rows)


def _work_obligation(
    request: ProgrammePlacementReadRequest,
    row: _Commitment,
    occurrence_id: UUID | None,
) -> ProgrammePersonObligation:
    return ProgrammePersonObligation(
        edition_person_conflict_key(
            edition_id=request.edition_id, account_id=row.account_id
        ),
        occurrence_id,
        row.id,
        "work",
        row.starts_at,
        row.ends_at,
        row.rest_ends_at,
    )


def _audit(request: ProgrammePlacementReadRequest, candidate_id: UUID) -> None:
    decision = _authorize(request)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.programme_release.person_conflicts",
            target_type="scheduling.candidate",
            target_id=candidate_id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="service",
            obligations=tuple(
                sorted(set(decision.obligations) | {"audit_sensitive_read"})
            ),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=timezone.now(),
    )


def _recheck_sources(
    request: ProgrammePlacementReadRequest,
    candidate: SchedulingReleaseCandidateSource,
    people: ProgrammeReleasePeople,
    item_ids: tuple[UUID, ...],
    host_ids: tuple[UUID, ...],
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> None:
    # Recheck independently owned, potentially time-expiring authority before
    # releasing consequences. Never acquire a newly discovered narrower person lock.
    current_people = collect_programme_release_person_references(
        request, item_ids=item_ids, host_ids=host_ids, authorizer=programme_authorizer
    )
    current_candidate = load_release_candidate_source(
        SchedulingReadRequest(
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        ),
        candidate_id=candidate.candidate_id,
        candidate_revision_id=candidate.revision_id,
        expected_candidate_version=candidate.candidate_version,
        authorizer=scheduling_authorizer,
    )
    authorize_programme_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_VIEW_STAFFING,
        requested_fields=frozenset({"staffing_requirements"}),
        authorizer=programme_authorizer,
    )
    if current_people != people or current_candidate != candidate:
        raise ProgrammeStaffingUnavailableError


def load_programme_combined_person_source(
    request: ProgrammePlacementReadRequest,
    *,
    candidate_id: UUID,
    candidate_revision_id: UUID,
    expected_candidate_version: int,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeCombinedPersonSource:
    """Resolve every selected host and retained bound worker, then check global rest.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted exact actor, tenant, edition and sensitive-read correlation.
    candidate_id : UUID
        Explicit candidate, independently authorized by Scheduling.
    candidate_revision_id : UUID
        Exact immutable complete selected manifest.
    expected_candidate_version : int
        Exact current candidate version, not inferred from recency.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current Programme source and complete staffing inventory policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent exact candidate policy, with existing isolated-test guard only.

    Returns
    -------
    ProgrammeCombinedPersonSource
        Minimized selected-occurrence conflicts and exact dependency fingerprint.

    Raises
    ------
    ProgrammeStaffingUnavailableError
        If complete current person membership or stable selected work is unavailable.

    Notes
    -----
    The query accepts no caller-supplied person IDs, demand selection, calendars
    or applicability flags. It discovers the complete current Programme and bound
    Workforce person union before taking globally sorted Identity locks. A composing
    release collector must call this before any narrower person-locking source.
    Shared parents and people remain locked until its surrounding transaction ends.
    Claimed and confirmed commitments in other editions remain protected, but their
    identity, times and private rationale never leave Workforce. Publication must
    repeat collection and supply the separate atomic invalidation closure.
    """
    for field in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, field), field=field)
    _authorize(request)
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _authorize(request)
        candidate = load_release_candidate_source(
            SchedulingReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.correlation_id,
            ),
            candidate_id=candidate_id,
            candidate_revision_id=candidate_revision_id,
            expected_candidate_version=expected_candidate_version,
            authorizer=scheduling_authorizer,
        )
        item_ids = tuple(
            sorted({row.occurrence.item_id for row in candidate.placements}, key=str)
        )
        host_ids = tuple(
            sorted(
                {
                    presence.host_id
                    for row in candidate.placements
                    for presence in row.hosts
                },
                key=str,
            )
        )
        people = collect_programme_release_person_references(
            request,
            item_ids=item_ids,
            host_ids=host_ids,
            authorizer=programme_authorizer,
        )
        demand_occurrences, work_digests = _bound_work(
            request, candidate, programme_authorizer
        )
        demand_ids = tuple(sorted(demand_occurrences, key=str))
        selected_work = _selected_work(request, demand_ids)
        account_ids = tuple(
            sorted(
                {*people.account_ids, *(row.account_id for row in selected_work)},
                key=str,
            )
        )
        if len(account_ids) > MAX_PERSON_REFERENCE_BATCH:
            raise ProgrammeStaffingUnavailableError
        current = resolve_active_verified_person_references(
            account_ids=account_ids, lock=True
        )
        if current is None or request.actor_id not in {
            row.account_id for row in current
        }:
            raise ProgrammeStaffingUnavailableError
        if _selected_work(request, demand_ids) != selected_work:
            raise ProgrammeStaffingUnavailableError
        hosts = _host_obligations(request, candidate, people)
        selected = (
            *hosts,
            *(
                _work_obligation(request, row, occurrence_id)
                for row in selected_work
                for occurrence_id in sorted(demand_occurrences[row.demand_id], key=str)
            ),
        )
        relevant_accounts = {
            *(row.account_id for row in people.selected_hosts),
            *(row.account_id for row in selected_work),
        }
        global_work = _global_work(relevant_accounts, selected)
        obligations = (
            *selected,
            *(_work_obligation(request, row, None) for row in global_work),
        )
        # Enforce complete source/comparison bounds before any published-source
        # loop. A malformed/oversized candidate must not trigger unbounded reads.
        local_consequences = evaluate_programme_person_conflicts(obligations)
        published_consequences = set()
        published_digests = []
        by_key = {
            edition_person_conflict_key(
                edition_id=request.edition_id, account_id=identifier
            ): identifier
            for identifier in relevant_accounts
        }
        for obligation in selected:
            published = resolve_published_person_conflict(
                account_id=by_key[obligation.person_key],
                starts_at=obligation.starts_at,
                ends_at=obligation.ends_at,
                rest_ends_at=obligation.rest_ends_at,
                replaced_edition_id=request.edition_id,
            )
            published_digests.append(published.evidence_digest)
            for blocked, code in (
                (published.overlap, "overlap"),
                (published.rest, "rest"),
            ):
                if blocked and obligation.occurrence_id is not None:
                    published_consequences.add(
                        ProgrammePersonConsequence(
                            obligation.occurrence_id, obligation.person_key, code
                        )
                    )
        consequences = tuple(
            sorted(
                {
                    *local_consequences,
                    *published_consequences,
                },
                key=lambda row: (str(row.occurrence_id), str(row.person_key), row.code),
            )
        )
        if len(consequences) > MAX_CONFLICTS:
            raise ProgrammeStaffingUnavailableError
        unavailable = not relevant_accounts <= {row.account_id for row in current}
        baseline = (
            "unavailable"
            if unavailable
            else "satisfied"
            if selected
            else "not_applicable"
        )
        result = ProgrammeCombinedPersonSource(
            candidate.revision_id,
            "blocked"
            if any(row.code == "overlap" for row in consequences)
            else baseline,
            "blocked" if any(row.code == "rest" for row in consequences) else baseline,
            consequences,
            canonical_digest(
                {
                    "schema": "programme-combined-person-source@1",
                    "organization_id": request.organization_id,
                    "edition_id": request.edition_id,
                    "candidate_revision_id": candidate.revision_id,
                    "candidate_manifest": candidate.manifest_digest,
                    "work_sources": work_digests,
                    # Caller-only locks are authorization mechanics, not release
                    # dependencies. Planner, approver and publisher must observe
                    # the same fingerprint for the same authorized owner facts.
                    "selected_hosts": tuple(
                        asdict(row) for row in people.selected_hosts
                    ),
                    "verified_selected_people": tuple(
                        sorted(
                            relevant_accounts & {row.account_id for row in current},
                            key=str,
                        )
                    ),
                    "selected_work": tuple(asdict(row) for row in selected_work),
                    "global_work": tuple(asdict(row) for row in global_work),
                    "published_person_sources": tuple(published_digests),
                    "consequences": tuple(asdict(row) for row in consequences),
                }
            ),
        )
        _recheck_sources(
            request,
            candidate,
            people,
            item_ids,
            host_ids,
            programme_authorizer,
            scheduling_authorizer,
        )
        _audit(request, candidate_id)
        return result
