"""Trusted complete release preflight; no retained approval or publication writes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction

from maru.authorization.catalog import POLICY_VERSION
from maru.events.adoption import profile_allows_adapter, profile_allows_conflict_source
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_edition_time_envelope_reference,
)
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.commands import ProgrammeUnavailableError
from maru.programme.placement_queries import (
    ProgrammePlacementReadRequest,
    preview_programme_placement_decision,
)
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.programme.release_inputs import (
    ProgrammePlacementDecisionKind,
    ProgrammePlacementSelection,
)
from maru.programme.release_queries import load_programme_release_item_sources
from maru.programme.scheduling_queries import (
    SCHEDULING_DEPENDENCY_FIELDS,
    load_programme_scheduling_dependencies,
)
from maru.venues.accessibility_queries import load_venue_accessibility_sources
from maru.venues.scheduling_queries import (
    VenueSchedulingSourceUnavailableError,
    load_venue_scheduling_dependencies,
)
from maru.workforce.programme_person_queries import (
    load_programme_combined_person_source,
)
from maru.workforce.programme_queries import authorize_programme_coverage
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_release_queries import authorize_programme_release_source
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
)

from .adoption import (
    SCHEDULING_RELEASE_PREFLIGHT_ADAPTER,
    SCHEDULING_TIME_CONFLICT_SOURCE,
)
from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CONFLICTS,
    SchedulingAuthorizationDeniedError,
    SchedulingAuthorizer,
)
from .catalogs import MAX_CONFLICTS, SchedulingConflictSeverity
from .command_support import SchedulingUnavailableError
from .conflicts import evaluate_scheduling_facts
from .evaluation_sources import (
    _programme_evidence,
    _venue_evidence,
)
from .inputs import require_identifier, require_version, scheduling_digest
from .planning_queries import SchedulingReadRequest, _audit, _authorize
from .release_candidate_queries import load_release_candidate_source
from .release_eligibility import (
    RELEASE_ELIGIBILITY_POLICY,
    ReleaseCheck,
    ReleaseCheckEvidence,
    ReleaseCheckState,
    ReleaseEligibility,
    ReleaseFinding,
    evaluate_release_eligibility,
)
from .release_source_rules import (
    combine_release_source_states,
    release_category_for_planning_finding,
    release_state_from_readiness,
)
from .release_staffing_sources import load_release_staffing_sources
from .time_rules import SchedulingWindow

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from .authorization import AuthorizedSchedulingScope
    from .conflicts import SchedulingPlacementFacts

_FIELDS = frozenset({"release_preflight"})
_ABSENT_SOURCES = (
    ProgrammeQueryUnavailableError,
    ProgrammeUnavailableError,
    VenueSchedulingSourceUnavailableError,
    ProgrammeStaffingUnavailableError,
)


@dataclass(frozen=True, slots=True)
class ReleasePreflightFinding:
    """One explainable selected-occurrence consequence without private source data.

    Attributes
    ----------
    check
        Closed release category.
    code
        Owner-derived closed consequence, never source text or human rationale.
    severity
        Blocker, warning or unavailable; no caller may waive a hard finding.
    occurrence_id
        Affected occurrence inside the exact selected manifest, if applicable.
    other_occurrence_id
        Another selected occurrence, never a foreign duty identity.
    fingerprint
        Exact complete-snapshot finding digest for a future retained review workflow.
    """

    check: ReleaseCheck
    code: str
    severity: SchedulingConflictSeverity
    occurrence_id: UUID | None
    other_occurrence_id: UUID | None
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class SchedulingReleasePreflight:
    """Complete minimized current sources, not an approval or activation permit.

    Attributes
    ----------
    candidate_revision_id
        Exact selected immutable candidate.
    snapshot_digest
        Actor-independent scope, profile, policy and complete dependency fingerprint.
    checks
        Exactly all ten mandatory release categories.
    findings
        Complete bounded minimized owner consequences.
    eligibility
        Pure fail-closed interpretation; warnings remain unacknowledged here.
    """

    candidate_revision_id: UUID
    snapshot_digest: str
    checks: tuple[ReleaseCheckEvidence, ...]
    findings: tuple[ReleasePreflightFinding, ...]
    eligibility: ReleaseEligibility


def _admit(
    request: SchedulingReadRequest, authorizer: SchedulingAuthorizer
) -> AuthorizedSchedulingScope:
    scope = _authorize(request, VIEW_CONFLICTS, _FIELDS, authorizer)
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_RELEASE_PREFLIGHT_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError
    if not scope.accepts_writes:
        raise SchedulingUnavailableError
    return scope


def _optional[T](loader: Callable[[], T]) -> T | None:
    # Only documented source absence becomes unavailable. Independent field denial,
    # required audit failure and database errors abort the complete disclosure.
    try:
        with transaction.atomic():
            return loader()
    except _ABSENT_SOURCES:
        return None


def _assessment(
    request: ProgrammePlacementReadRequest,
    selection: ProgrammePlacementSelection,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> tuple[ReleaseCheckState, dict[str, object]]:
    preview = _optional(
        lambda: preview_programme_placement_decision(
            request,
            selection=selection,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
    )
    return (
        release_state_from_readiness(preview.decision_state)
        if preview
        else ReleaseCheckState.UNAVAILABLE,
        {
            "placement_id": str(selection.placement_id),
            "kind": selection.kind.value,
            "digest": preview.source_digest if preview else None,
            "sequence": preview.decision_sequence if preview else None,
            "state": preview.decision_state if preview else "unavailable",
            "physical_selection_id": str(preview.physical_source.selection_id)
            if preview and preview.physical_source
            else None,
            "physical_digest": preview.physical_source.evidence_digest
            if preview and preview.physical_source
            else None,
        },
    )


def _final_owner_authority(
    request: ProgrammePlacementReadRequest,
    authorizer: ProgrammeAuthorizer,
) -> None:
    scope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    for capability, fields in (
        ("programme.view_readiness", frozenset({"readiness_summary"})),
        ("programme.view_public_copy", frozenset({"release_copy_consequences"})),
        (
            "programme.view_scheduling_dependencies",
            SCHEDULING_DEPENDENCY_FIELDS | {"release_person_references"},
        ),
        (
            "programme.view_delivery",
            frozenset({"delivery_information", "placement_decisions"}),
        ),
        (
            "programme.view_staffing",
            frozenset({"staffing_requirements", "placement_decisions"}),
        ),
    ):
        authorize_programme_scope(
            **scope,
            capability_code=capability,
            requested_fields=fields,
            authorizer=authorizer,
            lock=False,
        )
    authorize_programme_release_source(request)
    authorize_programme_coverage(**scope)
    authorize_programme_staffing_adapter(**scope, purpose="read")


def _finding_payload(row: ReleasePreflightFinding) -> dict[str, object]:
    return {
        "check": row.check.value,
        "code": row.code,
        "severity": row.severity.value,
        "occurrence_id": str(row.occurrence_id) if row.occurrence_id else None,
        "other_occurrence_id": str(row.other_occurrence_id)
        if row.other_occurrence_id
        else None,
    }


def _finish(
    revision_id: UUID,
    sources: dict[str, object],
    states: dict[ReleaseCheck, list[ReleaseCheckState]],
    findings: list[ReleasePreflightFinding],
) -> SchedulingReleasePreflight:
    if len(findings) > MAX_CONFLICTS:
        raise SchedulingUnavailableError
    for row in findings:
        if row.severity is SchedulingConflictSeverity.BLOCKER:
            states[row.check].append(ReleaseCheckState.BLOCKED)
        elif row.severity is SchedulingConflictSeverity.UNAVAILABLE:
            states[row.check].append(ReleaseCheckState.UNAVAILABLE)
        else:
            states[row.check].append(ReleaseCheckState.SATISFIED)
    reduced = {
        check: combine_release_source_states(tuple(states[check]))
        for check in ReleaseCheck
    }
    # Multiple underlying person conflicts can have the same safe projection.
    # Their complete private dependency set is still bound by the owner digest.
    unique = {scheduling_digest(_finding_payload(row)): row for row in findings}
    ordered = tuple(unique[key] for key in sorted(unique))
    digest = scheduling_digest(
        sources
        | {
            "checks": {check.value: state.value for check, state in reduced.items()},
            "findings": [_finding_payload(row) for row in ordered],
        }
    )
    exact = tuple(
        replace(
            row,
            fingerprint=scheduling_digest(
                {"snapshot": digest, "finding": _finding_payload(row)}
            ),
        )
        for row in ordered
    )
    checks = tuple(
        ReleaseCheckEvidence(digest, check, reduced[check]) for check in ReleaseCheck
    )
    return SchedulingReleasePreflight(
        revision_id,
        digest,
        checks,
        exact,
        evaluate_release_eligibility(
            snapshot_digest=digest,
            checks=checks,
            findings=tuple(
                ReleaseFinding(digest, row.check, row.fingerprint, row.severity)
                for row in exact
            ),
        ),
    )


def load_release_preflight(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    candidate_revision_id: UUID,
    expected_candidate_version: int,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingReleasePreflight:
    """Collect all ten owner checks for an exact candidate without publishing it.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, tenant, edition and mandatory sensitive-read attribution.
    candidate_id : UUID
        Explicit private alternative; never chosen by latest modification.
    candidate_revision_id : UUID
        Exact immutable selected manifest.
    expected_candidate_version : int
        Exact current optimistic version, independently checked before disclosure.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme owner authority; existing guarded test seam only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent candidate and separately ceilinged preflight authority.

    Returns
    -------
    SchedulingReleasePreflight
        All ten categories and minimized consequences; no private calendars, copy,
        people, approval actors, work titles or human assessment rationale.

    Notes
    -----
    Current profiles omit this adapter. No caller-supplied success, applicability,
    dependency list or warning acknowledgement is accepted. Shared parent locks and
    the complete canonical person closure precede all narrower owner reads. Missing
    person closure aborts, while later documented absence remains unavailable.
    Ordinary planning acknowledgements are not release acknowledgements. This read
    creates only sensitive-read audits, never retained approval or publication.
    Publication must repeat source collection and supply same-transaction owner
    invalidation and independent approval; this snapshot is not a reusable permit.
    """
    for value in (
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    ):
        require_identifier(value)
    _admit(request, scheduling_authorizer)
    require_identifier(candidate_id)
    require_identifier(candidate_revision_id)
    require_version(expected_candidate_version)
    owner_request = ProgrammePlacementReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    )
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, scheduling_authorizer)
        people = load_programme_combined_person_source(
            owner_request,
            candidate_id=candidate_id,
            candidate_revision_id=candidate_revision_id,
            expected_candidate_version=expected_candidate_version,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
        candidate = load_release_candidate_source(
            request,
            candidate_id=candidate_id,
            candidate_revision_id=candidate_revision_id,
            expected_candidate_version=expected_candidate_version,
            authorizer=scheduling_authorizer,
        )
        result = _collect(
            request,
            owner_request,
            candidate.placements,
            candidate_id=candidate_id,
            revision_id=candidate_revision_id,
            version=expected_candidate_version,
            manifest_digest=candidate.manifest_digest,
            person_states=(people.person_state, people.rest_state),
            person_digest=people.evidence_digest,
            person_findings=tuple(
                (row.occurrence_id, row.code) for row in people.consequences
            ),
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
        _final_owner_authority(owner_request, programme_authorizer)
        scope = _admit(request, scheduling_authorizer)
        _audit(request, VIEW_CONFLICTS, "release_preflight", scope=scope)
        return result


def _collect(
    request: SchedulingReadRequest,
    owner_request: ProgrammePlacementReadRequest,
    facts: tuple[SchedulingPlacementFacts, ...],
    *,
    candidate_id: UUID,
    revision_id: UUID,
    version: int,
    manifest_digest: str,
    person_states: tuple[str, str],
    person_digest: str,
    person_findings: tuple[tuple[UUID, str], ...],
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> SchedulingReleasePreflight:
    item_ids = tuple(sorted({row.occurrence.item_id for row in facts}, key=str))
    scope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "correlation_id": request.correlation_id,
    }
    programme = load_programme_scheduling_dependencies(
        **scope,
        source_channel="scheduling",
        item_ids=item_ids,
        host_ids=tuple(
            sorted({host.host_id for row in facts for host in row.hosts}, key=str)
        ),
        authorizer=programme_authorizer,
    )
    venues = _optional(
        lambda: load_venue_scheduling_dependencies(
            **scope,
            source_channel="scheduling",
            selection_ids=tuple(sorted({row.space_id for row in facts}, key=str)),
            placement_ids=tuple(sorted((row.id for row in facts), key=str)),
        )
    )
    bindings = {row.placement_id: row for row in venues.reservations} if venues else {}
    facts = tuple(
        replace(
            row,
            own_booking_id=bindings[row.id].booking_id
            if row.id in bindings
            and bindings[row.id].occurrence_id == row.occurrence.id
            else None,
        )
        for row in facts
    )
    edition = resolve_edition_time_envelope_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None:
        raise SchedulingUnavailableError
    # The time source uses the same exact pinned policy as planning evaluation.
    if not profile_allows_conflict_source(
        profile.code, profile.version, SCHEDULING_TIME_CONFLICT_SOURCE
    ):
        raise SchedulingUnavailableError
    planning = evaluate_scheduling_facts(
        facts,
        edition=SchedulingWindow(edition.starts_at, edition.ends_at)
        if edition
        else None,
        programme=programme,
        venues=venues,
    )
    states: dict[ReleaseCheck, list[ReleaseCheckState]] = {
        check: [] for check in ReleaseCheck
    }
    states[ReleaseCheck.CANDIDATE].append(ReleaseCheckState.SATISFIED)
    states[ReleaseCheck.PHYSICAL_CONSTRAINTS].append(
        ReleaseCheckState.SATISFIED if venues else ReleaseCheckState.UNAVAILABLE
    )
    states[ReleaseCheck.HOSTS].append(
        ReleaseCheckState.NOT_APPLICABLE
        if all(not row.hosting_required for row in programme.items)
        and not any(row.hosts for row in facts)
        else ReleaseCheckState.SATISFIED
    )
    for check, state in zip(
        (ReleaseCheck.PERSON_CONFLICTS, ReleaseCheck.REST), person_states, strict=True
    ):
        states[check].append(release_state_from_readiness(state))
    findings = [
        ReleasePreflightFinding(
            release_category_for_planning_finding(row),
            row.code.value,
            row.severity,
            row.occurrence_id,
            row.other_occurrence_id,
        )
        for row in planning
    ]
    findings.extend(
        ReleasePreflightFinding(
            ReleaseCheck.REST if code == "rest" else ReleaseCheck.PERSON_CONFLICTS,
            "combined_person_rest" if code == "rest" else "combined_person_overlap",
            SchedulingConflictSeverity.BLOCKER,
            occurrence_id,
            None,
        )
        for occurrence_id, code in person_findings
    )
    evidence: list[dict[str, object]] = []
    for item in programme.items:
        current = _optional(
            partial(
                load_programme_release_item_sources,
                owner_request,
                item_ids=(item.item_id,),
                authorizer=programme_authorizer,
            )
        )
        readiness = (
            combine_release_source_states(
                tuple(
                    release_state_from_readiness(row.state)
                    for row in current[0].readiness
                )
            )
            if current
            else ReleaseCheckState.UNAVAILABLE
        )
        if readiness is ReleaseCheckState.NOT_APPLICABLE:
            readiness = ReleaseCheckState.SATISFIED
        states[ReleaseCheck.PROGRAMME_READINESS].append(
            readiness if item.lifecycle == "active" else ReleaseCheckState.BLOCKED
        )
        states[ReleaseCheck.PUBLIC_COPY].append(
            release_state_from_readiness(current[0].public_copy_state)
            if current
            else ReleaseCheckState.UNAVAILABLE
        )
        selected = tuple(row for row in facts if row.occurrence.item_id == item.item_id)
        staffing = _optional(
            partial(
                load_release_staffing_sources,
                request,
                item_id=item.item_id,
                candidate_id=candidate_id,
                occurrence_ids=tuple(row.occurrence.id for row in selected),
                programme_authorizer=programme_authorizer,
                scheduling_authorizer=scheduling_authorizer,
            )
        )
        by_occurrence = {row.occurrence_id: row for row in staffing} if staffing else {}
        evidence.append(
            {
                "item_id": str(item.item_id),
                "current": current[0].evidence_digest if current else None,
            }
        )
        for placement in selected:
            states[ReleaseCheck.PHYSICAL_APPROVAL].append(
                ReleaseCheckState.UNAVAILABLE
                if venues is None
                else ReleaseCheckState.SATISFIED
                if placement.own_booking_id
                and bindings[placement.id].review_state == "approved"
                else ReleaseCheckState.BLOCKED
            )
            selection = ProgrammePlacementSelection(
                item.item_id,
                placement.occurrence.id,
                candidate_id,
                revision_id,
                placement.id,
                item.item_version,
                version,
                ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT,
            )
            fit, assessment = _assessment(
                owner_request, selection, programme_authorizer, scheduling_authorizer
            )
            states[ReleaseCheck.ACCESSIBILITY_FIT].append(fit)
            evidence.append(assessment)
            work = by_occurrence.get(placement.occurrence.id)
            work_state = work.state if work else ReleaseCheckState.UNAVAILABLE
            if work and work.requires_absence_decision:
                absence, assessment = _assessment(
                    owner_request,
                    replace(
                        selection,
                        kind=ProgrammePlacementDecisionKind.STAFFING_NOT_REQUIRED,
                    ),
                    programme_authorizer,
                    scheduling_authorizer,
                )
                work_state = (
                    ReleaseCheckState.NOT_APPLICABLE
                    if absence is ReleaseCheckState.SATISFIED
                    else absence
                )
                evidence.append(assessment)
            states[ReleaseCheck.STAFFING].append(work_state)
            evidence.append(
                {
                    "occurrence_id": str(placement.occurrence.id),
                    "staffing": work.evidence_digest if work else None,
                }
            )
    # Venue catalog writes do not all share the edition mutex. Re-read their
    # public owner sources before disclosure, without adding an inverted physical
    # row lock. Publication still needs the separate atomic invalidation contract.
    current_venues = _optional(
        lambda: load_venue_scheduling_dependencies(
            **scope,
            source_channel="scheduling",
            selection_ids=tuple(sorted({row.space_id for row in facts}, key=str)),
            placement_ids=tuple(sorted((row.id for row in facts), key=str)),
        )
    )
    access = _optional(
        lambda: load_venue_accessibility_sources(
            **scope,
            source_channel="scheduling",
            selection_ids=tuple(sorted({row.space_id for row in facts}, key=str)),
        )
    )
    access_digests = (
        {str(row.selection_id): row.evidence_digest for row in access} if access else {}
    )
    if current_venues != venues or any(
        row.get("physical_digest") is not None
        and access_digests.get(str(row["physical_selection_id"]))
        != row["physical_digest"]
        for row in evidence
    ):
        raise SchedulingUnavailableError
    return _finish(
        revision_id,
        {
            "schema": SCHEDULING_RELEASE_PREFLIGHT_ADAPTER,
            "organization_id": str(request.organization_id),
            "edition_id": str(request.edition_id),
            "edition_version": edition.version if edition else None,
            "profile": {"code": profile.code, "version": profile.version},
            "policy": POLICY_VERSION,
            "release_policy": RELEASE_ELIGIBILITY_POLICY,
            "candidate_id": str(candidate_id),
            "revision_id": str(revision_id),
            "candidate_version": version,
            "manifest": manifest_digest,
            "programme": _programme_evidence(programme),
            "venues": _venue_evidence(venues, facts),
            "people": person_digest,
            "owners": evidence,
            "current_placements": [
                {
                    "id": str(row.id),
                    "occurrence_version": row.occurrence.current_version,
                    "occurrence_active": row.occurrence.active,
                    "day_version": row.day.current_version,
                    "day_active": row.day.active,
                }
                for row in facts
            ],
        },
        states,
        findings,
    )
