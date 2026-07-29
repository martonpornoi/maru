from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.effects.models import DomainEvent, EffectAttempt, OutboxMessage
from maru.effects.services import (
    CancellationBoundaryPassedError,
    DomainEventRecord,
    cancel_pending_effect,
    claim_next_effect,
    publish_domain_event,
    replay_quarantined_effect,
)
from maru.effects.worker import (
    EffectContext,
    EffectTimeoutError,
    HandlerRegistration,
    HandlerRegistry,
    PermanentEffectError,
    RunOutcome,
    TransientEffectError,
    run_claimed_effect,
)
from maru.events.models import EventEdition
from tests.factories import EventEditionFactory, OrganizationFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _record(
    *,
    aggregate_id: UUID | None = None,
    aggregate_version: int = 1,
    probe: str = "ready",
    edition: EventEdition | None = None,
) -> DomainEventRecord:
    edition = edition or EventEditionFactory()
    return DomainEventRecord(
        event_name="system.effect.probe_requested.v1",
        schema_version=1,
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        aggregate_type="system.effect_probe",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_version=aggregate_version,
        payload={"probe": probe},
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )


def _publish(
    record: DomainEventRecord | None = None,
    *,
    max_attempts: int = 8,
) -> tuple[DomainEvent, OutboxMessage]:
    with transaction.atomic():
        return publish_domain_event(
            record or _record(),
            max_attempts=max_attempts,
        )


def _registry(
    handler: Callable[[DomainEvent, EffectContext], None],
) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register(
        HandlerRegistration(
            event_name="system.effect.probe_requested.v1",
            destination="internal",
            handler=handler,
        )
    )
    return registry


def _claim(message: OutboxMessage):
    claim = claim_next_effect(
        organization_id=message.organization_id,
        workload_pool=message.workload_pool,
        lease_duration=timedelta(minutes=1),
    )
    assert claim is not None
    return claim


def test_publish_requires_atomic_state_transaction_and_rolls_back_together() -> None:
    record = _record()
    with pytest.raises(RuntimeError, match="state transaction"):
        publish_domain_event(record)

    class AbortTransactionError(RuntimeError):
        pass

    def publish_then_abort() -> None:
        with transaction.atomic():
            publish_domain_event(record)
            raise AbortTransactionError

    with pytest.raises(AbortTransactionError):
        publish_then_abort()

    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_commit_creates_fact_and_delivery_in_same_transaction() -> None:
    event, message = _publish()

    assert message.event_id == event.id
    assert message.organization_id == event.organization_id
    assert message.status == OutboxMessage.Status.PENDING
    assert event.outbox_messages.get().id == message.id


def test_domain_event_and_attempt_ledgers_are_database_immutable() -> None:
    event, message = _publish()
    claim = _claim(message)
    result = run_claimed_effect(
        claim,
        handlers=_registry(lambda _event, _context: None),
        execution_timeout=timedelta(seconds=30),
    )
    attempt = EffectAttempt.objects.get(outbox_message=message)
    assert result.outcome is RunOutcome.SUCCEEDED

    event.payload = {"probe": "rewritten"}
    with pytest.raises(ValidationError, match="append-only"):
        event.save()
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        DomainEvent.objects.filter(pk=event.pk).update(payload={"probe": "raw"})
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM effects_domainevent WHERE id = %s", [event.id])

    attempt.error_code = "rewritten"
    with pytest.raises(ValidationError, match="append-only"):
        attempt.save()
    with transaction.atomic(), pytest.raises(IntegrityError):
        EffectAttempt.objects.filter(pk=attempt.pk).delete()


