import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from maru.effects.models import OutboxMessage
from maru.effects.services import (
    DomainEventRecord,
    claim_next_effect,
    finish_effect_permanent_failure,
    publish_domain_event,
)
from tests.factories import EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _pending_message(edition: object) -> OutboxMessage:
    with transaction.atomic():
        _event, message = publish_domain_event(
            DomainEventRecord(
                event_name="system.effect.probe_requested.v1",
                schema_version=1,
                organization_id=edition.organization_id,
                event_edition_id=edition.id,
                aggregate_type="system.effect_probe",
                aggregate_id=edition.id,
                aggregate_version=1,
                payload={"probe": "status"},
                correlation_id=edition.id,
                causation_id=None,
                actor_kind="system",
                actor_id=None,
            )
        )
    return message


def test_effects_status_is_machine_readable_and_tenant_bounded() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()
    _pending_message(edition)
    _pending_message(other)
    output = StringIO()

    call_command(
        "effects_status",
        "--organization",
        str(edition.organization_id),
        stdout=output,
    )

    result = json.loads(output.getvalue())
    assert result["organization_id"] == str(edition.organization_id)
    assert result["counts"] == {"pending": 1}
    assert result["oldest_ready_age_seconds"] >= 0
    assert result["quarantine_error_codes"] == {}
    assert result["quarantine_error_codes_truncated"] is False
    assert str(other.organization_id) not in output.getvalue()


def test_effects_status_can_fail_an_alert_check_on_quarantine() -> None:
    edition = EventEditionFactory()
    message = _pending_message(edition)
    claim = claim_next_effect(
        organization_id=message.organization_id,
        workload_pool=message.workload_pool,
        lease_duration=timedelta(minutes=1),
    )
    assert claim is not None
    finish_effect_permanent_failure(claim, error_code="synthetic_failure")

    output = StringIO()
    with pytest.raises(CommandError, match="quarantined"):
        call_command(
            "effects_status",
            "--organization",
            str(edition.organization_id),
            "--fail-on-quarantine",
            stdout=output,
        )

    result = json.loads(output.getvalue())
    assert result["quarantine_error_codes"] == {"synthetic_failure": 1}
    assert result["quarantine_error_codes_truncated"] is False


def test_effects_status_quarantine_codes_remain_tenant_bounded() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()
    message = _pending_message(edition)
    foreign_message = _pending_message(other)
    for pending, error_code in (
        (message, "synthetic_failure"),
        (foreign_message, "foreign_tenant_failure"),
    ):
        claim = claim_next_effect(
            organization_id=pending.organization_id,
            workload_pool=pending.workload_pool,
            lease_duration=timedelta(minutes=1),
        )
        assert claim is not None
        finish_effect_permanent_failure(claim, error_code=error_code)
    output = StringIO()

    call_command(
        "effects_status",
        "--organization",
        str(edition.organization_id),
        stdout=output,
    )

    result = json.loads(output.getvalue())
    assert result["quarantine_error_codes"] == {"synthetic_failure": 1}
    assert "foreign_tenant_failure" not in output.getvalue()
    assert str(other.organization_id) not in output.getvalue()
