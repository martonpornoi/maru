"""Explicit immutable placement edits using independent Programme and Venue proof."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from maru.programme.scheduling_queries import load_programme_scheduling_dependencies
from maru.venues.scheduling_queries import load_venue_scheduling_dependencies

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, MANAGE_CANDIDATES
from .candidate_commands import (
    _advance,
    _append_revision,
    _current_revision,
    _load_manifest,
    _locked_candidate,
)
from .catalogs import MAX_OCCURRENCES, SchedulingOperation
from .command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
    _CommandTransaction,
    _execute,
)
from .inputs import (
    SchedulingCommandRequest,
    SchedulingPlacementInput,
    require_identifier,
    require_version,
)
from .models import (
    SchedulingCandidateRevision,
    SchedulingOccurrenceRevision,
    SchedulingPlacementHostPresence,
    SchedulingPlacementRevision,
    SchedulingServiceDayRevision,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult


@dataclass(frozen=True, slots=True)
class _PlacementSources:
    occurrence: SchedulingOccurrenceRevision
    day: SchedulingServiceDayRevision


def _payload(
    intent: SchedulingPlacementInput, candidate_id: UUID, expected_version: int
) -> dict[str, object]:
    return {
        "candidate_id": str(candidate_id),
        "expected_version": expected_version,
        "occurrence_id": str(intent.occurrence_id),
        "occurrence_version": intent.occurrence_version,
        "day_id": str(intent.day_id),
        "day_version": intent.day_version,
        "space_selection_id": str(intent.space_selection_id),
        "capacity_mode": intent.capacity_mode,
        "expected_attendance": intent.expected_attendance,
        "setup_starts_at": intent.envelope.setup_starts_at.isoformat(),
        "effective_starts_at": intent.envelope.effective_starts_at.isoformat(),
        "effective_ends_at": intent.envelope.effective_ends_at.isoformat(),
        "teardown_ends_at": intent.envelope.teardown_ends_at.isoformat(),
        "host_presences": [
            {
                "host_id": str(host.host_id),
                "starts_at": host.starts_at.isoformat(),
                "ends_at": host.ends_at.isoformat(),
            }
            for host in intent.host_presences
        ],
    }


def _prepare(
    request: SchedulingCommandRequest, intent: SchedulingPlacementInput
) -> _PlacementSources:
    # The caller already holds Events' edition mutex. Resolve owned immutable
    # identifiers before Programme locks the complete canonical person set.
    scope = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    occurrence = (
        SchedulingOccurrenceRevision.objects.filter(
            **scope,
            occurrence_id=intent.occurrence_id,
            sequence=intent.occurrence_version,
            occurrence__aggregate_version=intent.occurrence_version,
            occurrence__lifecycle="active",
        )
        .select_related("occurrence")
        .first()
    )
    day = SchedulingServiceDayRevision.objects.filter(
        **scope,
        day_id=intent.day_id,
        sequence=intent.day_version,
        day__aggregate_version=intent.day_version,
        day__lifecycle="active",
    ).first()
    if occurrence is None or day is None:
        raise SchedulingUnavailableError
    load_programme_scheduling_dependencies(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        item_ids=(occurrence.occurrence.programme_item_id,),
        host_ids=tuple(host.host_id for host in intent.host_presences),
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
    )
    load_venue_scheduling_dependencies(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        selection_ids=(intent.space_selection_id,),
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
    )
    return _PlacementSources(occurrence, day)


def set_scheduling_placement(
    request: SchedulingCommandRequest,
    *,
    candidate_id: UUID,
    placement: SchedulingPlacementInput,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Place, move or resize one occurrence in only the selected candidate.

    Structural scope, versions and explicit host ownership must be proven.
    Draft dependency conflicts remain permitted and require current evaluation;
    this command creates no consent, booking, approval or published output.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution, inspectable action reason and exact retry key.
    candidate_id : UUID
        Exact draft whose new manifest will carry the placement.
    placement : SchedulingPlacementInput
        Complete explicit room, timing, capacity and required host-presence intent.
    expected_version : int
        Exact current candidate version, independent of other candidates.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal Scheduling policy; both source owners independently authorize reads.

    Returns
    -------
    SchedulingCommandResult
        Same candidate identity with a new immutable manifest and placement revision.
    """

    def normalize() -> SchedulingPlacementInput:
        require_identifier(candidate_id)
        require_version(expected_version)
        return placement.normalized()

    def write(
        context: _CommandTransaction,
        intent: SchedulingPlacementInput,
        sources: _PlacementSources,
    ) -> tuple[UUID, int]:
        candidate = _locked_candidate(context, candidate_id, expected_version)
        previous = _current_revision(candidate)
        retained = tuple(
            pair for pair in _load_manifest(previous) if pair[0] != intent.occurrence_id
        )
        if len(retained) >= MAX_OCCURRENCES:
            raise SchedulingLimitError
        placement_id = uuid4()

        def introduce(revision: SchedulingCandidateRevision) -> None:
            row = SchedulingPlacementRevision.objects.create(
                **context.ownership(),
                id=placement_id,
                introduced_in=revision,
                occurrence_revision=sources.occurrence,
                day_revision=sources.day,
                space_selection_id=intent.space_selection_id,
                capacity_mode=intent.capacity_mode,
                expected_attendance=intent.expected_attendance,
                setup_starts_at=intent.envelope.setup_starts_at,
                effective_starts_at=intent.envelope.effective_starts_at,
                effective_ends_at=intent.envelope.effective_ends_at,
                teardown_ends_at=intent.envelope.teardown_ends_at,
                host_presence_count=len(intent.host_presences),
            )
            SchedulingPlacementHostPresence.objects.bulk_create(
                [
                    SchedulingPlacementHostPresence(
                        **context.ownership(),
                        placement=row,
                        host_relationship_id=host.host_id,
                        starts_at=host.starts_at,
                        ends_at=host.ends_at,
                    )
                    for host in intent.host_presences
                ]
            )

        _advance(candidate)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.PLACEMENT_SET,
            label=previous.label,
            members=(*retained, (intent.occurrence_id, placement_id)),
            introduce=introduce,
        )
        return candidate.id, candidate.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.PLACEMENT_SET,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda intent: _payload(intent, candidate_id, expected_version),
        prepare=lambda intent: _prepare(request, intent),
        write=write,
        authorizer=authorizer,
    )
