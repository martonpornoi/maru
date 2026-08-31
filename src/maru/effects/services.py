"""Transactional publishing, tenant-bounded claims, and delivery outcomes."""

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from maru.effects.adoption import require_effect_delivery_allowed
from maru.effects.models import (
    MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS,
    MAX_EFFECT_REPLAY_REASON_LENGTH,
    MAX_EFFECT_TOTAL_ATTEMPTS,
    DomainEvent,
    EffectAttempt,
    EffectReplayReceipt,
    OutboxMessage,
)
from maru.effects.registry import validate_event_payload

DEFAULT_MAX_ATTEMPTS = 8
MAX_LEASE_DURATION = timedelta(minutes=15)
MAX_RETRY_DELAY = timedelta(days=1)
MAX_EFFECT_ERROR_CODE_LENGTH = 120
SAFE_EFFECT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _validate_effect_attempt_budget(value: object) -> int:
    """Return one initial attempt budget inside the global safety bound.

    Parameters
    ----------
    value : object
        Untrusted initial attempt budget.

    Returns
    -------
    int
        Validated budget between one and the global cumulative limit.

    Raises
    ------
    ValidationError
        If the budget is not an integer inside the closed safety bound.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_EFFECT_TOTAL_ATTEMPTS
    ):
        raise ValidationError(
            (
                "Outbox maximum attempts must be between 1 and "
                f"{MAX_EFFECT_TOTAL_ATTEMPTS}."
            ),
            code="invalid_max_attempts",
        )
    return value


def normalize_effect_replay_reason(value: object) -> str:
    """Return one bounded, canonical operator replay rationale.

    Parameters
    ----------
    value : object
        Untrusted operator input.

    Returns
    -------
    str
        NFC-normalized rationale with internal whitespace collapsed.

    Raises
    ------
    ValidationError
        If the rationale is absent, not text, or exceeds the retained bound.
    """
    if not isinstance(value, str):
        raise ValidationError(
            "A replay reason must be text.",
            code="reason_invalid",
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized:
        raise ValidationError(
            "A replay reason is required.",
            code="reason_required",
        )
    if len(normalized) > MAX_EFFECT_REPLAY_REASON_LENGTH:
        raise ValidationError(
            (
                "A replay reason cannot exceed "
                f"{MAX_EFFECT_REPLAY_REASON_LENGTH} characters."
            ),
            code="reason_too_long",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class DomainEventRecord:
    """Describe domain event record.

    Attributes
    ----------
    event_name
        The human-readable event name shown to authorized readers.
    schema_version
        The expected schema version used to reject stale updates.
    organization_id
        The organization identifier that owns the requested resource.
    event_edition_id
        The event edition identifier within the requested scope.
    aggregate_type
        The stable domain type of the target aggregate.
    aggregate_id
        The aggregate identifier whose state is being read or changed.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    payload
        The untrusted payload to validate before domain use.
    correlation_id
        The request correlation identifier used for audit tracing.
    causation_id
        The causation identifier within the requested scope.
    actor_kind
        The closed actor kind discriminator defined by the domain catalog.
    actor_id
        The immutable identifier of the account authorizing the operation.
    retention_class
        The retention class retained in this immutable projection.
    """

    event_name: str
    schema_version: int
    organization_id: UUID
    event_edition_id: UUID | None
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    payload: dict[str, object]
    correlation_id: UUID
    causation_id: UUID | None
    actor_kind: str
    actor_id: UUID | None
    retention_class: str = "domain-standard"


@dataclass(frozen=True, slots=True)
class ClaimedEffect:
    """Describe claimed effect.

    Attributes
    ----------
    message_id
        The message identifier within the requested scope.
    event_id
        The immutable identifier of the domain event to process.
    lease_token
        The opaque lease token supplied by the caller.
    attempt_number
        The attempt number retained in this immutable projection.
    claimed_at
        The timezone-aware timestamp for claimed.
    lease_expires_at
        The timezone-aware timestamp for lease expires.
    """

    message_id: UUID
    event_id: UUID
    lease_token: UUID
    attempt_number: int
    claimed_at: datetime
    lease_expires_at: datetime


class ClaimOutcome(StrEnum):
    """Enumerate supported claim outcome values."""

    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    QUARANTINED = "quarantined"


class LeaseLostError(RuntimeError):
    """The delivery is no longer owned by this worker."""


class CancellationBoundaryPassedError(RuntimeError):
    """An effect already crossed from pending into handler execution."""


def validate_effect_error_code(value: str) -> None:
    """Validate effect error code.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if len(
        value
    ) > MAX_EFFECT_ERROR_CODE_LENGTH or not SAFE_EFFECT_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable safe effect error code.",
            code="invalid_effect_error_code",
        )


