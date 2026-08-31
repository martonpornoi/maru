from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.effects.models import (
    MAX_EFFECT_TOTAL_ATTEMPTS,
    DomainEvent,
    EffectAttempt,
    OutboxMessage,
)
from maru.effects.services import (
    CancellationBoundaryPassedError,
    DomainEventRecord,
    cancel_pending_effect,
    claim_next_effect,
    enqueue_event_delivery,
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
from maru.events.queries import EditionAdoptionProfileReference
from tests.factories import AccountFactory, EventEditionFactory, OrganizationFactory

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
    event_name: str = "system.effect.probe_requested.v1",
    payload: dict[str, object] | None = None,
) -> DomainEventRecord:
    edition = edition or EventEditionFactory()
    return DomainEventRecord(
        event_name=event_name,
        schema_version=1,
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        aggregate_type="system.effect_probe",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_version=aggregate_version,
        payload=payload if payload is not None else {"probe": probe},
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


def _force_pending(
    record: DomainEventRecord,
    *,
    destination: str = "internal",
) -> OutboxMessage:
    """Persist a delivery without the publishing service for defensive tests."""
    event = DomainEvent.objects.create(
        occurred_at=timezone.now(),
        **asdict(record),
    )
    return OutboxMessage.objects.create(
        event=event,
        organization_id=event.organization_id,
        destination=destination,
        workload_pool="default",
        available_at=timezone.now(),
    )


def test_profile_forbidden_publish_persists_no_event_or_delivery() -> None:
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
        currency_codes=["XXX"],
    )
    record = _record(
        edition=edition,
        event_name="registration.submitted.v1",
        payload={
            "from_state": "draft",
            "to_state": "submitted",
            "reference": "synthetic-registration",
        },
    )

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        publish_domain_event(record)

    assert denied.value.code == "effect_profile_not_allowed"
    assert not DomainEvent.objects.filter(correlation_id=record.correlation_id).exists()
    assert not OutboxMessage.objects.exists()


def test_initial_attempt_budget_is_service_and_database_bounded() -> None:
    record = _record()

    with pytest.raises(ValidationError) as publish_error, transaction.atomic():
        publish_domain_event(
            record,
            max_attempts=MAX_EFFECT_TOTAL_ATTEMPTS + 1,
        )
    assert publish_error.value.code == "invalid_max_attempts"
    assert not DomainEvent.objects.filter(correlation_id=record.correlation_id).exists()

    event, message = _publish()
    with pytest.raises(ValidationError) as enqueue_error, transaction.atomic():
        enqueue_event_delivery(
            event=event,
            destination="notifications",
            workload_pool="default",
            max_attempts=MAX_EFFECT_TOTAL_ATTEMPTS + 1,
        )
    assert enqueue_error.value.code == "invalid_max_attempts"
    assert event.outbox_messages.count() == 1

    now = timezone.now()
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO effects_outboxmessage (
                id,
                created_at,
                updated_at,
                event_id,
                organization_id,
                destination,
                workload_pool,
                status,
                available_at,
                attempt_count,
                max_attempts,
                last_error_code,
                replay_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                uuid4(),
                now,
                now,
                event.id,
                event.organization_id,
                "raw-safety-probe",
                "default",
                OutboxMessage.Status.PENDING,
                now,
                0,
                MAX_EFFECT_TOTAL_ATTEMPTS + 1,
                "",
                0,
            ],
        )
    message.refresh_from_db()
    assert message.max_attempts == 8


def test_profile_forbidden_secondary_enqueue_persists_no_delivery() -> None:
    event, original = _publish()

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        enqueue_event_delivery(
            event=event,
            destination="notifications",
            workload_pool="default",
        )

    assert denied.value.code == "effect_profile_not_allowed"
    assert list(event.outbox_messages.values_list("id", flat=True)) == [original.id]


def test_workforce_profile_preserves_identity_fact_but_denies_notification() -> None:
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
        currency_codes=["XXX"],
    )
    record = _record(
        edition=edition,
        event_name="identity.account_restriction.applied.v1",
        payload={"restriction_kind": "communication", "status": "active"},
    )

    with transaction.atomic():
        event, internal = publish_domain_event(record)

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        enqueue_event_delivery(
            event=event,
            destination="notifications",
            workload_pool="default",
        )

    assert denied.value.code == "effect_profile_not_allowed"
    assert internal.destination == "internal"
    assert event.outbox_messages.count() == 1


