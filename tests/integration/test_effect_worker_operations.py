import json
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.effects.commands import replay_effect
from maru.effects.handlers import (
    ACKNOWLEDGED_INTERNAL_EVENTS,
    built_in_handler_registry,
)
from maru.effects.models import DomainEvent, OutboxMessage
from maru.effects.operations import outbox_health_snapshot, render_prometheus
from maru.effects.registry import DEFINITIONS_BY_NAME
from maru.effects.services import (
    DomainEventRecord,
    claim_next_effect,
    finish_effect_permanent_failure,
    finish_effect_transient_failure,
    publish_domain_event,
)
from maru.effects.supervisor import ChildOutcome, ChildResult, eligible_tenant_ids
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _pending_message(
    edition: object,
    *,
    pool: str = "default",
) -> OutboxMessage:
    with transaction.atomic():
        _event, message = publish_domain_event(
            DomainEventRecord(
                event_name="system.effect.probe_requested.v1",
                schema_version=1,
                organization_id=edition.organization_id,
                event_edition_id=edition.id,
                aggregate_type="system.effect_probe",
                aggregate_id=uuid4(),
                aggregate_version=1,
                payload={"probe": "worker"},
                correlation_id=uuid4(),
                causation_id=None,
                actor_kind="system",
                actor_id=None,
            ),
            workload_pool=pool,
        )
    return message


def _quarantined_message(edition: object) -> OutboxMessage:
    message = _pending_message(edition)
    claim = claim_next_effect(
        organization_id=message.organization_id,
        workload_pool=message.workload_pool,
        lease_duration=timedelta(minutes=1),
    )
    assert claim is not None
    finish_effect_permanent_failure(claim, error_code="synthetic_failure")
    message.refresh_from_db()
    return message


def test_builtin_handlers_explicitly_cover_the_closed_event_registry() -> None:
    assert frozenset(DEFINITIONS_BY_NAME) == ACKNOWLEDGED_INTERNAL_EVENTS
    handlers = built_in_handler_registry()
    assert all(
        handlers.resolve(event_name=event_name, destination="internal") is not None
        for event_name in ACKNOWLEDGED_INTERNAL_EVENTS
    )


def test_run_once_command_drains_one_message_with_durable_attempt() -> None:
    edition = EventEditionFactory()
    message = _pending_message(edition)
    output = StringIO()

    call_command(
        "effects_run_once",
        "--organization",
        str(edition.organization_id),
        stdout=output,
    )

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.SUCCEEDED
    assert message.attempts.get().outcome == "succeeded"
    assert '"result": "succeeded"' in output.getvalue()

    idle_output = StringIO()
    call_command(
        "effects_run_once",
        "--organization",
        str(edition.organization_id),
        stdout=idle_output,
    )
    assert '"result": "idle"' in idle_output.getvalue()


def test_eligible_tenants_are_pool_and_readiness_bounded() -> None:
    first = EventEditionFactory()
    second = EventEditionFactory()
    third = EventEditionFactory()
    first_message = _pending_message(first)
    _pending_message(second)
    _pending_message(third, pool="security")
    first_claim = claim_next_effect(
        organization_id=first_message.organization_id,
        workload_pool=first_message.workload_pool,
        lease_duration=timedelta(minutes=1),
    )
    assert first_claim is not None
    finish_effect_transient_failure(
        first_claim,
        error_code="retry_later",
        retry_after=timedelta(hours=1),
    )

    candidates = eligible_tenant_ids(workload_pool="default")

    assert candidates == (second.organization_id,)


def test_supervisor_command_rotates_tenants_and_validates_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = EventEditionFactory()
    second = EventEditionFactory()
    _pending_message(first)
    _pending_message(second)
    served: list[object] = []

    def record_child(**kwargs: object) -> ChildResult:
        served.append(kwargs["organization_id"])
        return ChildResult(ChildOutcome.COMPLETED, 0)

    monkeypatch.setattr(
        "maru.effects.management.commands.effects_worker.run_effect_child",
        record_child,
    )
    call_command(
        "effects_worker",
        "--max-cycles",
        "4",
        "--idle-seconds",
        "0",
    )

    ordered = sorted((first.organization_id, second.organization_id), key=str)
    assert served == [ordered[0], ordered[1], ordered[0], ordered[1]]

    with pytest.raises(CommandError, match="Hard timeout"):
        call_command(
            "effects_worker",
            "--max-cycles",
            "0",
            "--execution-timeout-seconds",
            "30",
            "--hard-timeout-seconds",
            "30",
        )
    with pytest.raises(CommandError, match="Idle interval"):
        call_command(
            "effects_worker",
            "--max-cycles",
            "0",
            "--idle-seconds",
            "-1",
        )
    with pytest.raises(CommandError, match="Lease"):
        call_command(
            "effects_worker",
            "--max-cycles",
            "0",
            "--lease-seconds",
            "0",
        )
    with pytest.raises(CommandError, match="Execution timeout"):
        call_command(
            "effects_worker",
            "--max-cycles",
            "0",
            "--lease-seconds",
            "10",
            "--execution-timeout-seconds",
            "11",
        )
    with pytest.raises(CommandError, match="Maximum cycles"):
        call_command(
            "effects_worker",
            "--max-cycles",
            "-1",
        )