def publish_domain_event(  # noqa: DOC503 - delegated validators raise ValidationError
    record: DomainEventRecord,
    *,
    destination: str = "internal",
    workload_pool: str = "default",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    occurred_at: datetime | None = None,
) -> tuple[DomainEvent, OutboxMessage]:
    """Publish domain event.

    Parameters
    ----------
    record : DomainEventRecord
        The domain record to validate, persist, or project.
    destination : str, default='internal'
        The registered destination that should receive the effect.
    workload_pool : str, default='default'
        The named worker pool that owns the work.
    max_attempts : int, default=DEFAULT_MAX_ATTEMPTS
        The max attempts applied within the audited domain transition.
    occurred_at : datetime | None, default=None
        The time at which the event occurred.

    Returns
    -------
    tuple[DomainEvent, OutboxMessage]
        The published domain event.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    connection = transaction.get_connection()
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Domain events must be published inside the canonical state transaction."
        )
    max_attempts = _validate_effect_attempt_budget(max_attempts)
    validate_event_payload(
        event_name=record.event_name,
        schema_version=record.schema_version,
        payload=record.payload,
    )
    require_effect_delivery_allowed(
        organization_id=record.organization_id,
        event_edition_id=record.event_edition_id,
        event_name=record.event_name,
        destination=destination,
        payload=record.payload,
    )
    event_values = asdict(record)
    event = DomainEvent.objects.create(
        occurred_at=occurred_at or timezone.now(),
        **event_values,
    )
    message = OutboxMessage.objects.create(
        event=event,
        organization_id=record.organization_id,
        destination=destination,
        workload_pool=workload_pool,
        available_at=timezone.now(),
        max_attempts=max_attempts,
    )
    return event, message


def enqueue_event_delivery(
    *,
    event: DomainEvent,
    destination: str,
    workload_pool: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> OutboxMessage:
    """Add another durable destination for an event inside its transaction.

    Parameters
    ----------
    event : DomainEvent
        The immutable domain event to process.
    destination : str
        The registered destination that should receive the effect.
    workload_pool : str
        The workload pool applied within the audited domain transition.
    max_attempts : int, default=DEFAULT_MAX_ATTEMPTS
        The max attempts applied within the audited domain transition.

    Returns
    -------
    OutboxMessage
        The resolved OutboxMessage for enqueue event delivery.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    connection = transaction.get_connection()
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Domain-event deliveries must be enqueued inside the canonical "
            "state transaction."
        )
    max_attempts = _validate_effect_attempt_budget(max_attempts)
    persisted_event = (
        DomainEvent.objects.filter(pk=event.pk)
        .only(
            "event_name",
            "event_edition_id",
            "organization_id",
            "payload",
        )
        .first()
    )
    if persisted_event is None:
        raise ValidationError(
            "The domain event is unavailable for delivery.",
            code="domain_event_unavailable",
        )
    require_effect_delivery_allowed(
        organization_id=persisted_event.organization_id,
        event_edition_id=persisted_event.event_edition_id,
        event_name=persisted_event.event_name,
        destination=destination,
        payload=persisted_event.payload,
    )
    return OutboxMessage.objects.create(
        event=persisted_event,
        organization_id=persisted_event.organization_id,
        destination=destination,
        workload_pool=workload_pool,
        available_at=timezone.now(),
        max_attempts=max_attempts,
    )