def test_secondary_enqueue_checks_the_persisted_event_envelope() -> None:
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
        currency_codes=["XXX"],
    )
    record = _record(
        edition=edition,
        event_name="registration.submitted.v1",
        payload={
            "from_state": "draft",
            "to_state": "submitted",
            "reference": "synthetic-registration",
        },
    )
    message = _force_pending(record)
    event = message.event
    event.event_name = "system.effect.probe_requested.v1"
    event.payload = {"probe": "in-memory-only"}

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        enqueue_event_delivery(
            event=event,
            destination="internal",
            workload_pool="default",
        )

    assert denied.value.code == "effect_profile_not_allowed"
    assert event.outbox_messages.count() == 1


def test_worker_quarantines_profile_incompatible_work_without_invocation() -> None:
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
        currency_codes=["XXX"],
    )
    record = _record(
        edition=edition,
        event_name="registration.submitted.v1",
        payload={
            "from_state": "draft",
            "to_state": "submitted",
            "reference": "synthetic-registration",
        },
    )
    message = _force_pending(record)
    calls: list[UUID] = []
    handlers = HandlerRegistry()
    handlers.register(
        HandlerRegistration(
            event_name=record.event_name,
            destination="internal",
            handler=lambda event, _context: calls.append(event.id),
        )
    )

    result = run_claimed_effect(
        _claim(message),
        handlers=handlers,
        execution_timeout=timedelta(seconds=30),
    )

    message.refresh_from_db()
    assert result.outcome is RunOutcome.QUARANTINED
    assert result.error_code == "effect_profile_not_allowed"
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.last_error_code == "effect_profile_not_allowed"
    assert message.attempts.get().error_code == "effect_profile_not_allowed"
    assert calls == []

    with pytest.raises(ValidationError) as replay_denied:
        replay_quarantined_effect(
            message_id=message.id,
            additional_attempts=1,
            actor_id=AccountFactory().id,
            reason="Retry after confirming the manifest incident persists.",
            correlation_id=uuid4(),
        )
    assert replay_denied.value.code == "effect_profile_not_allowed"

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.max_attempts == 8
    assert message.replay_count == 0
    assert message.attempts.count() == 1
    assert not message.replay_receipts.exists()
    assert calls == []


