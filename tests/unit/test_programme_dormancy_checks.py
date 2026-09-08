"""Exercise deployment guards against incomplete or accidentally active profiles."""

from dataclasses import replace
from enum import StrEnum

import pytest

from maru.applications import adoption as application_adoption
from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
    APPLICATION_PROGRAMME_SELF_ADAPTER,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_PROGRAMME_CAPABILITY_CODES,
)
from maru.applications.programme_checks import (
    applications_programme_dormancy_problem_codes,
    check_applications_programme_dormancy,
)
from maru.applications.programme_events import APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT
from maru.authorization import catalog
from maru.effects import adoption as effect_adoption
from maru.effects import handlers, registry
from maru.events import adoption, adoption_persistence
from maru.programme.adoption import PROGRAMME_ADOPTION_ADAPTERS
from maru.programme.authorization import PROGRAMME_CAPABILITY_CODES
from maru.programme.checks import (
    check_programme_dormancy,
    programme_dormancy_problem_codes,
)
from maru.programme.events import PROGRAMME_ITEM_CHANGED_EVENT


@pytest.mark.parametrize(
    ("event", "checker", "system_check", "error_id"),
    [
        (
            PROGRAMME_ITEM_CHANGED_EVENT,
            programme_dormancy_problem_codes,
            check_programme_dormancy,
            "programme.E001",
        ),
        (
            APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
            applications_programme_dormancy_problem_codes,
            check_applications_programme_dormancy,
            "applications.E002",
        ),
    ],
)
@pytest.mark.parametrize(
    "defect", ["missing-event", "event-version", "missing-capability"]
)
def test_dormancy_checks_reject_incomplete_catalog_declarations(
    monkeypatch: pytest.MonkeyPatch,
    event,
    checker,
    system_check,
    error_id: str,
    defect: str,
) -> None:
    """Run real compatibility checks against one intentionally damaged registry."""
    if defect == "missing-event":
        monkeypatch.delitem(registry.DEFINITIONS_BY_NAME, event)
        expected = "catalog.event-missing"
    elif defect == "event-version":
        monkeypatch.setitem(
            registry.DEFINITIONS_BY_NAME,
            event,
            replace(registry.event_definition(event), schema_version=999),
        )
        expected = "catalog.event-version-mismatch"
    else:
        monkeypatch.setattr(catalog, "CAPABILITIES", {})
        expected = "catalog.capability-missing"
    assert checker() == (expected,)
    messages = system_check()
    assert len(messages) == 1
    assert messages[0].id == error_id
    assert expected in messages[0].hint


@pytest.mark.parametrize(
    ("attribute", "value", "problem"),
    [
        ("modules", frozenset({"programme"}), "dormancy.module-adopted"),
        ("capability_codes", PROGRAMME_CAPABILITY_CODES, "dormancy.capability-adopted"),
        (
            "adapter_codes",
            frozenset(PROGRAMME_ADOPTION_ADAPTERS),
            "dormancy.adapter-adopted",
        ),
        (
            "effect_routes",
            (adoption.EffectRoute(PROGRAMME_ITEM_CHANGED_EVENT, "notifications"),),
            "dormancy.effect-route-adopted",
        ),
    ],
)
def test_programme_dormancy_rejects_each_independent_profile_activation(
    monkeypatch: pytest.MonkeyPatch, attribute: str, value: object, problem: str
) -> None:
    profile = next(iter(adoption.ADOPTION_PROFILES.values()))
    changed = replace(profile, **{attribute: value})
    monkeypatch.setattr(
        adoption, "ADOPTION_PROFILES", {(changed.code, changed.version): changed}
    )
    assert programme_dormancy_problem_codes() == (problem,)


def test_programme_dormancy_rejects_premature_enum_and_persistence_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrematureProfile(StrEnum):
        PROGRAMME = "programme_operations"

    monkeypatch.setattr(adoption, "AdoptionProfileCode", PrematureProfile)
    monkeypatch.setattr(
        adoption_persistence,
        "PERSISTED_ADOPTION_PROFILE_KEYS",
        {("programme_operations", 1)},
    )
    assert programme_dormancy_problem_codes() == (
        "dormancy.profile-enum-active",
        "dormancy.profile-persistence-active",
    )


@pytest.mark.parametrize(
    "defect", ["adapters", "target-adapter", "acknowledgement", "global-route"]
)
def test_programme_application_guards_reject_unregistered_or_active_delivery(
    monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    event = APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT
    if defect == "adapters":
        monkeypatch.setattr(application_adoption, "APPLICATIONS_ADOPTION_ADAPTERS", {})
        expected = "catalog.adapter-missing"
    elif defect == "target-adapter":
        monkeypatch.setattr(
            application_adoption,
            "TARGET_ADAPTER_CODES",
            {APPLICATION_PROGRAMME_ITEM_TARGET_KIND: "wrong-adapter"},
        )
        expected = "catalog.target-adapter-mismatch"
    elif defect == "acknowledgement":
        monkeypatch.setattr(
            handlers,
            "ACKNOWLEDGED_DORMANT_EVENTS",
            handlers.ACKNOWLEDGED_DORMANT_EVENTS - {event},
        )
        expected = "dormancy.event-not-acknowledged"
    else:
        monkeypatch.setattr(
            effect_adoption,
            "NON_EDITION_EFFECT_ROUTES",
            effect_adoption.NON_EDITION_EFFECT_ROUTES | {(event, "notifications")},
        )
        expected = "dormancy.non-edition-effect-route"
    assert applications_programme_dormancy_problem_codes() == (expected,)


@pytest.mark.parametrize(
    "attribute", ["capability_codes", "adapter_codes", "effect_routes"]
)
def test_programme_application_guards_reject_profile_activation(
    monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    values = {
        "capability_codes": APPLICATIONS_PROGRAMME_CAPABILITY_CODES,
        "adapter_codes": frozenset({APPLICATION_PROGRAMME_SELF_ADAPTER}),
        "effect_routes": (
            adoption.EffectRoute(
                APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT, "notifications"
            ),
        ),
    }
    profile = next(iter(adoption.ADOPTION_PROFILES.values()))
    changed = replace(profile, **{attribute: values[attribute]})
    monkeypatch.setattr(
        adoption, "ADOPTION_PROFILES", {(changed.code, changed.version): changed}
    )
    suffix = {
        "capability_codes": "capability",
        "adapter_codes": "adapter",
        "effect_routes": "effect-route",
    }[attribute]
    assert applications_programme_dormancy_problem_codes() == (
        f"dormancy.{suffix}-adopted",
    )