@transaction.atomic
def claim_next_effect(
    *,
    organization_id: UUID,
    workload_pool: str,
    lease_duration: timedelta,
    now: datetime | None = None,
) -> ClaimedEffect | None:
    """Claim next effect.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    workload_pool : str
        The named worker pool that owns the work.
    lease_duration : timedelta
        The lease duration applied within the audited domain transition.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    ClaimedEffect | None
        The matching ClaimedEffect, or `None` when no authorized record exists.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if lease_duration <= timedelta(0) or lease_duration > MAX_LEASE_DURATION:
        raise ValidationError(
            "Lease duration must be positive and no more than 15 minutes.",
            code="invalid_lease_duration",
        )
    claimed_at = now or timezone.now()
    expired = Q(
        status=OutboxMessage.Status.PROCESSING,
        lease_expires_at__lte=claimed_at,
    )
    ready = Q(
        status=OutboxMessage.Status.PENDING,
        available_at__lte=claimed_at,
    )
    candidates = OutboxMessage.objects.select_for_update(skip_locked=True).filter(
        Q(ready | expired),
        organization_id=organization_id,
        workload_pool=workload_pool,
        attempt_count__lt=F("max_attempts"),
    )
    message = candidates.order_by("available_at", "created_at", "id").first()
    if message is None:
        _quarantine_exhausted(
            organization_id=organization_id,
            workload_pool=workload_pool,
            now=claimed_at,
        )
        return None

    if (
        message.status == OutboxMessage.Status.PROCESSING
        and message.lease_token is not None
        and message.claimed_at is not None
    ):
        EffectAttempt.objects.create(
            outbox_message=message,
            attempt_number=message.attempt_count,
            lease_token=message.lease_token,
            started_at=message.claimed_at,
            finished_at=claimed_at,
            outcome=EffectAttempt.Outcome.TRANSIENT_FAILURE,
            error_code="lease_expired",
            handler_code=message.destination,
        )

    lease_token = uuid4()
    message.status = OutboxMessage.Status.PROCESSING
    message.claimed_at = claimed_at
    message.lease_expires_at = claimed_at + lease_duration
    message.lease_token = lease_token
    message.attempt_count += 1
    message.completed_at = None
    message.save()
    return ClaimedEffect(
        message_id=message.id,
        event_id=message.event_id,
        lease_token=lease_token,
        attempt_number=message.attempt_count,
        claimed_at=claimed_at,
        lease_expires_at=message.lease_expires_at,
    )


def _quarantine_exhausted(
    *,
    organization_id: UUID,
    workload_pool: str,
    now: datetime,
) -> None:
    exhausted = list(
        OutboxMessage.objects.select_for_update(skip_locked=True).filter(
            organization_id=organization_id,
            workload_pool=workload_pool,
            status=OutboxMessage.Status.PROCESSING,
            lease_expires_at__lte=now,
            attempt_count__gte=F("max_attempts"),
        )
    )
    for message in exhausted:
        lease_token = message.lease_token
        if lease_token is None or message.claimed_at is None:
            continue
        message.status = OutboxMessage.Status.QUARANTINED
        message.completed_at = now
        message.lease_expires_at = None
        message.lease_token = None
        message.last_error_code = "attempts_exhausted"
        message.save()
        EffectAttempt.objects.create(
            outbox_message=message,
            attempt_number=message.attempt_count,
            lease_token=lease_token,
            started_at=message.claimed_at,
            finished_at=now,
            outcome=EffectAttempt.Outcome.EXHAUSTED,
            error_code="attempts_exhausted",
            handler_code=message.destination,
        )


def _locked_claim(claim: ClaimedEffect) -> OutboxMessage:
    message = (
        OutboxMessage.objects.select_for_update()
        .select_related("event")
        .filter(
            id=claim.message_id,
            event_id=claim.event_id,
            status=OutboxMessage.Status.PROCESSING,
            lease_token=claim.lease_token,
            attempt_count=claim.attempt_number,
        )
        .first()
    )
    if message is None:
        raise LeaseLostError("Effect lease is no longer active.")
    return message


@transaction.atomic
def finish_effect_success(
    claim: ClaimedEffect,
    *,
    finished_at: datetime | None = None,
) -> None:
    """Finish effect success.

    Parameters
    ----------
    claim : ClaimedEffect
        The claimed work item to process.
    finished_at : datetime | None, default=None
        The time at which processing finished.
    """
    message = _locked_claim(claim)
    finished = finished_at or timezone.now()
    message.status = OutboxMessage.Status.SUCCEEDED
    message.completed_at = finished
    message.lease_expires_at = None
    message.lease_token = None
    message.last_error_code = ""
    message.save()
    EffectAttempt.objects.create(
        outbox_message=message,
        attempt_number=claim.attempt_number,
        lease_token=claim.lease_token,
        started_at=claim.claimed_at,
        finished_at=finished,
        outcome=EffectAttempt.Outcome.SUCCEEDED,
        handler_code=message.destination,
    )


@transaction.atomic
def finish_effect_transient_failure(
    claim: ClaimedEffect,
    *,
    error_code: str,
    retry_after: timedelta,
    finished_at: datetime | None = None,
) -> ClaimOutcome:
    """Finish effect transient failure.

    Parameters
    ----------
    claim : ClaimedEffect
        The claimed work item to process.
    error_code : str
        The stable error code from the relevant closed catalog.
    retry_after : timedelta
        The timezone-aware boundary for retry after.
    finished_at : datetime | None, default=None
        The time at which processing finished.

    Returns
    -------
    ClaimOutcome
        The ClaimOutcome established after finish effect transient failure completes.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    validate_effect_error_code(error_code)
    if retry_after < timedelta(0) or retry_after > MAX_RETRY_DELAY:
        raise ValidationError(
            "Retry delay must be between zero and one day.",
            code="invalid_retry_delay",
        )
    message = _locked_claim(claim)
    finished = finished_at or timezone.now()
    exhausted = message.attempt_count >= message.max_attempts
    message.status = (
        OutboxMessage.Status.QUARANTINED if exhausted else OutboxMessage.Status.PENDING
    )
    message.available_at = finished + retry_after
    message.completed_at = finished if exhausted else None
    message.lease_expires_at = None
    message.lease_token = None
    message.last_error_code = error_code
    message.save()
    EffectAttempt.objects.create(
        outbox_message=message,
        attempt_number=claim.attempt_number,
        lease_token=claim.lease_token,
        started_at=claim.claimed_at,
        finished_at=finished,
        outcome=(
            EffectAttempt.Outcome.EXHAUSTED
            if exhausted
            else EffectAttempt.Outcome.TRANSIENT_FAILURE
        ),
        error_code=error_code,
        handler_code=message.destination,
    )
    return ClaimOutcome.QUARANTINED if exhausted else ClaimOutcome.RETRY_SCHEDULED


