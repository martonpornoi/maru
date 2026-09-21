"""Minimized stop-purpose routing never replaces either current authority check."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from maru.authorization import programme_stop_authorization as boundary
from maru.authorization.catalog import ScopeLevel
from maru.authorization.services import AuthorizationDenied


@pytest.fixture
def admitted(monkeypatch):
    arguments = {
        name: uuid4() for name in ("actor_id", "organization_id", "edition_id")
    }
    events = []
    target, actor = object(), object()
    monkeypatch.setattr(boundary, "connection", SimpleNamespace(in_atomic_block=True))

    def preflight(**kwargs):
        assert kwargs == arguments
        events.append("preflight")

    monkeypatch.setattr(boundary, "require_programme_stop_preflight", preflight)
    monkeypatch.setattr(
        boundary,
        "lock_retired_department_authority_boundaries",
        lambda: events.append("fences"),
    )
    monkeypatch.setattr(boundary, "_require_profile", lambda: events.append("profile"))

    def scope(value, *, historical):
        assert value.organization_id == arguments["organization_id"]
        assert value.programme_edition_id == arguments["edition_id"]
        assert value.level == ScopeLevel.EDITION
        assert historical is True
        events.append("scope")
        return target

    def people(identities):
        assert identities == {arguments["actor_id"]}
        events.append("people")
        return {arguments["actor_id"]: actor}

    def controller(actual, resource):
        assert (actual, resource) == (actor, target)
        events.append("controller")

    def policy(**kwargs):
        assert kwargs == {
            "principal": actor,
            "resource": target,
            "capability_code": "events.transition",
        }
        events.append("transition")
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(boundary, "_lock_scope", scope)
    monkeypatch.setattr(boundary, "_lock_people", people)
    monkeypatch.setattr(boundary, "_require_current_controller", controller)
    monkeypatch.setattr(boundary, "decide", policy)
    monkeypatch.setattr(
        boundary, "_require_integrity", lambda: events.append("integrity")
    )
    return arguments, events


def test_stop_admission_requires_both_actual_authorities_and_native_integrity(admitted):
    arguments, events = admitted
    assert boundary.require_programme_stop_controller(**arguments) is None
    assert events == [
        "preflight",
        "fences",
        "profile",
        "scope",
        "people",
        "controller",
        "transition",
        "integrity",
    ]


@pytest.mark.parametrize("field", ["actor_id", "organization_id", "edition_id"])
@pytest.mark.parametrize("value", [None, "not-an-id", UUID(int=0), 1, True])
def test_invalid_scope_does_not_observe_any_private_state(admitted, field, value):
    arguments, events = admitted
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_controller(**{**arguments, field: value})
    assert events == []


def test_admission_cannot_release_its_locks_before_the_callers_operation(
    admitted, monkeypatch
):
    arguments, events = admitted
    monkeypatch.setattr(boundary, "connection", SimpleNamespace(in_atomic_block=False))
    with pytest.raises(RuntimeError, match="open transaction"):
        boundary.require_programme_stop_controller(**arguments)
    assert events == []


def test_current_controller_is_not_a_substitute_for_events_permission(
    admitted, monkeypatch
):
    arguments, events = admitted
    monkeypatch.setattr(boundary, "decide", lambda **_: SimpleNamespace(allowed=False))
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_controller(**arguments)
    assert events == ["preflight", "fences", "profile", "scope", "people", "controller"]


def test_preflight_denial_precedes_private_foundation_locks(admitted, monkeypatch):
    def denied(**_):
        raise AuthorizationDenied("Unavailable", reason_code="synthetic_denial")

    monkeypatch.setattr(boundary, "require_programme_stop_preflight", denied)
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_controller(**admitted[0])
    assert admitted[1] == []


@pytest.fixture
def preflight_context(monkeypatch):
    arguments = {
        name: uuid4() for name in ("actor_id", "organization_id", "edition_id")
    }
    events = []
    monkeypatch.setattr(boundary, "_require_profile", lambda: events.append("profile"))

    def people(**kwargs):
        assert kwargs == {"account_ids": {arguments["actor_id"]}}
        events.append("people")
        return (SimpleNamespace(account_id=arguments["actor_id"]),)

    def resolve(scope):
        assert scope.organization_id == arguments["organization_id"]
        assert scope.programme_edition_id == arguments["edition_id"]
        assert scope.level == ScopeLevel.EDITION
        events.append("scope")

    def policy(**kwargs):
        assert kwargs["principal_id"] == arguments["actor_id"]
        assert kwargs["organization_id"] == arguments["organization_id"]
        assert kwargs["edition_id"] == arguments["edition_id"]
        events.append(kwargs["capability_code"])
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(boundary, "resolve_active_verified_person_references", people)
    monkeypatch.setattr(boundary, "_resolve_scope", resolve)
    monkeypatch.setattr(boundary, "decide_verified_principal_exact_edition", policy)
    return arguments, events


def test_preflight_checks_exact_person_scope_and_both_capabilities(preflight_context):
    arguments, events = preflight_context
    assert boundary.require_programme_stop_preflight(**arguments) is None
    assert events == [
        "profile",
        "people",
        "scope",
        "authorization.manage_roles",
        "events.transition",
    ]


@pytest.mark.parametrize("people", [None, (), (SimpleNamespace(account_id=uuid4()),)])
def test_preflight_requires_exact_actual_person(preflight_context, monkeypatch, people):
    monkeypatch.setattr(
        boundary, "resolve_active_verified_person_references", lambda **_: people
    )
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_preflight(**preflight_context[0])
    assert preflight_context[1] == ["profile"]


@pytest.mark.parametrize(
    "capability", ["authorization.manage_roles", "events.transition"]
)
def test_preflight_denies_either_missing_capability(
    preflight_context, monkeypatch, capability
):
    monkeypatch.setattr(
        boundary,
        "decide_verified_principal_exact_edition",
        lambda **kwargs: SimpleNamespace(
            allowed=kwargs["capability_code"] != capability
        ),
    )
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_preflight(**preflight_context[0])
    assert preflight_context[1] == ["profile", "people", "scope"]


@pytest.mark.parametrize("stage", ["_require_current_controller", "_require_integrity"])
def test_unavailable_controller_or_native_evidence_is_not_ignored(
    admitted, monkeypatch, stage
):
    def unavailable(*_):
        raise AuthorizationDenied("Unavailable", reason_code="synthetic_denial")

    monkeypatch.setattr(boundary, stage, unavailable)
    with pytest.raises(AuthorizationDenied):
        boundary.require_programme_stop_controller(**admitted[0])
