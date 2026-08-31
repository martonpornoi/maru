"""Deployment-check coverage for governed effect routes."""

from dataclasses import replace

import pytest
from django.core.checks import Error, Tags, run_checks

from maru.effects import adoption as effect_adoption
from maru.effects.adoption import validated_effect_route_catalog
from maru.effects.checks import check_governed_effect_routes
from maru.events import adoption as event_adoption
from maru.events.adoption import EffectRoute


def test_current_adoption_profile_effect_routes_are_registered() -> None:
    assert check_governed_effect_routes() == []


def test_effect_route_catalog_rejects_duplicate_declarations() -> None:
    duplicate = ("system.effect.probe_requested.v1", "internal")

    with pytest.raises(RuntimeError, match="unique"):
        validated_effect_route_catalog((duplicate, duplicate))


def test_unregistered_profile_destination_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_key, profile = next(iter(event_adoption.ADOPTION_PROFILES.items()))
    unresolved_route = EffectRoute(
        event_name="system.effect.probe_requested.v1",
        destination="unregistered",
    )
    profiles = dict(event_adoption.ADOPTION_PROFILES)
    profiles[profile_key] = replace(
        profile,
        effect_routes=profile.effect_routes | {unresolved_route},
    )
    monkeypatch.setattr(event_adoption, "ADOPTION_PROFILES", profiles)

    messages = check_governed_effect_routes()

    assert len(messages) == 1
    assert isinstance(messages[0], Error)
    assert messages[0].id == "effects.E001"
    assert "unregistered" not in repr(messages[0])


def test_effect_route_check_is_registered_as_a_compatibility_check() -> None:
    messages = [
        message
        for message in run_checks(tags=[Tags.compatibility])
        if message.id == "effects.E001"
    ]

    assert messages == []


def test_unregistered_non_edition_route_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        effect_adoption,
        "NON_EDITION_EFFECT_ROUTES",
        effect_adoption.NON_EDITION_EFFECT_ROUTES
        | {("system.effect.probe_requested.v1", "unregistered")},
    )

    messages = check_governed_effect_routes()

    assert len(messages) == 1
    assert messages[0].id == "effects.E001"
