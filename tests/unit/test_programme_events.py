"""Unit coverage for minimized Programme events and dormant registration."""

from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ValidationError

import maru.effects.adoption as effect_adoption
from maru.effects.registry import validate_event_payload
from maru.programme.checks import programme_dormancy_problem_codes
from maru.programme.events import (
    PROGRAMME_EVENT_FIELDS,
    PROGRAMME_ITEM_CHANGED_EVENT,
    ProgrammeItemChanged,
    programme_item_changed_payload,
    validate_programme_item_changed_payload,
)


def test_programme_changed_payload_is_exact_and_content_free() -> None:
    """Retain closed codes without identifiers, reason, or private text."""
    payload = programme_item_changed_payload(
        action="revise_delivery",
        item_kind="ceremony",
        provenance="organizer_core",
        lifecycle="active",
    )

    assert set(payload) == PROGRAMME_EVENT_FIELDS
    assert payload == {
        "action": "revise_delivery",
        "layer": "delivery",
        "item_kind": "ceremony",
        "provenance": "organizer_core",
        "lifecycle": "active",
        "concern": "none",
    }
    validate_event_payload(
        event_name=PROGRAMME_ITEM_CHANGED_EVENT,
        schema_version=1,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("action", "concern", "layer"),
    [
        ("create_core_item", "none", "item"),
        ("revise_working", "none", "working"),
        ("revise_delivery", "none", "delivery"),
        ("append_discussion", "none", "discussion"),
        ("configure_readiness", "technical_needs", "readiness"),
        ("record_readiness", "required_files", "readiness"),
        ("approve_public_copy", "public_copy", "public_copy"),
    ],
)
def test_programme_changed_actions_derive_one_exact_layer(
    action: str,
    concern: str,
    layer: str,
) -> None:
    """Prevent event producers from choosing a misleading information layer."""
    payload = programme_item_changed_payload(
        action=action,
        item_kind="organizer_core",
        provenance="organizer_core",
        lifecycle="active",
        concern=concern,
    )

    assert payload["layer"] == layer
    validate_programme_item_changed_payload(payload)
    validate_event_payload(
        event_name=PROGRAMME_ITEM_CHANGED_EVENT,
        schema_version=1,
        payload=payload,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "action": "revise_working",
            "layer": "working",
            "item_kind": "ceremony",
            "provenance": "organizer_core",
            "lifecycle": "active",
            "concern": "none",
            "reason": "must never leave the aggregate",
        },
        {
            "action": "revise_working",
            "layer": "delivery",
            "item_kind": "ceremony",
            "provenance": "organizer_core",
            "lifecycle": "active",
            "concern": "none",
        },
        {
            "action": "record_readiness",
            "layer": "readiness",
            "item_kind": "ceremony",
            "provenance": "organizer_core",
            "lifecycle": "active",
            "concern": "none",
        },
        {
            "action": "approve_public_copy",
            "layer": "public_copy",
            "item_kind": "ceremony",
            "provenance": "organizer_core",
            "lifecycle": "active",
            "concern": "technical_needs",
        },
    ],
)
def test_programme_changed_payload_rejects_shape_or_semantic_drift(
    payload: dict[str, object],
) -> None:
    """Reject extra content, mismatched layers, and misleading concerns."""
    with pytest.raises(ValidationError) as raised:
        validate_programme_item_changed_payload(payload)

    assert raised.value.code == "invalid_domain_event_payload"
    with pytest.raises(ValidationError) as registry_raised:
        validate_event_payload(
            event_name=PROGRAMME_ITEM_CHANGED_EVENT,
            schema_version=1,
            payload=payload,
        )
    assert registry_raised.value.code == "invalid_domain_event_payload"


def test_programme_changed_value_is_immutable() -> None:
    """Freeze the value passed between command and durable event publisher."""
    event = ProgrammeItemChanged(
        action="create_core_item",
        layer="item",
        item_kind="break",
        provenance="organizer_core",
        lifecycle="active",
    )

    with pytest.raises(FrozenInstanceError):
        event.action = "revise_working"  # type: ignore[misc]


def test_programme_catalogs_are_registered_while_profiles_remain_dormant() -> None:
    """Require declarations without admitting Programme to a current profile."""
    assert programme_dormancy_problem_codes() == ()


def test_programme_dormancy_rejects_every_non_edition_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a non-internal route that would activate null-edition delivery."""
    monkeypatch.setattr(
        effect_adoption,
        "NON_EDITION_EFFECT_ROUTES",
        effect_adoption.NON_EDITION_EFFECT_ROUTES
        | {(PROGRAMME_ITEM_CHANGED_EVENT, "notifications")},
    )

    assert programme_dormancy_problem_codes() == ("dormancy.non-edition-effect-route",)