def test_outbox_tenant_and_routing_envelope_are_database_guarded() -> None:
    event, message = _publish()
    other_organization = OrganizationFactory()
    with transaction.atomic(), pytest.raises(IntegrityError):
        OutboxMessage.objects.bulk_create(
            [
                OutboxMessage(
                    event=event,
                    organization_id=other_organization.id,
                    destination="other",
                    workload_pool="default",
                    available_at=timezone.now(),
                )
            ]
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        OutboxMessage.objects.filter(pk=message.pk).update(destination="rewritten")
    with pytest.raises(ValidationError, match="retention"):
        message.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        OutboxMessage.objects.filter(pk=message.pk).delete()


def test_claim_is_tenant_bounded_and_expired_lease_is_recoverable() -> None:
    _event, message = _publish()
    assert (
        claim_next_effect(
            organization_id=OrganizationFactory().id,
            workload_pool="default",
            lease_duration=timedelta(minutes=1),
        )
        is None
    )
    started = timezone.now()
    first = claim_next_effect(
        organization_id=message.organization_id,
        workload_pool="default",
        lease_duration=timedelta(minutes=1),
        now=started,
    )
    assert first is not None
    assert (
        claim_next_effect(
            organization_id=message.organization_id,
            workload_pool="default",
            lease_duration=timedelta(minutes=1),
            now=started + timedelta(seconds=30),
        )
        is None
    )

    recovered = claim_next_effect(
        organization_id=message.organization_id,
        workload_pool="default",
        lease_duration=timedelta(minutes=1),
        now=started + timedelta(minutes=2),
    )

    assert recovered is not None
    assert recovered.attempt_number == 2
    assert recovered.lease_token != first.lease_token
    lost = EffectAttempt.objects.get(
        outbox_message=message,
        attempt_number=1,
    )
    assert lost.error_code == "lease_expired"


def test_worker_records_success_and_will_not_execute_a_stale_claim_twice() -> None:
    _event, message = _publish()
    claim = _claim(message)
    calls: list[str] = []

    def handler(_event: DomainEvent, context: EffectContext) -> None:
        calls.append(context.idempotency_key)

    registry = _registry(handler)
    first = run_claimed_effect(
        claim,
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )
    duplicate = run_claimed_effect(
        claim,
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )

    assert first.outcome is RunOutcome.SUCCEEDED
    assert duplicate.outcome is RunOutcome.LEASE_LOST
    assert calls == [str(claim.event_id)]
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.SUCCEEDED


def test_ambiguous_external_success_is_harmless_on_retry() -> None:
    _event, message = _publish()
    external_writes: set[str] = set()
    invocations = 0

    def idempotent_handler(_event: DomainEvent, context: EffectContext) -> None:
        nonlocal invocations
        invocations += 1
        if context.idempotency_key not in external_writes:
            external_writes.add(context.idempotency_key)
            raise TransientEffectError(
                "ambiguous_provider_result", retry_after=timedelta(0)
            )

    registry = _registry(idempotent_handler)
    first = run_claimed_effect(
        _claim(message),
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )
    second = run_claimed_effect(
        _claim(message),
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )

    assert first.outcome is RunOutcome.RETRY_SCHEDULED
    assert second.outcome is RunOutcome.SUCCEEDED
    assert external_writes == {str(message.event_id)}
    assert invocations == 2


def test_transient_failure_quarantines_when_attempt_budget_is_exhausted() -> None:
    _event, message = _publish(max_attempts=1)

    result = run_claimed_effect(
        _claim(message),
        handlers=_registry(
            lambda _event, _context: (_ for _ in ()).throw(
                TransientEffectError("provider_unavailable")
            )
        ),
        execution_timeout=timedelta(seconds=30),
    )

    assert result.outcome is RunOutcome.QUARANTINED
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.attempts.get().outcome == EffectAttempt.Outcome.EXHAUSTED


@pytest.mark.parametrize(
    ("handler", "expected_outcome", "expected_code"),
    [
        (
            lambda _event, _context: (_ for _ in ()).throw(
                PermanentEffectError("payload_rejected")
            ),
            RunOutcome.QUARANTINED,
            "payload_rejected",
        ),
        (
            lambda _event, _context: (_ for _ in ()).throw(EffectTimeoutError()),
            RunOutcome.RETRY_SCHEDULED,
            "handler_timeout",
        ),
        (
            lambda _event, _context: (_ for _ in ()).throw(
                RuntimeError("provider included a secret")
            ),
            RunOutcome.RETRY_SCHEDULED,
            "unhandled_handler_error",
        ),
    ],
)
def test_worker_failure_taxonomy_records_only_safe_codes(
    handler: Callable[[DomainEvent, EffectContext], None],
    expected_outcome: RunOutcome,
    expected_code: str,
) -> None:
    _event, message = _publish()

    result = run_claimed_effect(
        _claim(message),
        handlers=_registry(handler),
        execution_timeout=timedelta(seconds=30),
    )

    assert result.outcome is expected_outcome
    assert result.error_code == expected_code
    attempt = EffectAttempt.objects.get(outbox_message=message)
    assert attempt.error_code == expected_code
    assert "secret" not in attempt.error_code


def test_poisoned_payload_or_missing_handler_is_quarantined() -> None:
    record = _record()
    event = DomainEvent.objects.create(
        event_name=record.event_name,
        schema_version=record.schema_version,
        occurred_at=timezone.now(),
        organization_id=record.organization_id,
        event_edition_id=record.event_edition_id,
        aggregate_type=record.aggregate_type,
        aggregate_id=record.aggregate_id,
        aggregate_version=record.aggregate_version,
        payload={"unexpected": "poison"},
        correlation_id=record.correlation_id,
        causation_id=None,
        actor_kind=record.actor_kind,
        actor_id=None,
    )
    message = OutboxMessage.objects.create(
        event=event,
        organization_id=event.organization_id,
        destination="internal",
        workload_pool="default",
        available_at=timezone.now(),
    )

    poisoned = run_claimed_effect(
        _claim(message),
        handlers=_registry(lambda _event, _context: None),
        execution_timeout=timedelta(seconds=30),
    )
    _event, missing_message = _publish()
    missing = run_claimed_effect(
        _claim(missing_message),
        handlers=HandlerRegistry(),
        execution_timeout=timedelta(seconds=30),
    )

    assert poisoned.outcome is RunOutcome.QUARANTINED
    assert poisoned.error_code == "invalid_event_payload"
    assert missing.outcome is RunOutcome.QUARANTINED
    assert missing.error_code == "handler_not_registered"


def test_transient_reordering_converges_without_losing_effect() -> None:
    aggregate_id = uuid4()
    edition = EventEditionFactory()
    _second_event, second_message = _publish(
        _record(
            aggregate_id=aggregate_id,
            aggregate_version=2,
            probe="second",
            edition=edition,
        )
    )
    _first_event, first_message = _publish(
        _record(
            aggregate_id=aggregate_id,
            aggregate_version=1,
            probe="first",
            edition=edition,
        )
    )
    completed_versions: set[int] = set()

    def ordered_handler(event: DomainEvent, _context: EffectContext) -> None:
        if event.aggregate_version == 2 and 1 not in completed_versions:
            raise TransientEffectError(
                "prerequisite_not_ready", retry_after=timedelta(0)
            )
        completed_versions.add(event.aggregate_version)

    registry = _registry(ordered_handler)
    first_run = run_claimed_effect(
        _claim(second_message),
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )
    second_run = run_claimed_effect(
        _claim(first_message),
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )
    third_run = run_claimed_effect(
        _claim(second_message),
        handlers=registry,
        execution_timeout=timedelta(seconds=30),
    )

    assert first_run.outcome is RunOutcome.RETRY_SCHEDULED
    assert second_run.outcome is RunOutcome.SUCCEEDED
    assert third_run.outcome is RunOutcome.SUCCEEDED
    assert completed_versions == {1, 2}


def test_cancellation_boundary_and_operator_replay_are_explicit() -> None:
    _event, pending = _publish()
    cancel_pending_effect(
        message_id=pending.id,
        reason_code="operation_cancelled",
    )
    pending.refresh_from_db()
    assert pending.status == OutboxMessage.Status.CANCELLED
    assert (
        claim_next_effect(
            organization_id=pending.organization_id,
            workload_pool=pending.workload_pool,
            lease_duration=timedelta(minutes=1),
        )
        is None
    )

    _event, processing = _publish()
    _claim(processing)
    with pytest.raises(CancellationBoundaryPassedError):
        cancel_pending_effect(
            message_id=processing.id,
            reason_code="too_late",
        )

    _event, quarantined = _publish(max_attempts=1)
    failure = run_claimed_effect(
        _claim(quarantined),
        handlers=_registry(
            lambda _event, _context: (_ for _ in ()).throw(
                PermanentEffectError("provider_rejected")
            )
        ),
        execution_timeout=timedelta(seconds=30),
    )
    assert failure.outcome is RunOutcome.QUARANTINED

    replayed = replay_quarantined_effect(
        message_id=quarantined.id,
        additional_attempts=1,
    )
    assert replayed.status == OutboxMessage.Status.PENDING
    assert replayed.replay_count == 1
    success = run_claimed_effect(
        _claim(replayed),
        handlers=_registry(lambda _event, _context: None),
        execution_timeout=timedelta(seconds=30),
    )
    assert success.outcome is RunOutcome.SUCCEEDED
