import pytest
from django.core.exceptions import ValidationError

from maru.effects.registry import (
    DEFINITIONS_BY_NAME,
    EVENT_DEFINITIONS,
    validate_event_payload,
)
from maru.effects.services import validate_effect_error_code


def test_domain_event_registry_is_closed_and_unique() -> None:
    assert len(DEFINITIONS_BY_NAME) == len(EVENT_DEFINITIONS)
    assert all(definition.description for definition in EVENT_DEFINITIONS)


def test_registered_payload_requires_exact_bounded_schema() -> None:
    validate_event_payload(
        event_name="events.edition.lifecycle_transitioned.v1",
        schema_version=1,
        payload={"from_state": "draft", "to_state": "preparing"},
    )

    for payload in (
        {"from_state": "draft"},
        {"from_state": "draft", "to_state": "live", "secret": "value"},
        {"from_state": "draft", "to_state": ""},
        {"from_state": "draft", "to_state": "x" * 241},
    ):
        with pytest.raises(ValidationError):
            validate_event_payload(
                event_name="events.edition.lifecycle_transitioned.v1",
                schema_version=1,
                payload=payload,
            )


@pytest.mark.parametrize(
    ("event_name", "payload"),
    [
        (
            "authorization.capability.direct_granted.v1",
            {"capability_code": "events.view_basic", "scope_level": "organization"},
        ),
        (
            "authorization.capability.revoked.v1",
            {"capability_code": "events.transition", "scope_level": "edition"},
        ),
        (
            "authorization.role_bundle.version_created.v1",
            {"role_code": "front-desk", "role_version": "2"},
        ),
        (
            "authorization.role.assigned.v1",
            {
                "role_code": "front-desk",
                "role_version": "2",
                "scope_level": "edition",
            },
        ),
        (
            "authorization.role.revoked.v1",
            {
                "role_code": "front-desk",
                "role_version": "2",
                "scope_level": "edition",
            },
        ),
    ],
)
def test_authority_events_have_registered_minimized_payloads(
    event_name: str,
    payload: dict[str, object],
) -> None:
    validate_event_payload(
        event_name=event_name,
        schema_version=1,
        payload=payload,
    )


def test_unknown_event_and_version_are_rejected() -> None:
    with pytest.raises(ValidationError, match="declared"):
        validate_event_payload(
            event_name="unknown.v1",
            schema_version=1,
            payload={},
        )
    with pytest.raises(ValidationError, match="version"):
        validate_event_payload(
            event_name="system.effect.probe_requested.v1",
            schema_version=2,
            payload={"probe": "ready"},
        )


@pytest.mark.parametrize(
    "value",
    ["provider_timeout", "webhook.rate-limited", "retry.2"],
)
def test_safe_effect_error_codes(value: str) -> None:
    validate_effect_error_code(value)


@pytest.mark.parametrize(
    "value",
    ["", "Provider timeout: secret", "../escape", "x" * 121],
)
def test_unsafe_effect_error_codes_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="safe effect error code"):
        validate_effect_error_code(value)
