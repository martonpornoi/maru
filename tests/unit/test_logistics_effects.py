from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.effects.handlers import ACKNOWLEDGED_INTERNAL_EVENTS
from maru.effects.registry import validate_event_payload


def test_logistics_event_schema_and_internal_handler_are_registered() -> None:
    payload = {
        "action": "move",
        "record_type": "logistics.event",
        "record_id": str(uuid4()),
    }

    validate_event_payload(
        event_name="logistics.record.changed.v1",
        schema_version=1,
        payload=payload,
    )
    assert "logistics.record.changed.v1" in ACKNOWLEDGED_INTERNAL_EVENTS


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "move",
            "record_type": "logistics.event",
            "record_id": "not-a-uuid",
        },
        {
            "action": "unregistered-action",
            "record_type": "logistics.event",
            "record_id": str(uuid4()),
        },
        {
            "action": "move",
            "record_type": "logistics.event",
            "record_id": str(uuid4()),
            "private_reason": "must not enter an outbox payload",
        },
    ],
)
def test_logistics_event_schema_rejects_unknown_or_unbounded_values(
    payload: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(
            event_name="logistics.record.changed.v1",
            schema_version=1,
            payload=payload,
        )
