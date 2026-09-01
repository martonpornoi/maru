"""Unit coverage for minimized dormant Programme application events."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications.programme_checks import (
    applications_programme_dormancy_problem_codes,
)
from maru.applications.programme_events import (
    APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
    PROGRAMME_CALL_EVENT_FIELDS,
    PROGRAMME_PROPOSAL_EVENT_FIELDS,
    ProgrammeCallChanged,
    ProgrammeProposalChanged,
    programme_call_changed_payload,
    programme_proposal_changed_payload,
    validate_programme_call_changed_payload,
    validate_programme_proposal_changed_payload,
)
from maru.effects.handlers import ACKNOWLEDGED_DORMANT_EVENTS
from maru.effects.registry import validate_event_payload


def test_programme_call_event_is_exact_content_free_and_registered() -> None:
    """Retain only one identifier, closed state, action, and version."""
    call_id = uuid4()
    payload = programme_call_changed_payload(
        action="call_activated",
        call_id=call_id,
        lifecycle="active",
        resulting_version=4,
    )

    assert set(payload) == PROGRAMME_CALL_EVENT_FIELDS
    assert payload == {
        "action": "call_activated",
        "call_id": str(call_id),
        "lifecycle": "active",
        "resulting_version": "4",
    }
    assert not {"reason", "digest", "content", "actor_id"} & set(payload)
    validate_event_payload(
        event_name=APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
        schema_version=1,
        payload=payload,
    )


def test_proposal_event_derives_layer_and_rejects_semantic_drift() -> None:
    """Prevent producers from choosing a misleading state or information layer."""
    proposal_id = uuid4()
    payload = programme_proposal_changed_payload(
        action="proposal_sealed",
        proposal_id=proposal_id,
        state="sealed",
        resulting_version=9,
    )

    assert set(payload) == PROGRAMME_PROPOSAL_EVENT_FIELDS
    assert payload["layer"] == "revision"
    validate_event_payload(
        event_name=APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
        schema_version=1,
        payload=payload,
    )
    invalid = {**payload, "state": "draft"}
    with pytest.raises(ValidationError) as raised:
        validate_programme_proposal_changed_payload(invalid)
    assert raised.value.code == "invalid_domain_event_payload"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "action": "call_created",
            "call_id": str(uuid4()).upper(),
            "lifecycle": "draft",
            "resulting_version": "1",
        },
        {
            "action": "call_created",
            "call_id": str(uuid4()),
            "lifecycle": "draft",
            "resulting_version": "0",
        },
        {
            "action": "call_created",
            "call_id": str(uuid4()),
            "lifecycle": "draft",
            "resulting_version": "1",
            "reason": "never emit this",
        },
    ],
)
def test_programme_call_event_rejects_open_or_noncanonical_payloads(
    payload: dict[str, object],
) -> None:
    """Reject extra content, upper-case identifiers, and invalid versions."""
    with pytest.raises(ValidationError) as raised:
        validate_programme_call_changed_payload(payload)
    assert raised.value.code == "invalid_domain_event_payload"


def test_typed_event_values_are_immutable_and_require_typed_identifiers() -> None:
    """Reject free-text identity before a command can enqueue an event."""
    value = ProgrammeProposalChanged(
        action="proposal_started",
        proposal_id=uuid4(),
        state="draft",
        resulting_version=1,
    )
    with pytest.raises(FrozenInstanceError):
        value.state = "submitted"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ProgrammeCallChanged(
            action="call_created",
            call_id="not-a-typed-id",  # type: ignore[arg-type]
            lifecycle="draft",
            resulting_version=1,
        )


def test_events_are_acknowledged_but_current_profiles_remain_dormant() -> None:
    """Require a declared no-handler state rather than accidental activation."""
    assert {
        APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
        APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
    } <= ACKNOWLEDGED_DORMANT_EVENTS
    assert applications_programme_dormancy_problem_codes() == ()
