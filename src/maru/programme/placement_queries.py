"""Independent exact-source previews for accountable Programme owner decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_candidate_queries import load_release_candidate_source
from maru.venues.accessibility_queries import (
    VenueAccessibilitySource,
    load_venue_accessibility_sources,
)
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_release_queries import load_programme_retained_work_source

from .adoption import PROGRAMME_PLACEMENT_DECISION_ADAPTER
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_DELIVERY,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .commands import ProgrammeUnavailableError, _require_version
from .inputs import canonical_digest, require_uuid
from .models import ProgrammeDeliveryRevision, ProgrammeItem, ProgrammePlacementDecision
from .queries import _authorized_query
from .release_inputs import (
    MAX_PLACEMENT_DECISIONS,
    ProgrammePlacementDecisionKind,
    ProgrammePlacementSelection,
)
from .staffing_queries import ProgrammeStaffingReadRequest

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

PLACEMENT_HISTORY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class ProgrammePlacementReadRequest:
    """Trusted caller attribution, separate from untrusted placement selection.

    Attributes
    ----------
    actor_id
        Current authenticated organizer.
    organization_id
        Exact tenant expected to own the selected item.
    edition_id
        Exact edition whose sources must be independently authorized.
    correlation_id
        Trusted trace for mandatory sensitive-read evidence.
    source_channel
        Closed adapter provenance.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    source_channel: str = "programme-placement"


@dataclass(frozen=True, slots=True)
class ProgrammePlacementPreview:
    """Owner-recomputed evidence for a later explicit decision, never an approval.

    Attributes
    ----------
    selection
        Exact selected candidate and owner versions.
    source_digest
        Current complete placement and owner-source fingerprint.
    decision_sequence
        Current independent placement/purpose sequence, zero when absent.
    decision_state
        Current conclusion, stale if its sources moved, or absent.
    delivery_revision_id
        Exact declared Programme delivery source for accessibility only.
    accessibility_delivery
        Independently authorized private needs for a human fit assessment.
    physical_source
        Independently authorized selected configuration and complete access facts.
    staffing_absence_available
        True only for complete absence of active needs and operative bound work;
        this does not itself record the explicit no-staffing decision.
    """

    selection: ProgrammePlacementSelection
    source_digest: str
    decision_sequence: int
    decision_state: str
    delivery_revision_id: UUID | None
    accessibility_delivery: str | None
    physical_source: VenueAccessibilitySource | None
    staffing_absence_available: bool


@dataclass(frozen=True, slots=True)
class ProgrammePlacementHistoryEntry:
    """One exact retained owner decision; historical success is not current fitness.

    Attributes
    ----------
    decision_id
        Immutable Programme assessment identity.
    sequence
        Original independent placement/purpose sequence.
    state
        Original satisfied, blocked or withdrawn decision.
    candidate_revision_id
        Original Scheduling provenance; dereferencing it needs separate authority.
    item_version
        Programme owner version at the decision.
    source_digest
        Original source fingerprint, not portable authorization.
    actor_id
        Opaque retained decision-maker identity, not a directory label.
    reason
        Independently history-authorized private rationale.
    occurred_at
        Original server timestamp.
    """

    decision_id: UUID
    sequence: int
    state: str
    candidate_revision_id: UUID
    item_version: int
    source_digest: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammePlacementHistoryPage:
    """Stable bounded history that does not follow subsequent assessments.

    Attributes
    ----------
    through_sequence
        Fixed inclusive selected sequence ceiling.
    entries
        At most fifty consecutive retained owner decisions.
    next_after_sequence
        Exclusive continuation cursor, or None at the selected ceiling.
    """

    through_sequence: int
    entries: tuple[ProgrammePlacementHistoryEntry, ...]
    next_after_sequence: int | None


def _read_purpose(kind: ProgrammePlacementDecisionKind) -> tuple[str, frozenset[str]]:
    if type(kind) is not ProgrammePlacementDecisionKind:
        raise ProgrammeAuthorizationDeniedError
    return (
        (
            PROGRAMME_VIEW_DELIVERY,
            frozenset({"delivery_information", "placement_decisions"}),
        )
        if kind is ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT
        else (
            PROGRAMME_VIEW_STAFFING,
            frozenset({"staffing_requirements", "placement_decisions"}),
        )
    )


def _admit(
    request: ProgrammePlacementReadRequest,
    kind: ProgrammePlacementDecisionKind,
    authorizer: ProgrammeAuthorizer,
    *,
    history: bool = False,
) -> None:
    capability, fields = _read_purpose(kind)
    if history:
        fields = _history_fields(kind)
    authorize_programme_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=capability,
        requested_fields=fields,
        authorizer=authorizer,
    )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, PROGRAMME_PLACEMENT_DECISION_ADAPTER
    ):
        raise ProgrammeAuthorizationDeniedError


