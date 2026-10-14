"""All production Effects gates carry original retained transition identity."""

from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.effects import services, worker
from maru.effects.models import OutboxMessage
from maru.events import guidance_effects as owner
from maru.events import queries
from maru.events.queries import EditionAdoptionProfileReference
from tests.unit.test_guidance_transition_effects import (
    ACTOR,
    EDITION,
    EVENT,
    IDENTITY,
    OBJECT,
    ORG,
    OTHER,
    REFERENCE,
    TRACE,
)


@pytest.mark.parametrize("site", ["publish", "enqueue", "worker", "replay"])
@pytest.mark.parametrize("alter_actor", [False, True])
def test_full_original_identity_at_every_delivery_gate(  # noqa: PLR0915 - four real caller boundaries
    monkeypatch,
    site,
    alter_actor,
):
    monkeypatch.setattr(
        queries,
        "edition_adoption_profile_reference",
        lambda **_kw: EditionAdoptionProfileReference("announcements_only", 1),
    )
    resolver = Mock(return_value=REFERENCE)
    monkeypatch.setattr(owner, "guidance_adoption_effect_reference", resolver)
    identity = replace(IDENTITY, actor_id=OTHER) if alter_actor else IDENTITY
    record = services.DomainEventRecord(
        event_name=EVENT,
        organization_id=ORG,
        event_edition_id=EDITION,
        payload={"operation": "proposed"},
        **asdict(identity),
    )
    event = SimpleNamespace(id=OBJECT, pk=OBJECT, **asdict(record))
    events = Mock()
    events.create.return_value = event
    events.filter.return_value.only.return_value.first.return_value = event
    monkeypatch.setattr(services.DomainEvent, "objects", events)
    messages = Mock()
    message = SimpleNamespace(
        id=uuid4(),
        event_id=OBJECT,
        event=event,
        organization_id=ORG,
        destination="internal",
        status=OutboxMessage.Status.QUARANTINED,
        max_attempts=8,
        replay_count=0,
        save=Mock(),
    )
    messages.create.return_value = message
    locked = messages.select_for_update.return_value.select_related.return_value
    locked.get.return_value = message
    monkeypatch.setattr(services.OutboxMessage, "objects", messages)
    receipts = Mock()
    monkeypatch.setattr(services.EffectReplayReceipt, "objects", receipts)
    monkeypatch.setattr(
        services.transaction,
        "get_connection",
        lambda: SimpleNamespace(in_atomic_block=True),
    )

    def call():
        if site == "publish":
            return services.publish_domain_event(record)
        if site == "enqueue":
            # The submitted instance is not the source of scope or actor data.
            return services.enqueue_event_delivery(
                event=SimpleNamespace(pk=OBJECT, actor_id=OTHER),
                destination="internal",
                workload_pool="default",
            )
        if site == "replay":
            # Exercise the real body without the decorator's DB transaction.
            return services.replay_quarantined_effect.__wrapped__(
                message_id=message.id,
                additional_attempts=1,
                actor_id=OTHER,
                reason="Retry retained synthetic fact.",
                correlation_id=uuid4(),
            )
        now = timezone.now()
        claim = services.ClaimedEffect(
            message.id, OBJECT, uuid4(), 1, now, now + timedelta(minutes=1)
        )
        monkeypatch.setattr(worker, "_active_message", lambda *_a, **_kw: message)
        monkeypatch.setattr(
            worker,
            "_mark_permanent",
            lambda *_a, **kw: worker.RunResult(
                worker.RunOutcome.QUARANTINED, kw["error_code"]
            ),
        )
        monkeypatch.setattr(worker, "finish_effect_success", Mock())
        registry = Mock()
        result = worker.run_claimed_effect(
            claim,
            handlers=registry,
            execution_timeout=timedelta(seconds=10),
            clock=lambda: now,
        )
        assert registry.resolve.call_count == (0 if alter_actor else 1)
        return result

    if alter_actor and site != "worker":
        with pytest.raises(ValidationError) as error:
            call()
        assert error.value.code == "effect_profile_not_allowed"
        events.create.assert_not_called()
        messages.create.assert_not_called()
        receipts.create.assert_not_called()
        message.save.assert_not_called()
    else:
        result = call()
        if site == "worker":
            assert result.outcome == (
                worker.RunOutcome.QUARANTINED
                if alter_actor
                else worker.RunOutcome.SUCCEEDED
            )
        if site == "replay":
            assert result.status == OutboxMessage.Status.PENDING
            assert receipts.create.call_args.kwargs["actor_id"] == OTHER
            # The historical event actor/correlation are not replaced by replay's actor.
            assert event.actor_id == ACTOR
            assert event.correlation_id == TRACE
    resolver.assert_called_once_with(
        organization_id=ORG,
        edition_id=EDITION,
        aggregate_type=IDENTITY.aggregate_type,
        aggregate_id=OBJECT,
    )
    if site == "enqueue":
        assert set(asdict(IDENTITY)) <= set(
            events.filter.return_value.only.call_args.args
        )
