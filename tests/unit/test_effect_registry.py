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


def test_profile_extension_value_event_is_minimized_and_strict() -> None:
    payload = {
        "field_id": "17bc39a2-9cf4-4876-8fc8-65469223843e",
        "field_version": "2",
        "registration_id": "5cfba0c4-7b50-4c29-a6ae-3f4c5def3792",
        "sequence": "3",
        "writer_kind": "staff",
    }
    validate_event_payload(
        event_name="registration.profile_extension.value_appended.v1",
        schema_version=1,
        payload=payload,
    )

    invalid_payloads = (
        {**payload, "value": "must-not-leak"},
        {**payload, "field_id": "not-a-uuid"},
        {**payload, "field_version": "0"},
        {**payload, "sequence": "1.0"},
        {**payload, "writer_kind": "platform_admin"},
    )
    for invalid_payload in invalid_payloads:
        with pytest.raises(ValidationError):
            validate_event_payload(
                event_name="registration.profile_extension.value_appended.v1",
                schema_version=1,
                payload=invalid_payload,
            )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "department_created",
            "aggregate_version": "1",
            "changed_fields": "departments",
        },
        {
            "action": "department_updated",
            "aggregate_version": "12",
            "changed_fields": "description,display_order,name,parent_department",
        },
        {
            "action": "template_applied",
            "aggregate_version": "1",
            "changed_fields": "departments",
            "template_code": "awoostria-reference",
            "template_version": "1",
        },
    ],
)
def test_workforce_structure_event_has_minimized_registered_payload(
    payload: dict[str, object],
) -> None:
    validate_event_payload(
        event_name="workforce.structure.changed.v1",
        schema_version=1,
        payload=payload,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "template_applied",
            "aggregate_version": "1",
            "changed_fields": "departments",
        },
        {
            "action": "department_created",
            "aggregate_version": "0",
            "changed_fields": "departments",
        },
        {
            "action": "department_created",
            "aggregate_version": "1",
            "changed_fields": "name,private_reason",
        },
        {
            "action": "department_updated",
            "aggregate_version": "1",
            "changed_fields": "name,name",
        },
        {
            "action": "department_deleted",
            "aggregate_version": "2",
            "changed_fields": "departments",
            "target_department_id": "not-public-evidence",
        },
        {
            "action": "department_retired",
            "aggregate_version": "2",
            "changed_fields": "name",
        },
        {
            "action": "department_updated",
            "aggregate_version": "2",
            "changed_fields": "departments",
        },
    ],
)
def test_workforce_structure_event_rejects_unregistered_or_private_evidence(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(
            event_name="workforce.structure.changed.v1",
            schema_version=1,
            payload=payload,
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