def test_worker_quarantines_work_when_the_exact_manifest_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain pending evidence without invoking a handler on version drift."""
    message = _force_pending(_record())
    calls: list[UUID] = []
    monkeypatch.setattr(
        "maru.events.queries.edition_adoption_profile_reference",
        lambda **_kwargs: EditionAdoptionProfileReference(
            code="full_convention",
            version=2,
        ),
    )

    result = run_claimed_effect(
        _claim(message),
        handlers=_registry(lambda event, _context: calls.append(event.id)),
        execution_timeout=timedelta(seconds=30),
    )

    message.refresh_from_db()
    assert result.outcome is RunOutcome.QUARANTINED
    assert result.error_code == "effect_profile_not_allowed"
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.last_error_code == "effect_profile_not_allowed"
    assert message.attempts.get().error_code == "effect_profile_not_allowed"
    assert calls == []

    with pytest.raises(ValidationError) as replay_denied:
        replay_quarantined_effect(
            message_id=message.id,
            additional_attempts=1,
            actor_id=AccountFactory().id,
            reason="An unresolvable manifest must remain quarantined.",
            correlation_id=uuid4(),
        )
    assert replay_denied.value.code == "effect_profile_not_allowed"
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.max_attempts == 8
    assert message.replay_count == 0
    assert not message.replay_receipts.exists()


def test_worker_tenant_binds_edition_profile_before_invocation() -> None:
    owning_organization = OrganizationFactory()
    foreign_edition = EventEditionFactory()
    record = DomainEventRecord(
        event_name="system.effect.probe_requested.v1",
        schema_version=1,
        organization_id=owning_organization.id,
        event_edition_id=foreign_edition.id,
        aggregate_type="system.effect_probe",
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"probe": "tenant-bound"},
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )
    message = _force_pending(record)
    calls: list[UUID] = []

    result = run_claimed_effect(
        _claim(message),
        handlers=_registry(lambda event, _context: calls.append(event.id)),
        execution_timeout=timedelta(seconds=30),
    )

    message.refresh_from_db()
    assert result.outcome is RunOutcome.QUARANTINED
    assert result.error_code == "effect_profile_not_allowed"
    assert message.last_error_code == "effect_profile_not_allowed"
    assert calls == []

    with pytest.raises(ValidationError) as replay_denied:
        replay_quarantined_effect(
            message_id=message.id,
            additional_attempts=1,
            actor_id=AccountFactory().id,
            reason="A foreign edition must remain quarantined.",
            correlation_id=uuid4(),
        )
    assert replay_denied.value.code == "effect_profile_not_allowed"
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert message.max_attempts == 8
    assert message.replay_count == 0
    assert not message.replay_receipts.exists()


def test_explicit_non_edition_effect_retains_delivery_behavior() -> None:
    organization = OrganizationFactory()
    record = DomainEventRecord(
        event_name="system.effect.probe_requested.v1",
        schema_version=1,
        organization_id=organization.id,
        event_edition_id=None,
        aggregate_type="system.effect_probe",
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"probe": "organization-scope"},
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )
    event, message = _publish(record)
    calls: list[UUID] = []

    result = run_claimed_effect(
        _claim(message),
        handlers=_registry(lambda delivered, _context: calls.append(delivered.id)),
        execution_timeout=timedelta(seconds=30),
    )

    assert result.outcome is RunOutcome.SUCCEEDED
    assert calls == [event.id]


@pytest.mark.parametrize("scope_level", ["edition", "department", "resource"])
def test_hybrid_authorization_effect_cannot_omit_edition_scope(
    scope_level: str,
) -> None:
    organization = OrganizationFactory()
    record = DomainEventRecord(
        event_name="authorization.capability.direct_granted.v1",
        schema_version=1,
        organization_id=organization.id,
        event_edition_id=None,
        aggregate_type="authorization.capability_grant",
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={
            "capability_code": "workforce.manage_structure",
            "scope_level": scope_level,
        },
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        publish_domain_event(record)

    assert denied.value.code == "effect_profile_not_allowed"
    assert not DomainEvent.objects.filter(correlation_id=record.correlation_id).exists()
    assert not OutboxMessage.objects.exists()


def test_hybrid_authorization_effect_retains_organization_scope() -> None:
    organization = OrganizationFactory()
    record = DomainEventRecord(
        event_name="authorization.capability.direct_granted.v1",
        schema_version=1,
        organization_id=organization.id,
        event_edition_id=None,
        aggregate_type="authorization.capability_grant",
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={
            "capability_code": "authorization.grant_direct",
            "scope_level": "organization",
        },
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )

    event, message = _publish(record)

    assert event.event_edition_id is None
    assert message.status == OutboxMessage.Status.PENDING


def test_edition_owned_effect_cannot_use_missing_edition_scope() -> None:
    organization = OrganizationFactory()
    record = DomainEventRecord(
        event_name="registration.submitted.v1",
        schema_version=1,
        organization_id=organization.id,
        event_edition_id=None,
        aggregate_type="registration.registration",
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={
            "from_state": "draft",
            "to_state": "submitted",
            "reference": "synthetic-registration",
        },
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="system",
        actor_id=None,
    )

    with pytest.raises(ValidationError) as denied, transaction.atomic():
        publish_domain_event(record)

    assert denied.value.code == "effect_profile_not_allowed"
    assert not DomainEvent.objects.filter(correlation_id=record.correlation_id).exists()
    assert not OutboxMessage.objects.exists()


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
        actor_id=AccountFactory().id,
        reason="Retry after synthetic delivery recovery.",
        correlation_id=uuid4(),
    )
    assert replayed.status == OutboxMessage.Status.PENDING
    assert replayed.replay_count == 1
    success = run_claimed_effect(
        _claim(replayed),
        handlers=_registry(lambda _event, _context: None),
        execution_timeout=timedelta(seconds=30),
    )
    assert success.outcome is RunOutcome.SUCCEEDED
