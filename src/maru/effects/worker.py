"""Idempotent handler contract and one-effect worker execution."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.effects.models import DomainEvent, OutboxMessage
from maru.effects.registry import event_definition, validate_event_payload
from maru.effects.services import (
    MAX_LEASE_DURATION,
    ClaimedEffect,
    ClaimOutcome,
    LeaseLostError,
    finish_effect_permanent_failure,
    finish_effect_success,
    finish_effect_transient_failure,
    validate_effect_error_code,
)

DEFAULT_RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class EffectContext:
    event_id: UUID
    idempotency_key: str
    organization_id: UUID
    correlation_id: UUID
    attempt_number: int
    deadline: datetime


class EffectHandler(Protocol):
    def __call__(self, event: DomainEvent, context: EffectContext) -> None: ...


@dataclass(frozen=True, slots=True)
class HandlerRegistration:
    event_name: str
    destination: str
    handler: EffectHandler


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], EffectHandler] = {}

    def register(self, registration: HandlerRegistration) -> None:
        if event_definition(registration.event_name) is None:
            raise ValidationError(
                "Handlers require a registered domain event.",
                code="unknown_domain_event",
            )
        key = (registration.event_name, registration.destination)
        if key in self._handlers:
            raise ValidationError(
                "Only one handler may own an event destination.",
                code="duplicate_effect_handler",
            )
        self._handlers[key] = registration.handler

    def resolve(self, *, event_name: str, destination: str) -> EffectHandler | None:
        return self._handlers.get((event_name, destination))


class TransientEffectError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        *,
        retry_after: timedelta = DEFAULT_RETRY_DELAY,
    ) -> None:
        super().__init__(error_code)
        validate_effect_error_code(error_code)
        self.error_code = error_code
        self.retry_after = retry_after


class PermanentEffectError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        validate_effect_error_code(error_code)
        self.error_code = error_code


class EffectTimeoutError(TransientEffectError):
    def __init__(self) -> None:
        super().__init__("handler_timeout")


class RunOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    QUARANTINED = "quarantined"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True, slots=True)
class RunResult:
    outcome: RunOutcome
    error_code: str = ""


def _active_message(claim: ClaimedEffect, *, now: datetime) -> OutboxMessage | None:
    if now >= claim.lease_expires_at:
        return None
    return (
        OutboxMessage.objects.select_related("event")
        .filter(
            id=claim.message_id,
            event_id=claim.event_id,
            status=OutboxMessage.Status.PROCESSING,
            lease_token=claim.lease_token,
            attempt_count=claim.attempt_number,
            lease_expires_at__gt=now,
        )
        .first()
    )


def _mark_permanent(
    claim: ClaimedEffect,
    *,
    error_code: str,
) -> RunResult:
    try:
        finish_effect_permanent_failure(claim, error_code=error_code)
    except LeaseLostError:
        return RunResult(RunOutcome.LEASE_LOST, "lease_lost")
    return RunResult(RunOutcome.QUARANTINED, error_code)


def _mark_transient(
    claim: ClaimedEffect,
    *,
    error_code: str,
    retry_after: timedelta,
) -> RunResult:
    try:
        outcome = finish_effect_transient_failure(
            claim,
            error_code=error_code,
            retry_after=retry_after,
        )
    except LeaseLostError:
        return RunResult(RunOutcome.LEASE_LOST, "lease_lost")
    if outcome is ClaimOutcome.QUARANTINED:
        return RunResult(RunOutcome.QUARANTINED, error_code)
    return RunResult(RunOutcome.RETRY_SCHEDULED, error_code)


def _ensure_before_deadline(*, now: datetime, deadline: datetime) -> None:
    if now >= deadline:
        raise EffectTimeoutError


def run_claimed_effect(  # noqa: PLR0911 - terminal worker states stay explicit
    claim: ClaimedEffect,
    *,
    handlers: HandlerRegistry,
    execution_timeout: timedelta,
    clock: Callable[[], datetime] = timezone.now,
) -> RunResult:
    if execution_timeout <= timedelta(0) or execution_timeout > MAX_LEASE_DURATION:
        raise ValidationError(
            "Execution timeout must be positive and no more than 15 minutes.",
            code="invalid_execution_timeout",
        )
    started_at = clock()
    message = _active_message(claim, now=started_at)
    if message is None:
        return RunResult(RunOutcome.LEASE_LOST, "lease_lost")

    try:
        validate_event_payload(
            event_name=message.event.event_name,
            schema_version=message.event.schema_version,
            payload=message.event.payload,
        )
    except ValidationError:
        return _mark_permanent(claim, error_code="invalid_event_payload")

    handler = handlers.resolve(
        event_name=message.event.event_name,
        destination=message.destination,
    )
    if handler is None:
        return _mark_permanent(claim, error_code="handler_not_registered")

    context = EffectContext(
        event_id=message.event_id,
        idempotency_key=str(message.event_id),
        organization_id=message.organization_id,
        correlation_id=message.event.correlation_id,
        attempt_number=claim.attempt_number,
        deadline=min(claim.lease_expires_at, started_at + execution_timeout),
    )
    try:
        handler(message.event, context)
        _ensure_before_deadline(now=clock(), deadline=context.deadline)
    except PermanentEffectError as error:
        return _mark_permanent(claim, error_code=error.error_code)
    except TransientEffectError as error:
        return _mark_transient(
            claim,
            error_code=error.error_code,
            retry_after=error.retry_after,
        )
    except Exception:  # noqa: BLE001 - unexpected handlers are safely retried
        return _mark_transient(
            claim,
            error_code="unhandled_handler_error",
            retry_after=DEFAULT_RETRY_DELAY,
        )

    try:
        finish_effect_success(claim)
    except LeaseLostError:
        return RunResult(RunOutcome.LEASE_LOST, "lease_lost")
    return RunResult(RunOutcome.SUCCEEDED)
