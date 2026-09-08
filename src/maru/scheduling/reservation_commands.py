"""Explicit physical hold changes without candidate edits or implicit approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError

from maru.identity.queries import lock_account_references_for_evidence
from maru.venues.scheduling_reservations import apply_scheduling_reservation

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, MANAGE_RESERVATIONS
from .catalogs import SchedulingOperation
from .command_support import SchedulingUnavailableError, _CommandTransaction, _execute
from .inputs import SchedulingCommandRequest, require_identifier, require_version
from .models import SchedulingCandidateMember, SchedulingReservationIntent

if TYPE_CHECKING:
    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult


@dataclass(frozen=True, slots=True)
class SchedulingReservationInput:
    """Exact selected candidate facts and optimistic old physical hold.

    Attributes
    ----------
    candidate_id
        Exact candidate containing the selected immutable placement.
    candidate_version
        Exact candidate revision; replacement requires it to remain current.
    placement_id
        Selected immutable placement, never inferred from a room or label.
    previous_booking_id
        Exact current hold to replace or cancel, absent only for initial reservation.
    expected_booking_version
        Current physical version, zero only when no previous booking is selected.
    """

    candidate_id: UUID
    candidate_version: int
    placement_id: UUID
    previous_booking_id: UUID | None = None
    expected_booking_version: int = 0

    def normalized(self) -> SchedulingReservationInput:
        """Validate typed exact input without resolving authority or current state.

        Returns
        -------
        SchedulingReservationInput
            Unchanged valid immutable input.

        Raises
        ------
        ValidationError
            If a previous booking and expected version are inconsistent.
        """
        require_identifier(self.candidate_id)
        require_identifier(self.placement_id)
        require_version(self.candidate_version)
        require_version(self.expected_booking_version, initial=True)
        if self.previous_booking_id is not None:
            require_identifier(self.previous_booking_id)
        if (self.previous_booking_id is None) != (self.expected_booking_version == 0):
            raise ValidationError(
                "Select an exact previous physical reservation version."
            )
        return self


def _prepare(
    request: SchedulingCommandRequest, intent: SchedulingReservationInput
) -> SchedulingCandidateMember:
    member = (
        SchedulingCandidateMember.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            revision__candidate_id=intent.candidate_id,
            revision__sequence=intent.candidate_version,
            placement_id=intent.placement_id,
        )
        .select_related("placement__introduced_in")
        .only(
            "id",
            "organization_id",
            "edition_id",
            "revision_id",
            "occurrence_id",
            "placement_id",
            "placement__introduced_in__actor_id",
        )
        .first()
    )
    if (
        member is None
        or lock_account_references_for_evidence(
            account_ids=(request.actor_id, member.placement.introduced_in.actor_id)
        )
        is None
    ):
        raise SchedulingUnavailableError
    return member


def change_scheduling_reservation(
    request: SchedulingCommandRequest,
    *,
    reservation: SchedulingReservationInput,
    operation: SchedulingOperation,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Reserve, replace or cancel a physical hold through independent Venue authority.

    Replacement does not edit the candidate or approve either owner. The supplied
    reason is explicitly Venue-visible. Exact retries return the original intent;
    any late failure rolls back both owners and preserves the previous hold.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Exact current attribution, retry key and deliberate physical rationale.
    reservation : SchedulingReservationInput
        Explicit immutable candidate placement and current previous booking version.
    operation : SchedulingOperation
        Only RESERVATION_REPLACE or RESERVATION_CANCEL is accepted.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Scheduling policy; the Venue adapter separately proves its own authority.

    Returns
    -------
    SchedulingCommandResult
        Immutable completed reservation intent, retaining both owner receipt links.

    Raises
    ------
    ValidationError
        If an operation is not one of the two explicit reservation changes.
    """
    if not isinstance(operation, SchedulingOperation) or operation not in (
        SchedulingOperation.RESERVATION_REPLACE,
        SchedulingOperation.RESERVATION_CANCEL,
    ):
        raise ValidationError("Select an explicit physical reservation operation.")

    def normalize() -> SchedulingReservationInput:
        intent = reservation.normalized()
        if (
            operation == SchedulingOperation.RESERVATION_CANCEL
            and intent.previous_booking_id is None
        ):
            raise ValidationError(
                "Cancellation requires an exact previous reservation."
            )
        return intent

    def write(
        context: _CommandTransaction,
        intent: SchedulingReservationInput,
        member: SchedulingCandidateMember,
    ) -> tuple[UUID, int]:
        source = SchedulingReservationIntent.objects.create(
            **context.evidence(),
            command_receipt_id=context.receipt_id,
            venue_receipt_id=uuid4(),
            candidate_revision_id=member.revision_id,
            occurrence_id=member.occurrence_id,
            placement_id=member.placement_id,
            operation=operation.value,
            previous_booking_id=intent.previous_booking_id,
            expected_booking_version=intent.expected_booking_version,
            target_booking_id=uuid4()
            if operation == SchedulingOperation.RESERVATION_REPLACE
            else None,
        )
        apply_scheduling_reservation(
            actor_id=context.request.actor_id,
            organization_id=context.request.organization_id,
            edition_id=context.request.edition_id,
            intent_id=source.id,
            correlation_id=context.request.correlation_id,
            source_channel=context.request.source_channel,
        )
        return source.id, 1

    return _execute(
        request,
        operation=operation,
        capability=MANAGE_RESERVATIONS,
        normalize=normalize,
        payload=lambda intent: {
            "candidate_id": str(intent.candidate_id),
            "candidate_version": intent.candidate_version,
            "placement_id": str(intent.placement_id),
            "previous_booking_id": str(intent.previous_booking_id)
            if intent.previous_booking_id
            else None,
            "expected_booking_version": intent.expected_booking_version,
        },
        prepare=lambda intent: _prepare(request, intent),
        write=write,
        authorizer=authorizer,
    )
