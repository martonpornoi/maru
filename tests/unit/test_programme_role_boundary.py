"""Exercise exact scope and persistent source admission without a database."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.authorization import programme_role_boundary as boundary
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.authorization.provenance import ControlHorizonMode
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account

RECIPE = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]


def scope(level=ScopeLevel.EDITION):
    return ProgrammeRoleScope(
        UUID(int=1),
        UUID(int=2),
        level,
        UUID(int=3) if level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE} else None,
        UUID(int=4) if level is ScopeLevel.RESOURCE else None,
        "venue.edition_space" if level is ScopeLevel.RESOURCE else "",
    )


@pytest.mark.parametrize("fault", ["profile", "recipe", "capability"])
def test_exact_profile_recipe_and_capabilities_all_required(monkeypatch, fault):
    monkeypatch.setattr(
        boundary,
        "adoption_profile",
        lambda *_: None if fault == "profile" else object(),
    )
    monkeypatch.setattr(
        boundary, "profile_allows_catalog_entry", lambda *_: fault != "recipe"
    )
    monkeypatch.setattr(
        boundary, "profile_allows_capabilities", lambda *_: fault != "capability"
    )
    with pytest.raises(AuthorizationDenied):
        boundary._require_profile(RECIPE)


@pytest.mark.parametrize("level", list(ScopeLevel))
def test_scope_uses_complete_owner_chain_and_exact_resolver(monkeypatch, level):
    values = scope(level)
    context = SimpleNamespace(
        adoption_profile_code="programme_operations", adoption_profile_version=1
    )
    resolvers = {}
    for name in (
        "resolve_edition_target",
        "resolve_organization_target",
        "resolve_department_target",
        "resolve_resource_target",
    ):
        resolvers[name] = MagicMock(return_value=context)
        monkeypatch.setattr(boundary, name, resolvers[name])
    assert boundary._resolve_scope(values) is context
    resolvers["resolve_edition_target"].assert_called_once_with(
        organization_id=values.organization_id, edition_id=values.programme_edition_id
    )
    selected = f"resolve_{level.value}_target"
    args = resolvers[selected].call_args.kwargs
    assert args["organization_id"] == values.organization_id
    if level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE}:
        assert args["department_id"] == values.department_id
    if level is ScopeLevel.RESOURCE:
        assert args["resource_binding_id"] == values.resource_binding_id
    for name, mock in resolvers.items():
        if name not in {selected, "resolve_edition_target"}:
            mock.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": UUID(int=0)},
        {"programme_edition_id": "uuid"},
        {"level": "edition"},
        {"department_id": uuid4()},
        {"resource_binding_id": uuid4()},
        {"resource_kind": "venue.edition_space"},
        {"level": ScopeLevel.DEPARTMENT},
        {"level": ScopeLevel.RESOURCE},
    ],
)
def test_malformed_scope_never_resolves_owner(monkeypatch, changes):
    resolver = MagicMock()
    monkeypatch.setattr(boundary, "resolve_edition_target", resolver)
    with pytest.raises(AuthorizationDenied):
        boundary._resolve_scope(replace(scope(), **changes))
    resolver.assert_not_called()


@pytest.mark.parametrize(
    "context",
    [
        None,
        SimpleNamespace(
            adoption_profile_code="workforce_only", adoption_profile_version=1
        ),
        SimpleNamespace(
            adoption_profile_code="programme_operations", adoption_profile_version=2
        ),
    ],
)
def test_shared_organization_role_still_requires_exact_programme_context(
    monkeypatch, context
):
    monkeypatch.setattr(boundary, "resolve_edition_target", lambda **_: context)
    organization = MagicMock()
    monkeypatch.setattr(boundary, "resolve_organization_target", organization)
    with pytest.raises(AuthorizationDenied):
        boundary._resolve_scope(scope(ScopeLevel.ORGANIZATION))
    organization.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    ["missing", "inactive", "representation", "edition", "archived", "cancelled"],
)
def test_locked_scope_requires_active_foundation_and_lifecycle(monkeypatch, fault):
    foundation = SimpleNamespace(
        fingerprint="a" * 64,
        organization_lifecycle="suspended" if fault == "inactive" else "active",
        representation_state="provisioning" if fault == "representation" else "active",
    )
    monkeypatch.setattr(
        boundary,
        "resolve_programme_setup_foundation",
        lambda **_: None if fault == "missing" else foundation,
    )
    monkeypatch.setattr(
        boundary, "lock_programme_setup_foundation", lambda **_: foundation
    )
    monkeypatch.setattr(
        boundary, "lock_edition_ownership", lambda **_: fault != "edition"
    )
    monkeypatch.setattr(boundary, "resolve_edition_target", lambda **_: object())
    monkeypatch.setattr(
        boundary,
        "_lock_target",
        lambda _: SimpleNamespace(
            edition=SimpleNamespace(lifecycle=fault), target=object()
        ),
    )
    with pytest.raises(AuthorizationDenied):
        boundary._lock_scope(scope())


def test_locked_scope_orders_representation_parents_then_target(monkeypatch):
    calls = []
    foundation = SimpleNamespace(
        fingerprint="a" * 64,
        organization_lifecycle="active",
        representation_state="active",
    )
    context, target = object(), object()
    monkeypatch.setattr(
        boundary, "resolve_programme_setup_foundation", lambda **_: foundation
    )
    monkeypatch.setattr(
        boundary,
        "lock_programme_setup_foundation",
        lambda **_: (calls.append("representation"), foundation)[1],
    )
    monkeypatch.setattr(
        boundary,
        "lock_edition_ownership",
        lambda **_: (calls.append("owners"), True)[1],
    )
    monkeypatch.setattr(boundary, "resolve_edition_target", lambda **_: context)
    monkeypatch.setattr(boundary, "_resolve_scope", lambda _: target)
    monkeypatch.setattr(
        boundary,
        "_lock_target",
        lambda value: (
            calls.append("context" if value is context else "target"),
            SimpleNamespace(edition=SimpleNamespace(lifecycle="live"), target=value),
        )[1],
    )
    assert boundary._lock_scope(scope()) is target
    assert calls == ["representation", "owners", "context", "target"]


@pytest.mark.parametrize("references", [None, ()])
def test_missing_people_do_not_become_eligible(monkeypatch, references):
    resolver = MagicMock(return_value=references)
    monkeypatch.setattr(boundary, "resolve_active_verified_person_references", resolver)
    ids = {uuid4(), uuid4(), uuid4()}
    with pytest.raises(AuthorizationDenied):
        boundary._lock_people(ids)
    resolver.assert_called_once_with(account_ids=ids, lock=True)


@pytest.mark.parametrize("kind", [None, "different.resource"])
def test_locked_resource_must_match_the_recipe_kind(monkeypatch, kind):
    foundation = SimpleNamespace(
        fingerprint="a" * 64,
        organization_lifecycle="active",
        representation_state="active",
    )
    monkeypatch.setattr(
        boundary, "resolve_programme_setup_foundation", lambda **_: foundation
    )
    monkeypatch.setattr(
        boundary, "lock_programme_setup_foundation", lambda **_: foundation
    )
    monkeypatch.setattr(boundary, "lock_edition_ownership", lambda **_: True)
    monkeypatch.setattr(boundary, "resolve_edition_target", lambda **_: object())
    monkeypatch.setattr(boundary, "_resolve_scope", lambda _: object())
    monkeypatch.setattr(
        boundary,
        "_lock_target",
        lambda _: SimpleNamespace(
            edition=SimpleNamespace(lifecycle="live"),
            target=object(),
            resource_binding=SimpleNamespace(resource_kind=kind) if kind else None,
        ),
    )
    with pytest.raises(AuthorizationDenied):
        boundary._lock_scope(scope(ScopeLevel.RESOURCE))


@pytest.mark.parametrize("fault", ["inactive", "platform", "unverified", "denied"])
def test_actor_requires_active_verified_person_and_scoped_policy(monkeypatch, fault):
    actor = Account(
        is_active=fault != "inactive",
        account_kind="platform_administrator" if fault == "platform" else "person",
        email_verified_at=None if fault == "unverified" else boundary.timezone.now(),
    )
    monkeypatch.setattr(
        boundary, "decide", lambda **_: SimpleNamespace(allowed=fault != "denied")
    )
    with pytest.raises(AuthorizationDenied):
        boundary._require_actor(actor, object())


def test_replay_requires_current_persistent_source_not_just_policy(monkeypatch):
    actor, target = object(), object()
    monkeypatch.setattr(boundary, "_require_actor", lambda *_: None)
    selector = MagicMock(return_value=None)
    monkeypatch.setattr(boundary, "select_authorized_control_source", selector)
    with pytest.raises(AuthorizationDenied):
        boundary._require_current_controller(actor, target)
    assert selector.call_args.kwargs["horizon_mode"] is ControlHorizonMode.POINT_IN_TIME
    assert selector.call_args.kwargs["principal"] is actor
    assert selector.call_args.kwargs["target"] is target


def test_both_controllers_must_cover_exact_persistent_interval(monkeypatch):
    author, approver, target = object(), object(), object()
    start, end = boundary.timezone.now(), boundary.timezone.now()
    actor_check, horizon_check = MagicMock(), MagicMock()
    monkeypatch.setattr(boundary, "_require_actor", actor_check)
    monkeypatch.setattr(
        boundary.authority, "require_authorized_control_horizon", horizon_check
    )
    boundary._require_horizons(author, approver, target, start, end)
    assert [call.args[0] for call in actor_check.call_args_list] == [author, approver]
    assert [call.kwargs["principal"] for call in horizon_check.call_args_list] == [
        author,
        approver,
    ]
    for call in horizon_check.call_args_list:
        assert call.kwargs["requested_effective_from"] == start
        assert call.kwargs["requested_expires_at"] == end
        assert call.kwargs["target"] is target


@pytest.fixture
def bundle_world(monkeypatch):
    bundle = SimpleNamespace(
        id=uuid4(),
        version=1,
        name=RECIPE.name,
        capability_codes=list(RECIPE.capability_codes),
    )
    manager = MagicMock()
    manager.filter.return_value = manager
    manager.first.return_value = bundle
    manager.exists.return_value = False
    monkeypatch.setattr(boundary.RoleBundle, "objects", manager)
    proof = MagicMock(return_value=True)
    monkeypatch.setattr(boundary, "role_bundle_provenance_is_historical", proof)
    target = object()
    monkeypatch.setattr(boundary, "resolve_organization_target", lambda **_: target)
    creator = MagicMock(return_value=bundle)
    monkeypatch.setattr(boundary.authority, "create_role_bundle_version", creator)
    return SimpleNamespace(
        bundle=bundle, manager=manager, proof=proof, creator=creator, target=target
    )


def exact_bundle():
    return boundary._exact_bundle(
        scope=scope(),
        recipe=RECIPE,
        author=object(),
        approver=object(),
        reason="Synthetic intent.",
        correlation_id=uuid4(),
        source_channel="test",
    )


@pytest.mark.parametrize("fault", ["version", "name", "capabilities", "provenance"])
def test_familiar_role_cannot_substitute_for_exact_historical_recipe(
    bundle_world, fault
):
    if fault == "version":
        bundle_world.bundle.version = 2
    elif fault == "name":
        bundle_world.bundle.name = "Different name"
    elif fault == "capabilities":
        bundle_world.bundle.capability_codes.append("authorization.manage_roles")
    else:
        bundle_world.proof.return_value = False
    with pytest.raises(ValidationError, match="reviewed role version"):
        exact_bundle()
    bundle_world.creator.assert_not_called()


def test_exact_bundle_reuse_never_upgrades_existing_role(bundle_world):
    assert exact_bundle() is bundle_world.bundle
    bundle_world.creator.assert_not_called()
    assert bundle_world.proof.call_args.kwargs["lock"] is True


def test_new_role_uses_existing_dual_control_owner_command(bundle_world):
    bundle_world.manager.first.return_value = None
    assert exact_bundle() is bundle_world.bundle
    args = bundle_world.creator.call_args.kwargs
    assert args["target"] is bundle_world.target
    assert args["code"] == RECIPE.role_code
    assert args["name"] == RECIPE.name
    assert args["capability_codes"] == RECIPE.capability_codes


def test_missing_version_in_existing_role_history_is_not_silently_replaced(
    bundle_world,
):
    bundle_world.manager.first.return_value = None
    bundle_world.manager.exists.return_value = True
    with pytest.raises(ValidationError, match="reviewed role version"):
        exact_bundle()
    bundle_world.creator.assert_not_called()


def test_integrity_failure_denies(monkeypatch):
    monkeypatch.setattr(
        boundary, "programme_role_database_integrity_is_ready", lambda: False
    )
    with pytest.raises(ValidationError, match="integrity"):
        boundary._require_integrity()
