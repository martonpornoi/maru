"""Prepared native pre-adoption delivery and retained-history replay coverage.

Uses the existing owner-login native fixture, not restricted-runtime acceptance.
"""

from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.effects.handlers import built_in_handler_registry
from maru.effects.models import DomainEvent, OutboxMessage
from maru.effects.services import (
    DomainEventRecord,
    claim_next_effect,
    enqueue_event_delivery,
    finish_effect_permanent_failure,
    publish_domain_event,
    replay_quarantined_effect,
)
from maru.effects.worker import RunOutcome, run_claimed_effect
from maru.events.guidance_activation import (
    propose_guidance_activation,
    respond_to_guidance_activation,
)
from maru.events.guidance_effects import guidance_adoption_effect_reference
from maru.events.models import EventEdition, GuidanceActivationRequest
from maru.organizations.models import OrganizationRepresentation
from tests.integration.guidance_test_support import guidance_runtime
from tests.integration.test_announcements_adoption import (
    activate_announcements_operators,
    setup_announcements,
)

__all__ = ["guidance_runtime"]

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_pre_adoption_fact_delivery_replay_survives_original_request_expiry(
    guidance_runtime,
    monkeypatch,
):
    platform, _key, setup = setup_announcements()
    representation = OrganizationRepresentation.objects.get(id=setup.representation_id)
    appointments = activate_announcements_operators(platform, representation)
    first, second = (appointment.account for appointment in appointments)
    edition = EventEdition.objects.get(id=setup.edition_id)
    proposal = propose_guidance_activation(
        actor=platform,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        expected_edition_version=edition.aggregate_version,
        operator_ids=(first.id, second.id),
        reason="Synthetic transition route rehearsal.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    # An actual declined answer is also retained delivery work, never an adoption grant.
    respond_to_guidance_activation(
        actor=first,
        request_id=proposal.request_id,
        expected_version=1,
        accept=False,
        correlation_id=uuid4(),
    )
    request = GuidanceActivationRequest.objects.get(id=proposal.request_id)
    event = DomainEvent.objects.get(
        aggregate_type="events.guidance_activation_request", aggregate_id=request.id
    )
    message = OutboxMessage.objects.get(event=event, destination="internal")
    assert edition.adoption_profile_code == "announcements_only"
    assert (
        guidance_adoption_effect_reference(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            aggregate_type=event.aggregate_type,
            aggregate_id=request.id,
        ).actor_id
        == platform.id
    )

    values = {
        field: getattr(event, field) for field in DomainEventRecord.__dataclass_fields__
    }
    forged = DomainEventRecord(**{**values, "aggregate_id": uuid4()})
    with transaction.atomic(), pytest.raises(ValidationError):
        publish_domain_event(forged)
    assert not DomainEvent.objects.filter(aggregate_id=forged.aggregate_id).exists()
    with transaction.atomic(), pytest.raises(ValidationError):
        enqueue_event_delivery(
            event=event, destination="notifications", workload_pool="default"
        )

    # Advance the worker's supplied time past the immutable proposal's expiry.
    # No retained row or actor is rewritten to make that historical fact current.
    after_expiry = max(timezone.now(), request.expires_at) + timedelta(minutes=1)
    monkeypatch.setattr(timezone, "now", lambda: after_expiry)
    handlers = built_in_handler_registry()
    seen_target = False
    for _ in range(100):
        claim = claim_next_effect(
            organization_id=edition.organization_id,
            workload_pool="default",
            lease_duration=timedelta(minutes=1),
            now=after_expiry,
        )
        if claim is None:
            break
        if claim.message_id == message.id:
            finish_effect_permanent_failure(
                claim, error_code="synthetic_delivery_failure", finished_at=after_expiry
            )
            seen_target = True
        else:
            result = run_claimed_effect(
                claim,
                handlers=handlers,
                execution_timeout=timedelta(seconds=10),
                clock=lambda: after_expiry,
            )
            assert result.outcome == RunOutcome.SUCCEEDED
    assert seen_target
    original = {
        field: getattr(event, field) for field in asdict(DomainEventRecord(**values))
    }
    replay_quarantined_effect(
        message_id=message.id,
        additional_attempts=1,
        actor_id=platform.id,
        reason="Retry the original retained transition fact.",
        correlation_id=uuid4(),
        now=after_expiry,
    )
    claim = claim_next_effect(
        organization_id=edition.organization_id,
        workload_pool="default",
        lease_duration=timedelta(minutes=1),
        now=after_expiry,
    )
    assert claim is not None
    assert claim.message_id == message.id
    assert (
        run_claimed_effect(
            claim,
            handlers=handlers,
            execution_timeout=timedelta(seconds=10),
            clock=lambda: after_expiry,
        ).outcome
        == RunOutcome.SUCCEEDED
    )
    event.refresh_from_db()
    assert {field: getattr(event, field) for field in original} == original
    assert (
        EventEdition.objects.get(id=edition.id).adoption_profile_code
        == "announcements_only"
    )