@transaction.atomic
def finish_effect_permanent_failure(
    claim: ClaimedEffect,
    *,
    error_code: str,
    finished_at: datetime | None = None,
) -> None:
    """Finish effect permanent failure.

    Parameters
    ----------
    claim : ClaimedEffect
        The claimed work item to process.
    error_code : str
        The stable error code from the relevant closed catalog.
    finished_at : datetime | None, default=None
        The time at which processing finished.
    """
    validate_effect_error_code(error_code)
    message = _locked_claim(claim)
    finished = finished_at or timezone.now()
    message.status = OutboxMessage.Status.QUARANTINED
    message.completed_at = finished
    message.lease_expires_at = None
    message.lease_token = None
    message.last_error_code = error_code
    message.save()
    EffectAttempt.objects.create(
        outbox_message=message,
        attempt_number=claim.attempt_number,
        lease_token=claim.lease_token,
        started_at=claim.claimed_at,
        finished_at=finished,
        outcome=EffectAttempt.Outcome.PERMANENT_FAILURE,
        error_code=error_code,
        handler_code=message.destination,
    )


@transaction.atomic
def cancel_pending_effect(
    *,
    message_id: UUID,
    reason_code: str,
    now: datetime | None = None,
) -> None:
    """Cancel pending effect.

    Parameters
    ----------
    message_id : UUID
        The identifier of the message.
    reason_code : str
        The stable reason code from the relevant closed catalog.
    now : datetime | None, default=None
        The effective time for the operation.

    Raises
    ------
    CancellationBoundaryPassedError
        If the operation encounters a cancellation boundary passed condition.
    """
    validate_effect_error_code(reason_code)
    message = OutboxMessage.objects.select_for_update().get(id=message_id)
    if message.status == OutboxMessage.Status.PROCESSING:
        raise CancellationBoundaryPassedError(
            "The handler execution boundary has already been crossed."
        )
    if message.status != OutboxMessage.Status.PENDING:
        return
    message.status = OutboxMessage.Status.CANCELLED
    message.completed_at = now or timezone.now()
    message.last_error_code = reason_code
    message.save()