def _history_fields(kind: ProgrammePlacementDecisionKind) -> frozenset[str]:
    return frozenset(
        {
            "placement_decisions",
            "delivery_history"
            if kind is ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT
            else "staffing_history",
        }
    )


def _source(
    request: ProgrammePlacementReadRequest,
    selection: ProgrammePlacementSelection,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> ProgrammePlacementPreview:
    item = (
        ProgrammeItem.objects.filter(
            id=selection.item_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            lifecycle="active",
        )
        .only("id", "aggregate_version")
        .first()
    )
    if item is None:
        raise ProgrammeUnavailableError
    _require_version(
        actual=item.aggregate_version, expected=selection.expected_item_version
    )
    candidate = load_release_candidate_source(
        SchedulingReadRequest(
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        ),
        candidate_id=selection.candidate_id,
        candidate_revision_id=selection.candidate_revision_id,
        expected_candidate_version=selection.expected_candidate_version,
        authorizer=scheduling_authorizer,
    )
    placements = tuple(
        row for row in candidate.placements if row.id == selection.placement_id
    )
    if len(placements) != 1:
        raise ProgrammeUnavailableError
    placement = placements[0]
    if (
        placement.occurrence.id != selection.occurrence_id
        or placement.occurrence.item_id != item.id
    ):
        raise ProgrammeUnavailableError
    delivery_id = None
    delivery_text = None
    physical = None
    absence_available = False
    if selection.kind is ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT:
        delivery = (
            ProgrammeDeliveryRevision.objects.filter(
                item_id=item.id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
            .order_by("-sequence")
            .only("id", "sequence", "accessibility_delivery")
            .first()
        )
        if delivery is None:
            raise ProgrammeUnavailableError
        (physical,) = load_venue_accessibility_sources(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            correlation_id=request.correlation_id,
            selection_ids=(placement.space_id,),
        )
        delivery_id, delivery_text = delivery.id, delivery.accessibility_delivery
        owner_digest = canonical_digest(
            {
                "delivery_id": delivery.id,
                "delivery_sequence": delivery.sequence,
                "physical": physical.evidence_digest,
            }
        )
    else:
        work = load_programme_retained_work_source(
            ProgrammeStaffingReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                item.id,
                request.correlation_id,
                request.source_channel,
            ),
            occurrence_id=selection.occurrence_id,
            authorizer=programme_authorizer,
        )
        owner_digest = work.evidence_digest
        absence_available = (
            not work.active_requirement_ids and not work.operative_demand_ids
        )
    digest = canonical_digest(
        {
            "schema": "programme-placement-decision-source@1",
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
            "item_id": item.id,
            "kind": selection.kind,
            # Candidate identity is retained provenance. Exact immutable placement plus
            # every current owner dependency allows reuse in an identical copy.
            "placement": asdict(placement),
            "owner_digest": owner_digest,
        }
    )
    previous = (
        ProgrammePlacementDecision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=item.id,
            occurrence_id=selection.occurrence_id,
            placement_id=selection.placement_id,
            kind=selection.kind,
        )
        .order_by("-sequence")
        .only("sequence", "state", "source_digest")
        .first()
    )
    return ProgrammePlacementPreview(
        selection,
        digest,
        previous.sequence if previous else 0,
        (
            "withdrawn"
            if previous.state == "withdrawn"
            else previous.state
            if previous.source_digest == digest
            else "stale"
        )
        if previous
        else "absent",
        delivery_id,
        delivery_text,
        physical,
        absence_available,
    )


