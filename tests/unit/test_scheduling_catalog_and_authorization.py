"""Deny-by-default Scheduling declarations and independently gated test policy."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

import maru.authorization.catalog as capability_catalog
import maru.effects.adoption as effect_adoption
import maru.effects.registry as effect_registry
import maru.scheduling.authorization as auth
from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.authorization.policy import PolicyDecision
from maru.effects.handlers import (
    ACKNOWLEDGED_DORMANT_EVENTS,
    built_in_handler_registry,
)
from maru.effects.registry import event_definition
from maru.events import adoption
from maru.events.adoption import ADOPTION_PROFILES
from maru.events.scheduling_queries import SchedulingEditionReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.scheduling.adoption import (
    SCHEDULING_TIME_CONFLICT_SOURCE,
    SCHEDULING_VENUE_RESERVATION_ADAPTER,
)
from maru.scheduling.catalogs import SchedulingOperation
from maru.scheduling.checks import (
    check_scheduling_dormancy,
    scheduling_dormancy_problem_codes,
)
from maru.scheduling.events import (
    SCHEDULING_CHANGED_EVENT,
    SCHEDULING_RELEASE_CHANGED_EVENT,
    validate_scheduling_changed_payload,
    validate_scheduling_release_changed_payload,
)
from maru.scheduling.planning_preview import PREVIEW_FIELDS
from maru.scheduling.planning_queries import HISTORY_FIELDS, PLANNING_FIELDS
from maru.venues.timetable_queries import TIMETABLE_SPACE_FIELDS


@pytest.mark.parametrize(
    ("capability", "fields"),
    [
        ("scheduling.view_planning", PLANNING_FIELDS),
        ("scheduling.view_history", HISTORY_FIELDS),
        ("scheduling.view_conflicts", PREVIEW_FIELDS),
        ("venues.view_workspace", TIMETABLE_SPACE_FIELDS),
    ],
)
def test_editor_reads_request_only_preexisting_capability_fields(capability, fields):
    assert fields
    assert fields <= CAPABILITIES[capability].field_ceiling


def test_host_schedule_policy_uses_exact_self_not_edition_planner(monkeypatch):
    decision = PolicyDecision(
        allowed=True,
        fields=frozenset({"own_host_schedule"}),
        obligations=frozenset({"audit_sensitive_read"}),
        reason_code="self_relationship",
    )
    personal = MagicMock(return_value=decision)
    planner = MagicMock(side_effect=AssertionError("Not planner authority"))
    monkeypatch.setattr(auth, "decide_verified_principal_exact_self", personal)
    monkeypatch.setattr(auth, "decide_verified_principal_exact_edition", planner)
    actor, organization, edition = uuid4(), uuid4(), uuid4()
    assert (
        auth.ExactSchedulingAuthorizer().authorize(
            principal_id=actor,
            organization_id=organization,
            edition_id=edition,
            capability_code=auth.VIEW_HOST_SELF,
            requested_fields=decision.fields,
        )
        == decision
    )
    personal.assert_called_once_with(
        principal_id=actor,
        owner_account_id=actor,
        organization_id=organization,
        edition_id=edition,
        capability_code=auth.VIEW_HOST_SELF,
        requested_fields=decision.fields,
    )
    planner.assert_not_called()


@pytest.mark.parametrize(
    "event_name", [SCHEDULING_CHANGED_EVENT, SCHEDULING_RELEASE_CHANGED_EVENT]
)
def test_declared_capabilities_and_event_do_not_activate_current_profiles(event_name):
    assert scheduling_dormancy_problem_codes() == ()
    assert check_scheduling_dormancy() == []
    assert event_definition(event_name) is not None
    assert event_name in ACKNOWLEDGED_DORMANT_EVENTS
    handlers = built_in_handler_registry()
    assert all(
        handlers.resolve(event_name=event_name, destination=destination) is None
        for destination in ("internal", "notifications")
    )
    for code in auth.SCHEDULING_CAPABILITIES:
        if code == auth.VIEW_HOST_SELF:
            assert CAPABILITIES[code].maximum_scope == ScopeLevel.RESOURCE
            assert CAPABILITIES[code].allow_self
            assert not CAPABILITIES[code].persistable
            assert CAPABILITIES[code].field_ceiling == frozenset({"own_host_schedule"})
        else:
            assert CAPABILITIES[code].maximum_scope == ScopeLevel.EDITION
            assert not CAPABILITIES[code].allow_self
    for profile in ADOPTION_PROFILES.values():
        assert not profile.capability_codes & auth.SCHEDULING_CAPABILITIES
        assert "scheduling" not in profile.modules


def test_scope_migration_adds_only_exact_scheduling_and_owner_dependency_codes():
    previous = import_module(
        "maru.authorization.migrations.0026_programme_host_capabilities"
    )
    current = import_module(
        "maru.authorization.migrations.0027_scheduling_capabilities"
    )
    release = import_module(
        "maru.authorization.migrations.0029_programme_release_capabilities"
    )
    assert set(current.SCHEDULING_CAPABILITIES) == {
        *(
            auth.SCHEDULING_CAPABILITIES
            - set(release.RELEASE_CAPABILITIES)
            - {auth.VIEW_HOST_SELF}
        ),
        "programme.view_scheduling_dependencies",
    }
    assert current.PHYSICAL_CAPABILITIES == ("venues.view_scheduling_dependencies",)
    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.DEPARTMENT_CAPABILITIES == previous.DEPARTMENT_CAPABILITIES
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.SCHEDULING_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    assert (
        *previous.RESOURCE_CAPABILITIES,
        *current.PHYSICAL_CAPABILITIES,
    ) == current.RESOURCE_CAPABILITIES
    assert {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    } == {
        code for code, definition in CAPABILITIES.items() if definition.persistable
    } - {
        "programme.manage_staffing",
        "programme.view_staffing",
        *release.RELEASE_CAPABILITIES,
    }
    for code in current.SCHEDULING_CAPABILITIES:
        assert CAPABILITIES[code].maximum_scope == ScopeLevel.EDITION
    for code in current.PHYSICAL_CAPABILITIES:
        assert CAPABILITIES[code].maximum_scope == ScopeLevel.RESOURCE


def test_release_migration_adds_only_four_independent_edition_capabilities():
    previous = import_module(
        "maru.authorization.migrations.0028_programme_staffing_capabilities"
    )
    current = import_module(
        "maru.authorization.migrations.0029_programme_release_capabilities"
    )
    assert current.RELEASE_CAPABILITIES == (
        "scheduling.acknowledge_release_warnings",
        "scheduling.approve_release",
        "scheduling.publish_release",
        "scheduling.withdraw_release",
    )
    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.DEPARTMENT_CAPABILITIES == previous.DEPARTMENT_CAPABILITIES
    assert current.RESOURCE_CAPABILITIES == previous.RESOURCE_CAPABILITIES
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.RELEASE_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    assert {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    } == {code for code, definition in CAPABILITIES.items() if definition.persistable}


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        ("module", "catalog.module-missing"),
        ("capability", "catalog.capability-missing"),
        ("event_absent", "catalog.event-missing-or-mismatched"),
        ("event_version", "catalog.event-missing-or-mismatched"),
        ("non_edition_route", "dormancy.non-edition-effect-route"),
        ("profile_module", "dormancy.module-adopted"),
        ("profile_capability", "dormancy.capability-adopted"),
        ("profile_adapter", "dormancy.adapter-adopted"),
        ("profile_conflict", "dormancy.conflict-source-adopted"),
        ("profile_effect", "dormancy.effect-route-adopted"),
    ],
)
def test_missing_declarations_and_each_activation_path_fail_the_system_check(
    monkeypatch, drift, expected
):
    if drift == "module":
        monkeypatch.setattr(
            adoption,
            "ADOPTION_MODULE_NAMESPACE_CATALOG",
            adoption.ADOPTION_MODULE_NAMESPACE_CATALOG - {"scheduling"},
        )
    elif drift == "capability":
        monkeypatch.delitem(capability_catalog.CAPABILITIES, auth.VIEW_PLANNING)
    elif drift.startswith("event_"):
        monkeypatch.setattr(
            effect_registry,
            "event_definition",
            lambda _: (
                None if drift == "event_absent" else SimpleNamespace(schema_version=999)
            ),
        )
    elif drift == "non_edition_route":
        monkeypatch.setattr(
            effect_adoption,
            "NON_EDITION_EFFECT_ROUTES",
            ((SCHEDULING_CHANGED_EVENT, "synthetic"),),
        )
    else:
        profile = SimpleNamespace(
            modules=frozenset({"scheduling"})
            if drift == "profile_module"
            else frozenset(),
            capability_codes=frozenset({auth.VIEW_PLANNING})
            if drift == "profile_capability"
            else frozenset(),
            adapter_codes=frozenset({SCHEDULING_VENUE_RESERVATION_ADAPTER})
            if drift == "profile_adapter"
            else frozenset(),
            conflict_source_codes=frozenset({SCHEDULING_TIME_CONFLICT_SOURCE})
            if drift == "profile_conflict"
            else frozenset(),
            effect_routes=(SimpleNamespace(event_name=SCHEDULING_CHANGED_EVENT),)
            if drift == "profile_effect"
            else (),
        )
        monkeypatch.setattr(adoption, "ADOPTION_PROFILES", {"synthetic": profile})
    assert scheduling_dormancy_problem_codes() == (expected,)
    errors = check_scheduling_dormancy()
    assert len(errors) == 1
    assert errors[0].id == "scheduling.E001"
    assert expected in errors[0].hint


@pytest.mark.parametrize("operation", list(SchedulingOperation))
def test_every_owned_operation_has_a_minimized_event(operation):
    if operation.value.startswith("release_"):
        validate_scheduling_release_changed_payload({"operation": operation.value})
        with pytest.raises(ValidationError):
            validate_scheduling_changed_payload({"operation": operation.value})
    else:
        validate_scheduling_changed_payload({"operation": operation.value})
        with pytest.raises(ValidationError):
            validate_scheduling_release_changed_payload({"operation": operation.value})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"operation": None},
        {"operation": "unknown"},
        {"operation": "placement_set", "person": "private"},
        {"operation": SchedulingOperation.PLACEMENT_SET},
    ],
)
def test_event_rejects_unknown_fields_private_values_and_unserialized_enums(payload):
    with pytest.raises(ValidationError):
        validate_scheduling_changed_payload(payload)
    with pytest.raises(ValidationError):
        validate_scheduling_release_changed_payload(payload)


def scope_mocks(monkeypatch, *, allowed=True, fields=frozenset({"candidates"})):
    actor_id, organization_id, edition_id = uuid4(), uuid4(), uuid4()
    edition_loader = MagicMock(
        return_value=SchedulingEditionReference(
            organization_id,
            edition_id,
            4,
            accepts_scheduling_writes=True,
            zone_name="Europe/Budapest",
        )
    )
    person_loader = MagicMock(return_value=ActiveVerifiedPersonReference(actor_id))
    decision = PolicyDecision(
        allowed=allowed,
        fields=fields,
        obligations=frozenset({"audit"}),
        reason_code="synthetic_policy",
    )
    ordinary_policy = MagicMock(return_value=decision)
    monkeypatch.setattr(auth, "resolve_scheduling_edition_reference", edition_loader)
    monkeypatch.setattr(auth, "resolve_active_verified_person_reference", person_loader)
    monkeypatch.setattr(
        auth, "decide_verified_principal_exact_edition", ordinary_policy
    )
    request = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "capability_code": auth.VIEW_PLANNING,
        "requested_fields": frozenset({"candidates"}),
    }
    return request, edition_loader, person_loader, ordinary_policy


def test_scope_uses_current_owner_refs_and_exact_policy(monkeypatch):
    request, edition_loader, person_loader, ordinary_policy = scope_mocks(monkeypatch)
    actual = auth.authorize_scheduling_scope(**request, lock=True)
    assert actual.actor_id == request["actor_id"]
    assert actual.edition_version == 4
    assert actual.accepts_writes
    edition_loader.assert_called_once_with(
        organization_id=request["organization_id"],
        edition_id=request["edition_id"],
        lock=True,
    )
    person_loader.assert_called_once_with(account_id=request["actor_id"], lock=True)
    ordinary_policy.assert_called_once_with(
        principal_id=request["actor_id"],
        organization_id=request["organization_id"],
        edition_id=request["edition_id"],
        capability_code=auth.VIEW_PLANNING,
        requested_fields=frozenset({"candidates"}),
    )


@pytest.mark.parametrize(
    "cause",
    ["unknown_capability", "person", "edition", "decision", "fields", "boolean"],
)
def test_scope_denials_do_not_release_partial_authority(monkeypatch, cause):
    request, edition, person, ordinary_policy = scope_mocks(
        monkeypatch,
        allowed=cause != "decision",
        fields=frozenset() if cause == "fields" else frozenset({"candidates"}),
    )
    if cause == "unknown_capability":
        request["capability_code"] = "scheduling.future_admin"
    elif cause == "person":
        person.return_value = None
    elif cause == "edition":
        edition.return_value = None
    elif cause == "boolean":
        ordinary_policy.return_value = True
    with pytest.raises(auth.SchedulingAuthorizationDeniedError):
        auth.authorize_scheduling_scope(**request)


@pytest.mark.parametrize(
    ("flag", "database"),
    [(False, "test_scope"), (True, "real_scope"), (False, "real_scope"), (True, None)],
)
def test_alternate_policy_requires_both_test_factors(
    monkeypatch, settings, flag, database
):
    settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER = flag
    monkeypatch.setattr(auth, "connection", MagicMock(settings_dict={"NAME": database}))
    request, edition, person, ordinary_policy = scope_mocks(monkeypatch)
    with pytest.raises(auth.SchedulingAuthorizationDeniedError):
        auth.authorize_scheduling_scope(**request, authorizer=MagicMock())
    edition.assert_not_called()
    person.assert_not_called()
    ordinary_policy.assert_not_called()


def test_two_factor_alternate_policy_still_requires_complete_decision(
    monkeypatch, settings
):
    settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER = True
    monkeypatch.setattr(
        auth, "connection", MagicMock(settings_dict={"NAME": "test_scope"})
    )
    request, _, _, ordinary_policy = scope_mocks(monkeypatch)
    alternate = MagicMock()
    alternate.authorize.return_value = ordinary_policy.return_value
    assert (
        auth.authorize_scheduling_scope(**request, authorizer=alternate).decision
        is alternate.authorize.return_value
    )
    ordinary_policy.assert_not_called()
