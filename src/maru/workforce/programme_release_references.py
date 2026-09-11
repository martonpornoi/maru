"""Complete bounded native work references for governed release capture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.inputs import require_uuid
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_candidate_queries import load_release_candidate_source

from .models import ShiftCommitment
from .programme_person_queries import _bound_work
from .programme_references import lock_programme_staffing_scope
from .programme_release_queries import RELEASE_FIELDS, _authorize
from .programme_staffing_queries import ProgrammeStaffingUnavailableError
from .shift_queries import MAX_SHIFT_COMMITMENTS

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.placement_queries import ProgrammePlacementReadRequest

RELEASE_REFERENCE_FIELDS = RELEASE_FIELDS | {"release_dependency_references"}


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseWorkReference:
    """Selected active work's exact retained owner identities, never foreign work.

    Attributes
    ----------
    commitment_id
        Exact claimed or confirmed native commitment in this edition.
    demand_id
        Owning retained bound demand, including operative predecessors.
    account_id
        Ephemeral person reference needed for canonical lock closure.
    assignment_id
        Exact retained qualification relationship governing the commitment.
    availability_plan_id
        Exact deliberately shared native availability governing the commitment.
    ends_at
        Immutable half-open end of accepted work, not a requested backdated cutoff.
    version
        Current native commitment command version for complete-source comparison.
    status
        Current claimed or confirmed state; this is not a coverage decision.
    """

    commitment_id: UUID
    demand_id: UUID
    account_id: UUID
    assignment_id: UUID
    availability_plan_id: UUID
    ends_at: datetime
    version: int
    status: str


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseWorkReferences:
    """Complete native dependency closure for one exact candidate selection.

    Attributes
    ----------
    candidate_revision_id
        Independently authorized immutable Scheduling manifest.
    demand_occurrences
        Complete retained demand to selected-occurrence membership, including closed
        and predecessor demands; empty is a proven empty inventory, not user input.
    commitments
        Every claimed/confirmed commitment of those demands in this edition.
    """

    candidate_revision_id: UUID
    demand_occurrences: tuple[tuple[UUID, tuple[UUID, ...]], ...]
    commitments: tuple[ProgrammeReleaseWorkReference, ...]


def collect_programme_release_work_references(
    request: ProgrammePlacementReadRequest,
    *,
    candidate_id: UUID,
    candidate_revision_id: UUID,
    expected_candidate_version: int,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeReleaseWorkReferences:
    """Resolve complete retained work before the compositor locks its whole person set.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted exact actor, organization, edition and mandatory audit attribution.
    candidate_id : UUID
        Explicit Scheduling candidate; arbitrary demand/person identifiers are rejected.
    candidate_revision_id : UUID
        Exact immutable candidate revision, independently authorized by its owner.
    expected_candidate_version : int
        Exact optimistic candidate version, never inferred from recency.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme staffing inventory authority; guarded test seam only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent complete candidate admission; guarded test seam only.

    Returns
    -------
    ProgrammeReleaseWorkReferences
        Exact native local references without names, private work copy or foreign scope.

    Raises
    ------
    ProgrammeStaffingUnavailableError
        Without an enclosing transaction or complete bounded current native sources.

    Notes
    -----
    Requires the additional release_dependency_references field. Shared parents
    remain locked in the caller's transaction; this query deliberately acquires no
    person-only lock. Combine these references with Programme's complete person
    union before taking Identity locks, then recollect and compare both sets.
    Global work is represented by account-only generations in Scheduling, never by
    collecting foreign demand, assignment, availability or tenant identities here.
    These references create no key, release, accepted work or disclosure permission.
    """
    for field in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, field), field=field)
    _authorize(request, fields=RELEASE_REFERENCE_FIELDS)
    if not connection.in_atomic_block:
        raise ProgrammeStaffingUnavailableError
    read_request = SchedulingReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    )
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _authorize(request, fields=RELEASE_REFERENCE_FIELDS)
        candidate = load_release_candidate_source(
            read_request,
            candidate_id=candidate_id,
            candidate_revision_id=candidate_revision_id,
            expected_candidate_version=expected_candidate_version,
            authorizer=scheduling_authorizer,
        )
        demands, _digests = _bound_work(request, candidate, programme_authorizer)
        rows = tuple(
            ShiftCommitment.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                demand_id__in=demands,
                status__in=("claimed", "confirmed"),
                position_assignment__organization_id=request.organization_id,
                position_assignment__edition_id=request.edition_id,
                position_assignment__account_id=F("account_id"),
                position_assignment__position_id=F("demand__position_id"),
                availability_plan__organization_id=request.organization_id,
                availability_plan__edition_id=request.edition_id,
                availability_plan__account_id=F("account_id"),
            )
            .order_by("id")
            .values_list(
                "id",
                "demand_id",
                "account_id",
                "position_assignment_id",
                "availability_plan_id",
                "ends_at",
                "command_version",
                "status",
            )[: MAX_SHIFT_COMMITMENTS + 1]
        )
        # SQL ownership guards prevent mismatched native references. Compare the
        # entire scoped active set too, so malformed legacy evidence cannot be
        # silently removed by the joined ownership filters above.
        expected_ids = tuple(
            ShiftCommitment.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                demand_id__in=demands,
                status__in=("claimed", "confirmed"),
            )
            .order_by("id")
            .values_list("id", flat=True)[: MAX_SHIFT_COMMITMENTS + 1]
        )
        if (
            len(rows) > MAX_SHIFT_COMMITMENTS
            or tuple(row[0] for row in rows) != expected_ids
        ):
            raise ProgrammeStaffingUnavailableError
        result = ProgrammeReleaseWorkReferences(
            candidate.revision_id,
            tuple(
                (identifier, tuple(sorted(demands[identifier], key=str)))
                for identifier in sorted(demands, key=str)
            ),
            tuple(ProgrammeReleaseWorkReference(*row) for row in rows),
        )
        if (
            load_release_candidate_source(
                read_request,
                candidate_id=candidate_id,
                candidate_revision_id=candidate_revision_id,
                expected_candidate_version=expected_candidate_version,
                authorizer=scheduling_authorizer,
            )
            != candidate
        ):
            raise ProgrammeStaffingUnavailableError
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=PROGRAMME_VIEW_STAFFING,
            requested_fields=frozenset({"staffing_requirements"}),
            authorizer=programme_authorizer,
        )
        decision = _authorize(request, fields=RELEASE_REFERENCE_FIELDS)
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=request.actor_id,
                principal_context_id=None,
                organization_id=request.organization_id,
                event_edition_id=request.edition_id,
                capability_code="workforce.view_shifts",
                operation="workforce.programme_release.work_references",
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
        return result