def preview_programme_placement_decision(
    request: ProgrammePlacementReadRequest,
    *,
    selection: ProgrammePlacementSelection,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammePlacementPreview:
    """Recompute an exact human-decision preview with independent source admission.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted caller scope and mandatory sensitive-read correlation.
    selection : ProgrammePlacementSelection
        Explicit placement and optimistic owner versions, parsed after admission.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real Programme field policy; existing guarded synthetic substitute only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent exact candidate policy with the same isolated-test restriction.

    Returns
    -------
    ProgrammePlacementPreview
        Complete private assessment inputs, never publication authority.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If the closed selection purpose or independent source authority is absent.

    Notes
    -----
    Missing declarations, stale candidate versions, source denial or required
    audit failure return no usable preview. Current profiles omit this adapter.
    The later command recomputes the source under its own transaction; this is
    neither a portable authorization credential nor an automated fit assessment.
    """
    for field in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, field), field=field)
    if type(selection) is not ProgrammePlacementSelection:
        raise ProgrammeAuthorizationDeniedError
    _admit(request, selection.kind, programme_authorizer)
    selection.validated()
    capability, fields = _read_purpose(selection.kind)

    def load() -> ProgrammePlacementPreview:
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, selection.kind, programme_authorizer)
        result = _source(
            request, selection, programme_authorizer, scheduling_authorizer
        )
        _admit(request, selection.kind, programme_authorizer)
        return result

    with transaction.atomic():
        return _authorized_query(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            requested_fields=fields,
            operation="programme.placement.preview",
            loader=load,
            target_type="programme.item",
            target_id=selection.item_id,
            target_count=lambda _: 1,
            reason="Exact Programme placement assessment",
            correlation_id=request.correlation_id,
            source_channel=request.source_channel,
            authorizer=programme_authorizer,
        )


def load_programme_placement_decision_history(
    request: ProgrammePlacementReadRequest,
    *,
    item_id: UUID,
    placement_id: UUID,
    kind: ProgrammePlacementDecisionKind,
    through_sequence: int,
    after_sequence: int = 0,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammePlacementHistoryPage:
    """Read exact immutable owner history under a separate private-rationale ceiling.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted actor, tenant, edition and mandatory audit correlation.
    item_id : UUID
        Exact Programme owner of the retained assessment.
    placement_id : UUID
        Exact immutable placement identity retained by Programme, not dereferenced.
    kind : ProgrammePlacementDecisionKind
        Closed accessibility-fit or no-staffing history purpose.
    through_sequence : int
        Fixed inclusive sequence selected from an authorized current preview.
    after_sequence : int, default=0
        Exclusive continuation cursor below the fixed ceiling.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current Programme history-field authority.

    Returns
    -------
    ProgrammePlacementHistoryPage
        Consecutive immutable decisions; no automatic source-freshness assertion.

    Raises
    ------
    ProgrammeUnavailableError
        If the fixed ceiling, cursor or complete retained history is unavailable.

    Notes
    -----
    Original candidate references are provenance only. Opening Scheduling history
    or withdrawing against it requires independent Scheduling authority. Foreign,
    absent, over-bound or incomplete owner history is unavailable, not an empty
    success. New decisions never expand a previously selected page ceiling.
    """
    for field in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, field), field=field)
    _admit(request, kind, authorizer, history=True)
    require_uuid(item_id, field="item_id")
    require_uuid(placement_id, field="placement_id")
    if (
        type(through_sequence) is not int
        or type(after_sequence) is not int
        or not 0 <= after_sequence < through_sequence <= MAX_PLACEMENT_DECISIONS + 1
    ):
        raise ProgrammeUnavailableError

    def load() -> ProgrammePlacementHistoryPage:
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, kind, authorizer, history=True)
        rows = ProgrammePlacementDecision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=item_id,
            placement_id=placement_id,
            kind=kind,
        )
        if not rows.filter(sequence=through_sequence).exists():
            raise ProgrammeUnavailableError
        selected = tuple(
            rows.filter(sequence__gt=after_sequence, sequence__lte=through_sequence)
            .order_by("sequence")
            .only(
                "id",
                "sequence",
                "state",
                "candidate_revision_id",
                "item_version",
                "source_digest",
                "actor_id",
                "reason",
                "occurred_at",
            )[:PLACEMENT_HISTORY_PAGE_SIZE]
        )
        expected = min(through_sequence - after_sequence, PLACEMENT_HISTORY_PAGE_SIZE)
        if tuple(row.sequence for row in selected) != tuple(
            range(after_sequence + 1, after_sequence + expected + 1)
        ):
            raise ProgrammeUnavailableError
        entries = tuple(
            ProgrammePlacementHistoryEntry(
                row.id,
                row.sequence,
                row.state,
                row.candidate_revision_id,
                row.item_version,
                row.source_digest,
                row.actor_id,
                row.reason,
                row.occurred_at,
            )
            for row in selected
        )
        _admit(request, kind, authorizer, history=True)
        return ProgrammePlacementHistoryPage(
            through_sequence,
            entries,
            entries[-1].sequence if entries[-1].sequence < through_sequence else None,
        )

    capability, _fields = _read_purpose(kind)
    return _authorized_query(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=capability,
        requested_fields=_history_fields(kind),
        operation="programme.placement.history",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda page: len(page.entries),
        reason="Programme placement decision history",
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        authorizer=authorizer,
    )
