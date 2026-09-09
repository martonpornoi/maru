"""Current reciprocal physical hold proof, independent of the edited draft."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from maru.venues.scheduling_queries import (
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
    load_venue_scheduling_dependencies,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CONFLICTS,
    SchedulingAuthorizationDeniedError,
)
from .catalogs import SchedulingOperation
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .models import SchedulingOccurrence, SchedulingReservationIntent
from .planning_preview import PREVIEW_FIELDS
from .planning_queries import _ownership, _read
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import AuthorizedSchedulingScope, SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest


class PlanningReservationState(StrEnum):
    """Current physical consequence, never Programme approval or publication."""

    NOT_REQUESTED = "not_requested"
    NOT_ACTIVE = "not_active"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class PlanningActiveReservation:
    """Exact cancel/replacement proof for the currently active reciprocal hold.

    Attributes
    ----------
    candidate_id
        Source candidate, which may differ from the currently edited alternative.
    candidate_version
        Retained source version accepted by historical cancellation.
    placement_id
        Exact physically bound placement, not an inferred current draft placement.
    space_selection_id
        Independently authorized room; its label requires the separate owner read.
    envelope
        Immutable source geometry of this current reciprocal physical binding.
    booking_id
        Same-edition current hold identifier, never a foreign booking identifier.
    booking_version
        Current physical version, including independent approval changes.
    review_state
        Physical review state only; no approver identity or Programme approval.
    """

    candidate_id: UUID
    candidate_version: int
    placement_id: UUID
    space_selection_id: UUID
    envelope: SchedulingEnvelope
    booking_id: UUID
    booking_version: int
    review_state: str


@dataclass(frozen=True, slots=True)
class SchedulingReservationReview:
    """Distinguish no request, inactive binding and an independently proved hold.

    Attributes
    ----------
    occurrence_id
        Exact authorized occurrence, including retained retired occurrences.
    state
        Current purpose-bound reservation consequence.
    active
        Exact live reciprocal source proof, or none without historical content.
    """

    occurrence_id: UUID
    state: PlanningReservationState
    active: PlanningActiveReservation | None


def _active_reservation(
    request: SchedulingReadRequest, intent: SchedulingReservationIntent
) -> PlanningActiveReservation | None:
    placement = intent.placement
    if placement.occurrence_revision.occurrence_id != intent.occurrence_id:
        raise SchedulingUnavailableError
    try:
        physical = load_venue_scheduling_dependencies(
            actor_id=request.actor_id,
            **_ownership(request),
            selection_ids=(placement.space_selection_id,),
            placement_ids=(placement.id,),
            correlation_id=request.correlation_id,
            source_channel="scheduling-planning",
        )
    except VenueSchedulingSourceDeniedError as error:
        raise SchedulingAuthorizationDeniedError from error
    except VenueSchedulingSourceUnavailableError as error:
        raise SchedulingUnavailableError from error
    if not physical.reservations:
        return None
    if len(physical.reservations) != 1:
        raise SchedulingUnavailableError
    binding = physical.reservations[0]
    if (
        intent.operation != SchedulingOperation.RESERVATION_REPLACE
        or binding.occurrence_id != intent.occurrence_id
        or binding.placement_id != intent.placement_id
        or binding.booking_id != intent.target_booking_id
    ):
        raise SchedulingUnavailableError
    return PlanningActiveReservation(
        intent.candidate_revision.candidate_id,
        intent.candidate_revision.sequence,
        placement.id,
        placement.space_selection_id,
        SchedulingEnvelope(
            placement.setup_starts_at,
            placement.effective_starts_at,
            placement.effective_ends_at,
            placement.teardown_ends_at,
        ),
        binding.booking_id,
        binding.booking_version,
        binding.review_state,
    )


def load_scheduling_reservation_review(
    request: SchedulingReadRequest,
    *,
    occurrence_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingReservationReview:
    """Resolve the latest ordered intent, then independently prove its physical state.

    Receipt control versions, not timestamps, order the occurrence's attempts.
    Every linked physical hold must originate in such an intent; ordinary Venue
    cancellation can remove it but cannot silently replace or reschedule it.
    A moved/unplaced draft therefore does not hide the previous hold. No host,
    booking title, rationale, private room content or foreign busy periods leave
    this projection. Only read audits are written.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, exact organization/edition and trace attribution.
    occurrence_id : UUID
        Scoped occurrence whose current physical consequence is selected.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent conflict/dependency-read policy or isolated-test admission.

    Returns
    -------
    SchedulingReservationReview
        No recorded request, independently confirmed inactivity, or exact live hold.
    """
    require_identifier(occurrence_id)

    def load(_scope: AuthorizedSchedulingScope) -> SchedulingReservationReview:
        scope = _ownership(request)
        if not SchedulingOccurrence.objects.filter(**scope, id=occurrence_id).exists():
            raise SchedulingUnavailableError
        intent = (
            SchedulingReservationIntent.objects.filter(
                **scope, occurrence_id=occurrence_id
            )
            .select_related("placement__occurrence_revision", "candidate_revision")
            .only(
                "id",
                "operation",
                "occurrence_id",
                "placement_id",
                "target_booking_id",
                "candidate_revision__candidate_id",
                "candidate_revision__sequence",
                "placement__space_selection_id",
                "placement__occurrence_revision__occurrence_id",
                "placement__setup_starts_at",
                "placement__effective_starts_at",
                "placement__effective_ends_at",
                "placement__teardown_ends_at",
            )
            .order_by("-command_receipt__control_version")
            .first()
        )
        if intent is None:
            return SchedulingReservationReview(
                occurrence_id, PlanningReservationState.NOT_REQUESTED, None
            )
        active = _active_reservation(request, intent)
        return SchedulingReservationReview(
            occurrence_id,
            PlanningReservationState.ACTIVE
            if active
            else PlanningReservationState.NOT_ACTIVE,
            active,
        )

    return _read(
        request,
        capability=VIEW_CONFLICTS,
        fields=PREVIEW_FIELDS,
        purpose="reservation_review",
        authorizer=authorizer,
        loader=load,
    )
