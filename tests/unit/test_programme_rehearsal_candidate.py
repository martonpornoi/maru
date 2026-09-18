"""Database-free preparation checks; never native or complete fixture acceptance."""

import ast
import importlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.db.backends.base.base import BaseDatabaseWrapper

from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.core.programme_navigation import PROGRAMME_SHELL_KINDS
from maru.effects.handlers import (
    ACKNOWLEDGED_DORMANT_EVENTS,
    acknowledge_internal_fact,
    built_in_handler_registry,
)
from maru.effects.registry import event_definition
from maru.events import adoption
from maru.events.adoption_persistence import PERSISTED_ADOPTION_PROFILE_KEYS
from maru.events.checks import (
    adoption_manifest_catalog_problem_codes,
    current_adoption_catalog_snapshot,
)
from maru.events.models import EventEdition
from tests.rehearsals import programme_candidate as candidate
from tests.rehearsals.programme_effects import candidate_internal_handler_registry

PROFILE = candidate.PROGRAMME_REHEARSAL_PROFILE
EXCLUDED = frozenset(
    {
        "accreditation",
        "catalog",
        "charities",
        "communications",
        "logistics",
        "participation",
        "registration",
    }
)


def test_candidate_import_is_pure_and_cannot_activate_a_runtime_profile(monkeypatch):
    connection = Mock(side_effect=AssertionError("Candidate import opened a database"))
    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", connection)
    before = dict(adoption.ADOPTION_PROFILES)
    choices = tuple(EventEdition._meta.get_field("adoption_profile_code").choices)
    importlib.reload(candidate)
    assert before == adoption.ADOPTION_PROFILES
    assert adoption.adoption_profile(*PROFILE.key) is None
    assert adoption.selectable_adoption_profile(PROFILE.code.value) is None
    assert PROFILE.key not in PERSISTED_ADOPTION_PROFILE_KEYS
    assert (
        tuple(EventEdition._meta.get_field("adoption_profile_code").choices) == choices
    )
    connection.assert_not_called()


def test_candidate_resolves_owner_catalogs_but_is_deliberately_not_persistable():
    catalog = current_adoption_catalog_snapshot()
    problems = adoption_manifest_catalog_problem_codes(
        profiles={**adoption.ADOPTION_PROFILES, PROFILE.key: PROFILE},
        selectable_profile_keys=adoption.SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=catalog,
    )
    assert problems == ("manifest.persistence-key-mismatch",)
    assert PROFILE.primary_module == "programme"
    assert not catalog.registry_problem_codes


def test_candidate_keeps_complete_workforce_without_attendee_or_extra_product_scope():
    workforce = adoption.adoption_profile("workforce_only", 1)
    assert workforce.capability_codes <= PROFILE.capability_codes
    assert workforce.modules <= PROFILE.modules
    assert workforce.catalog_entries <= PROFILE.catalog_entries
    assert workforce.effect_routes <= PROFILE.effect_routes
    assert workforce.adapter_codes <= PROFILE.adapter_codes
    assert workforce.root_role_codes == PROFILE.root_role_codes
    assert not PROFILE.modules & EXCLUDED
    assert PROFILE.modules == workforce.modules | {
        "applications",
        "programme",
        "scheduling",
        "venues",
    }
    for code in (
        *PROFILE.capability_codes,
        *PROFILE.adapter_codes,
        *PROFILE.catalog_entries,
    ):
        assert code.partition(".")[0] not in EXCLUDED
    assert "venues.attendee-schedule@1" not in PROFILE.adapter_codes
    assert "workforce.assignment.participation-required@1" not in PROFILE.adapter_codes
    assert "venues.manage_accommodation" not in PROFILE.capability_codes
    assert all("attendee" not in code for code in PROFILE.adapter_codes)
    assert (
        not {"my.registrations", "my.catalog", "work.attendee-service"}
        & PROFILE.shell_destination_kinds
    )


@pytest.mark.parametrize(
    "recipe", tuple(PROGRAMME_ROLE_RECIPES.values()), ids=lambda r: r.code
)
def test_each_optional_role_is_pinned_without_replacing_its_scope_or_approval(recipe):
    assert recipe.catalog_entry in PROFILE.catalog_entries
    assert set(recipe.capability_codes) <= PROFILE.capability_codes
    assert recipe.role_code not in PROFILE.root_role_codes


def test_shared_and_personal_task_destinations_are_explicit_and_separate():
    assert set(PROGRAMME_SHELL_KINDS.values()) <= PROFILE.shell_destination_kinds
    assert {
        "my.applications",
        "my.schedule",
        "my.workforce",
    } <= PROFILE.shell_destination_kinds
    assert {
        "applications.self.programme_proposal@1",
        "workforce.self@1",
    } <= PROFILE.adapter_codes
    assert PROFILE.destination_codes == ("today", "workforce", "setup", "security")


def test_effects_resolve_real_handlers_without_generic_notifications():
    handlers = candidate_internal_handler_registry()
    for route in PROFILE.effect_routes:
        assert route.destination == "internal"
        assert route.event_name.partition(".")[0] not in EXCLUDED
        assert event_definition(route.event_name) is not None
        registration = handlers.resolve(
            event_name=route.event_name, destination=route.destination
        )
        assert registration is not None
        assert registration is acknowledge_internal_fact
    assert (
        handlers.resolve(event_name="registration.submitted.v1", destination="internal")
        is None
    )
    assert (
        handlers.resolve(
            event_name="identity.account_restriction.applied.v1",
            destination="notifications",
        )
        is None
    )
    runtime = built_in_handler_registry()
    for name in ACKNOWLEDGED_DORMANT_EVENTS:
        assert runtime.resolve(event_name=name, destination="internal") is None


@pytest.mark.parametrize(
    "name",
    [
        "MODULES",
        "CAPABILITIES",
        "SHELL_KINDS",
        "CATALOG_ENTRIES",
        "ADAPTERS",
        "CONFLICT_SOURCES",
        "INTERNAL_EVENTS",
    ],
)
def test_declarations_are_literal_and_unique_not_catalog_wide_inheritance(name):
    tree = ast.parse(Path(candidate.__file__).read_text(encoding="utf-8"))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    ]
    assert len(values) == 1
    literal = ast.literal_eval(values[0])
    assert isinstance(literal, tuple)
    assert all(isinstance(value, str) for value in literal)
    assert literal == getattr(candidate, name)
    assert len(literal) == len(set(literal))


def test_duplicate_pins_fail_instead_of_being_normalized_away():
    with pytest.raises(ValueError, match="duplicate"):
        candidate._unique(("one", "one"))


def test_candidate_and_its_sets_are_immutable():
    with pytest.raises(FrozenInstanceError):
        PROFILE.version = 2
    with pytest.raises(AttributeError):
        PROFILE.capability_codes.add("programme.future_capability")
