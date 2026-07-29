from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EditionLifecycleTransition, EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _grant_transition(actor: Account, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )


def test_authorized_transition_commits_state_audit_fact_and_outbox_together() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant_transition(actor, edition)
    correlation_id = uuid4()

    transitioned = transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=actor,
        reason="Begin operational preparation.",
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel="api",
    )

    assert transitioned.lifecycle == EventEdition.Lifecycle.PREPARING
    assert transitioned.lifecycle_version == 1
    transition = EditionLifecycleTransition.objects.get(edition=edition)
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    message = OutboxMessage.objects.get(event=event)
    assert transition.actor_id == actor.id
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.changed_fields == ["lifecycle", "lifecycle_version"]
    assert event.aggregate_version == 1
    assert event.causation_id == audit.id
    assert event.payload == {"from_state": "draft", "to_state": "preparing"}
    assert message.status == OutboxMessage.Status.PENDING
    assert message.workload_pool == "core"
    assert "Begin operational preparation." not in str(audit.safe_metadata)
    assert "Begin operational preparation." not in str(event.payload)


def test_denied_transition_records_denial_without_revealing_or_changing_state() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=actor,
            reason="Attempt without authority.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "permission_absent"
    edition.refresh_from_db()
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.outcome == AuditEvent.Outcome.DENY
    assert audit.reason_code == "permission_absent"
    assert not EditionLifecycleTransition.objects.filter(edition=edition).exists()
    assert not DomainEvent.objects.filter(aggregate_id=edition.id).exists()
    assert not OutboxMessage.objects.filter(
        organization_id=edition.organization_id
    ).exists()


def test_invalid_transition_records_safe_error_and_emits_no_domain_fact() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant_transition(actor, edition)
    correlation_id = uuid4()

    with pytest.raises(ValidationError, match="Cannot transition"):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.LIVE,
            actor=actor,
            reason="Skip required states.",
            correlation_id=correlation_id,
        )

    edition.refresh_from_db()
    assert edition.lifecycle_version == 0
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "invalid_transition"
    assert not DomainEvent.objects.filter(aggregate_id=edition.id).exists()


def test_effect_publish_failure_rolls_back_canonical_change_and_records_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant_transition(actor, edition)
    correlation_id = uuid4()

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr("maru.events.services.publish_domain_event", fail_publish)

    with pytest.raises(RuntimeError, match="synthetic outbox"):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=actor,
            reason="Begin preparation.",
            correlation_id=correlation_id,
        )

    edition.refresh_from_db()
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    assert edition.lifecycle_version == 0
    assert not EditionLifecycleTransition.objects.filter(edition=edition).exists()
    assert not DomainEvent.objects.filter(aggregate_id=edition.id).exists()
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "transition_failed"
