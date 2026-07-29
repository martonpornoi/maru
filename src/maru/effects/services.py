"""Transactional publishing, tenant-bounded claims, and delivery outcomes."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from maru.effects.models import DomainEvent, EffectAttempt, OutboxMessage
from maru.effects.registry import validate_event_payload

DEFAULT_MAX_ATTEMPTS = 8
MAX_LEASE_DURATION = timedelta(minutes=15)
MAX_RETRY_DELAY = timedelta(days=1)
MAX_EFFECT_ERROR_CODE_LENGTH = 120
SAFE_EFFECT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class DomainEventRecord:
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
    message_id: UUID
    event_id: UUID
    lease_token: UUID
    attempt_number: int
    claimed_at: datetime
    lease_expires_at: datetime


class ClaimOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    QUARANTINED = "quarantined"


class LeaseLostError(RuntimeError):
    """The delivery is no longer owned by this worker."""


class CancellationBoundaryPassedError(RuntimeError):
    """An effect already crossed from pending into handler execution."""


def validate_effect_error_code(value: str) -> None:
    if len(
        value
    ) > MAX_EFFECT_ERROR_CODE_LENGTH or not SAFE_EFFECT_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable safe effect error code.",
            code="invalid_effect_error_code",
        )


def publish_domain_event(
    record: DomainEventRecord,
    *,
    destination: str = "internal",
    workload_pool: str = "default",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    occurred_at: datetime | None = None,
) -> tuple[DomainEvent, OutboxMessage]:
    connection = transaction.get_connection()
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Domain events must be published inside the canonical state transaction."
        )
    if max_attempts < 1:
        raise ValidationError(
            "Outbox maximum attempts must be positive.",
            code="invalid_max_attempts",
        )
    validate_event_payload(
        event_name=record.event_name,
        schema_version=record.schema_version,
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
    """Add another durable destination for an event inside its transaction."""

    connection = transaction.get_connection()
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Domain-event deliveries must be enqueued inside the canonical "
            "state transaction."
        )
    if max_attempts < 1:
        raise ValidationError(
            "Outbox maximum attempts must be positive.",
            code="invalid_max_attempts",
        )
    return OutboxMessage.objects.create(
        event=event,
        organization_id=event.organization_id,
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
    now: datetime | None = None,
) -> OutboxMessage:
    if additional_attempts < 1:
        raise ValidationError(
            "A replay must allow at least one additional attempt.",
            code="invalid_replay_attempts",
        )
    message = OutboxMessage.objects.select_for_update().get(id=message_id)
    if message.status != OutboxMessage.Status.QUARANTINED:
        raise ValidationError(
            "Only quarantined effects can be replayed.",
            code="effect_not_quarantined",
        )
    message.max_attempts += additional_attempts
    message.status = OutboxMessage.Status.PENDING
    message.available_at = now or timezone.now()
    message.completed_at = None
    message.last_error_code = ""
    message.replay_count += 1
    message.save()
    return message