@transaction.atomic
def replay_quarantined_effect(
    *,
    message_id: UUID,
    additional_attempts: int,
    actor_id: UUID,
    reason: str,
    correlation_id: UUID,
    now: datetime | None = None,
) -> OutboxMessage:
    """Replay quarantined effect.

    Parameters
    ----------
    message_id : UUID
        The identifier of the message.
    additional_attempts : int
        The additional attempts applied within the audited domain transition.
    actor_id : UUID
        The account identifier authorizing the replay.
    reason : str
        The bounded operator rationale retained with the transition.
    correlation_id : UUID
        The command correlation identifier retained with the transition.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    OutboxMessage
        The OutboxMessage established after replay quarantined effect completes.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if (
        isinstance(additional_attempts, bool)
        or not isinstance(additional_attempts, int)
        or not 1 <= additional_attempts <= MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS
    ):
        raise ValidationError(
            (
                "A replay must allow between 1 and "
                f"{MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS} additional attempts."
            ),
            code="invalid_replay_attempts",
        )
    normalized_reason = normalize_effect_replay_reason(reason)
    message = (
        OutboxMessage.objects.select_for_update()
        .select_related("event")
        .get(id=message_id)
    )
    if message.status != OutboxMessage.Status.QUARANTINED:
        raise ValidationError(
            "Only quarantined effects can be replayed.",
            code="effect_not_quarantined",
        )
    if message.event.organization_id != message.organization_id:
        raise ValidationError(
            "The effect route is unavailable for this scope or edition profile.",
            code="effect_profile_not_allowed",
        )
    require_effect_delivery_allowed(
        organization_id=message.organization_id,
        event_edition_id=message.event.event_edition_id,
        event_name=message.event.event_name,
        destination=message.destination,
        payload=message.event.payload,
    )
    previous_max_attempts = message.max_attempts
    new_max_attempts = previous_max_attempts + additional_attempts
    if new_max_attempts > MAX_EFFECT_TOTAL_ATTEMPTS:
        raise ValidationError(
            (
                "Replay would exceed the total safety limit of "
                f"{MAX_EFFECT_TOTAL_ATTEMPTS} attempts."
            ),
            code="effect_replay_attempt_limit",
        )
    replay_count = message.replay_count + 1
    EffectReplayReceipt.objects.create(
        outbox_message=message,
        organization_id=message.organization_id,
        actor_id=actor_id,
        reason=normalized_reason,
        additional_attempts=additional_attempts,
        previous_max_attempts=previous_max_attempts,
        new_max_attempts=new_max_attempts,
        replay_count=replay_count,
        correlation_id=correlation_id,
    )
    message.max_attempts = new_max_attempts
    message.status = OutboxMessage.Status.PENDING
    message.available_at = now or timezone.now()
    message.completed_at = None
    message.last_error_code = ""
    message.replay_count = replay_count
    message.save()
    return message