def test_metrics_are_tenant_bounded_and_contain_no_event_payload() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()
    message = _pending_message(edition)
    _pending_message(other)
    call_command(
        "effects_run_once",
        "--organization",
        str(edition.organization_id),
        stdout=StringIO(),
    )

    snapshot = outbox_health_snapshot(
        organization_id=edition.organization_id,
        workload_pool="default",
    )
    metrics = render_prometheus(snapshot)

    assert dict(snapshot.counts)["succeeded"] == 1
    assert dict(snapshot.counts)["pending"] == 0
    assert dict(snapshot.attempt_counts)["succeeded"] == 1
    assert snapshot.replay_count == 0
    assert str(edition.organization_id) in metrics
    assert str(other.organization_id) not in metrics
    assert "worker" not in metrics
    assert str(message.event_id) not in metrics

    output = StringIO()
    call_command(
        "effects_metrics",
        "--organization",
        str(edition.organization_id),
        stdout=output,
    )
    assert output.getvalue() == metrics


def test_authorized_replay_records_audit_and_restores_pending_work() -> None:
    edition = EventEditionFactory()
    message = _quarantined_message(edition)
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=actor,
        capability_code="effects.replay",
    )
    correlation_id = uuid4()

    replayed = replay_effect(
        actor=actor,
        organization_id=edition.organization_id,
        message_id=message.id,
        additional_attempts=2,
        reason="Provider recovery has been verified.",
        correlation_id=correlation_id,
    )

    assert replayed.status == OutboxMessage.Status.PENDING
    assert replayed.replay_count == 1
    assert replayed.max_attempts == message.max_attempts + 2
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.operation == "effects.outbox.replay"
    assert audit.target_id == message.id


def test_effects_replay_command_uses_authorized_audited_path() -> None:
    edition = EventEditionFactory()
    message = _quarantined_message(edition)
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=actor,
        capability_code="effects.replay",
    )
    output = StringIO()

    call_command(
        "effects_replay",
        "--organization",
        str(edition.organization_id),
        "--message",
        str(message.id),
        "--actor",
        actor.email,
        "--reason",
        "The poison input has been corrected.",
        "--additional-attempts",
        "2",
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    message.refresh_from_db()
    assert payload["message_id"] == str(message.id)
    assert payload["status"] == OutboxMessage.Status.PENDING
    assert message.replay_count == 1
    audit = AuditEvent.objects.get(correlation_id=payload["correlation_id"])
    assert audit.source_channel == "management-command"
    assert audit.outcome == AuditEvent.Outcome.ALLOW


def test_effects_replay_command_fails_closed_for_unknown_actor() -> None:
    with pytest.raises(CommandError, match="actor is unavailable"):
        call_command(
            "effects_replay",
            "--organization",
            str(uuid4()),
            "--message",
            str(uuid4()),
            "--actor",
            "unknown@example.invalid",
            "--reason",
            "No actor should reveal a target.",
        )


def test_replay_denies_missing_authority_and_hides_other_tenant() -> None:
    own_edition = EventEditionFactory()
    other_edition = EventEditionFactory()
    message = _quarantined_message(other_edition)
    actor = AccountFactory()
    denied_correlation = uuid4()
    with pytest.raises(AuthorizationDenied) as denied:
        replay_effect(
            actor=actor,
            organization_id=own_edition.organization_id,
            message_id=message.id,
            additional_attempts=1,
            reason="Unauthorized replay.",
            correlation_id=denied_correlation,
        )
    assert denied.value.reason_code == "permission_absent"

    CapabilityGrantFactory(
        organization=own_edition.organization,
        principal=actor,
        capability_code="effects.replay",
    )
    hidden_correlation = uuid4()
    with pytest.raises(AuthorizationDenied) as hidden:
        replay_effect(
            actor=actor,
            organization_id=own_edition.organization_id,
            message_id=message.id,
            additional_attempts=1,
            reason="Cross-tenant replay attempt.",
            correlation_id=hidden_correlation,
        )
    assert hidden.value.reason_code == "effect_unavailable"
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.QUARANTINED
    assert (
        AuditEvent.objects.get(correlation_id=hidden_correlation).outcome
        == AuditEvent.Outcome.DENY
    )


def test_replay_requires_reason_and_quarantined_state() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=actor,
        capability_code="effects.replay",
    )
    pending = _pending_message(edition)
    reason_correlation = uuid4()
    with pytest.raises(ValidationError):
        replay_effect(
            actor=actor,
            organization_id=edition.organization_id,
            message_id=pending.id,
            additional_attempts=1,
            reason=" ",
            correlation_id=reason_correlation,
        )
    assert (
        AuditEvent.objects.get(correlation_id=reason_correlation).reason_code
        == "reason_required"
    )

    invalid_correlation = uuid4()
    with pytest.raises(ValidationError):
        replay_effect(
            actor=actor,
            organization_id=edition.organization_id,
            message_id=pending.id,
            additional_attempts=1,
            reason="The effect is not quarantined.",
            correlation_id=invalid_correlation,
        )
    assert (
        AuditEvent.objects.get(correlation_id=invalid_correlation).reason_code
        == "effect_not_quarantined"
    )
    assert not DomainEvent.objects.filter(correlation_id=invalid_correlation).exists()
