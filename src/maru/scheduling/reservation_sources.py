"""Owned in-transaction source proof for the governed Venue reservation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_edition_time_envelope_reference,
)

from .adoption import SCHEDULING_VENUE_RESERVATION_ADAPTER
from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    MANAGE_RESERVATIONS,
    authorize_scheduling_scope,
)
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingUnavailableError,
)
from .inputs import require_identifier
from .models import (
    SchedulingCandidateMember,
    SchedulingPlacementRevision,
    SchedulingReservationIntent,
)
from .time_rules import SchedulingEnvelope, SchedulingWindow, placement_fits_service_day
from .writer_boundary import _require_active_receipt

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer


@dataclass(frozen=True, slots=True)
class SchedulingReservationSource:
    """Exact physical intent, never a caller-forged approval or copied Programme layer.

    Attributes
    ----------
    intent_id
        Immutable Scheduling-owned in-progress intent.
    command_receipt_id
        Exact reserved Scheduling receipt completed in the same transaction.
    venue_receipt_id
        Exact reserved Venue receipt for either replacement or cancellation.
    actor_id
        Current person accountable for both owners' reservation evidence.
    organization_id
        Exact common organization owner.
    edition_id
        Exact common edition owner.
    operation
        Closed reservation replacement or cancellation operation.
    occurrence_id
        Stable Programme occurrence, independent of candidate alternatives.
    placement_id
        Immutable selected physical placement revision.
    space_selection_id
        Exact Venue selection that must independently authorize and validate use.
    placement_actor_id
        Retained original physical-placement author excluded from Venue approval.
    envelope
        Complete explicit physical work envelope, not personal availability.
    capacity_mode
        Explicit selected physical configuration mode.
    expected_attendance
        Positive explicit planning estimate.
    previous_booking_id
        Exact previous reservation when replacing or cancelling an existing hold.
    expected_booking_version
        Exact previous booking version, zero only for an initial reservation.
    target_booking_id
        Reserved new booking identity for replacement, absent for cancellation.
    reason
        Deliberate Venue-visible reservation rationale, never the old placement reason.
    """

    intent_id: UUID
    command_receipt_id: UUID
    venue_receipt_id: UUID
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    operation: str
    occurrence_id: UUID
    placement_id: UUID
    space_selection_id: UUID
    placement_actor_id: UUID
    envelope: SchedulingEnvelope
    capacity_mode: str
    expected_attendance: int
    previous_booking_id: UUID | None
    expected_booking_version: int
    target_booking_id: UUID | None
    reason: str


def _active_intent(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, intent_id: UUID
) -> SchedulingReservationIntent:
    source = (
        SchedulingReservationIntent.objects.filter(
            id=intent_id,
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related(
            "placement__introduced_in", "candidate_revision__candidate", "occurrence"
        )
        .only(
            "id",
            "actor_id",
            "organization_id",
            "edition_id",
            "command_receipt_id",
            "venue_receipt_id",
            "candidate_revision_id",
            "occurrence_id",
            "placement_id",
            "operation",
            "previous_booking_id",
            "expected_booking_version",
            "target_booking_id",
            "reason",
            "occurrence__lifecycle",
            "candidate_revision__sequence",
            "candidate_revision__candidate__lifecycle",
            "candidate_revision__candidate__aggregate_version",
            "placement__space_selection_id",
            "placement__introduced_in__actor_id",
            "placement__setup_starts_at",
            "placement__effective_starts_at",
            "placement__effective_ends_at",
            "placement__teardown_ends_at",
            "placement__capacity_mode",
            "placement__expected_attendance",
        )
        .first()
    )
    if source is None:
        raise SchedulingUnavailableError
    try:
        _require_active_receipt(source.command_receipt_id)
    except ValidationError as error:
        raise SchedulingUnavailableError from error
    if not SchedulingCandidateMember.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        revision_id=source.candidate_revision_id,
        occurrence_id=source.occurrence_id,
        placement_id=source.placement_id,
    ).exists():
        raise SchedulingUnavailableError
    if source.operation == "reservation_replace" and (
        source.occurrence.lifecycle != "active"
        or source.candidate_revision.candidate.lifecycle != "draft"
        or source.candidate_revision.candidate.aggregate_version
        != source.candidate_revision.sequence
    ):
        raise SchedulingLifecycleConflictError
    return source


def _require_current_physical_intent(source: SchedulingReservationIntent) -> None:
    selected_day = (
        SchedulingPlacementRevision.objects.filter(
            id=source.placement_id,
            organization_id=source.organization_id,
            edition_id=source.edition_id,
            occurrence_revision__occurrence_id=source.occurrence_id,
            occurrence_revision__sequence=F(
                "occurrence_revision__occurrence__aggregate_version"
            ),
            occurrence_revision__occurrence__lifecycle="active",
            day_revision__sequence=F("day_revision__day__aggregate_version"),
            day_revision__day__lifecycle="active",
        )
        .values_list(
            "day_revision__starts_at",
            "day_revision__ends_at",
            "day_revision__precision_minutes",
        )
        .first()
    )
    edition = resolve_edition_time_envelope_reference(
        organization_id=source.organization_id, edition_id=source.edition_id
    )
    if selected_day is None or edition is None:
        raise SchedulingUnavailableError
    placement = source.placement
    if not (
        edition.starts_at <= selected_day[0] < selected_day[1] <= edition.ends_at
        and placement_fits_service_day(
            SchedulingEnvelope(
                placement.setup_starts_at,
                placement.effective_starts_at,
                placement.effective_ends_at,
                placement.teardown_ends_at,
            ),
            window=SchedulingWindow(selected_day[0], selected_day[1]),
            precision_minutes=selected_day[2],
        )
    ):
        raise SchedulingUnavailableError


def resolve_scheduling_reservation_source(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    intent_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingReservationSource:
    """Revalidate one owned intent only while its parent Scheduling command is active.

    This internal adapter query returns no Programme title, proposal, private
    delivery, host availability or original placement rationale. The newly
    supplied reservation reason is deliberately shared with Venue history.
    It is not a public mutation endpoint or an approval credential.

    Parameters
    ----------
    actor_id : UUID
        Exact current person who owns the in-progress intent.
    organization_id : UUID
        Expected common source and target organization.
    edition_id : UUID
        Expected exact source and target edition.
    intent_id : UUID
        Scheduling-owned immutable source identity, not an unchecked external reference.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or independently sealed isolated-test substitute.

    Returns
    -------
    SchedulingReservationSource
        Exact current source and reserved target proof for the independent Venue owner.

    Raises
    ------
    SchedulingUnavailableError
        If transaction, active receipt or exact pinned source proof is unavailable.
    SchedulingLifecycleConflictError
        If current Scheduling or selected candidate lifecycle rejects the reservation.
    """
    for value in (actor_id, organization_id, edition_id, intent_id):
        require_identifier(value)
    if not connection.in_atomic_block:
        raise SchedulingUnavailableError
    scope = authorize_scheduling_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=MANAGE_RESERVATIONS,
        authorizer=authorizer,
        lock=True,
    )
    if not scope.accepts_writes:
        raise SchedulingLifecycleConflictError
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_VENUE_RESERVATION_ADAPTER
    ):
        raise SchedulingUnavailableError
    source = _active_intent(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        intent_id=intent_id,
    )
    if source.operation == "reservation_replace":
        _require_current_physical_intent(source)
    placement = source.placement
    return SchedulingReservationSource(
        source.id,
        source.command_receipt_id,
        source.venue_receipt_id,
        actor_id,
        organization_id,
        edition_id,
        source.operation,
        source.occurrence_id,
        source.placement_id,
        placement.space_selection_id,
        placement.introduced_in.actor_id,
        SchedulingEnvelope(
            placement.setup_starts_at,
            placement.effective_starts_at,
            placement.effective_ends_at,
            placement.teardown_ends_at,
        ),
        placement.capacity_mode,
        placement.expected_attendance,
        source.previous_booking_id,
        source.expected_booking_version,
        source.target_booking_id,
        source.reason,
    )
