"""Check the extra archive purpose without claiming database or source admission."""

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.authorization.catalog import (
    CAPABILITIES,
    ScopeLevel,
    Sensitivity,
    require_capability,
)
from maru.authorization.policy import PolicyDecision
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.events.adoption import ADOPTION_PROFILES, profile_allows_adapter
from maru.events.checks import current_adoption_catalog_snapshot
from maru.events.queries import EditionAdoptionProfileReference
from maru.programme import archive_authorization as archive
from maru.programme import authorization as auth


@pytest.fixture
def scope(monkeypatch):
    ids = dict(
        zip(
            ("actor_id", "organization_id", "edition_id"),
            (UUID(int=i) for i in range(1, 4)),
            strict=True,
        )
    )
    edition = Mock(
        return_value=SimpleNamespace(
            organization_id=ids["organization_id"],
            edition_id=ids["edition_id"],
            accepts_private_planning_writes=False,
        )
    )
    actor = Mock(return_value=SimpleNamespace(account_id=ids["actor_id"]))
    decision = PolicyDecision(
        allowed=True,
        fields=archive.PROGRAMME_ARCHIVE_FIELDS,
        obligations=frozenset({"audit_sensitive_read"}),
        reason_code="synthetic",
    )
    policy = Mock(return_value=decision)
    profile = Mock(return_value=EditionAdoptionProfileReference("synthetic", 1))
    adapter = Mock(return_value=True)
    monkeypatch.setattr(auth, "resolve_private_planning_edition_reference", edition)
    monkeypatch.setattr(auth, "resolve_active_verified_account_reference", actor)
    monkeypatch.setattr(auth, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(archive, "edition_adoption_profile_reference", profile)
    monkeypatch.setattr(archive, "profile_allows_adapter", adapter)
    return SimpleNamespace(
        ids=ids,
        edition=edition,
        actor=actor,
        policy=policy,
        profile=profile,
        adapter=adapter,
        decision=decision,
    )


@pytest.mark.parametrize(
    "fields",
    [
        frozenset({"archive_requests"}),
        frozenset({"source_lineage"}),
        archive.PROGRAMME_ARCHIVE_FIELDS,
    ],
)
@pytest.mark.parametrize("lock", [False, True])
def test_exact_purpose_uses_real_scope_seam_and_forwards_lock(scope, fields, lock):
    result = archive.authorize_programme_archive_scope(
        **scope.ids, requested_fields=fields, lock=lock
    )
    assert result.decision is scope.decision
    assert not result.accepts_private_planning_writes
    scope.edition.assert_called_once_with(
        organization_id=scope.ids["organization_id"],
        edition_id=scope.ids["edition_id"],
        lock=lock,
    )
    scope.actor.assert_called_once_with(account_id=scope.ids["actor_id"], lock=lock)
    scope.policy.assert_called_once_with(
        principal_id=scope.ids["actor_id"],
        organization_id=scope.ids["organization_id"],
        edition_id=scope.ids["edition_id"],
        capability_code="programme.export_archive",
        requested_fields=fields,
    )
    scope.profile.assert_called_once_with(
        organization_id=scope.ids["organization_id"], edition_id=scope.ids["edition_id"]
    )
    scope.adapter.assert_called_once_with("synthetic", 1, "programme.exit-archive@1")


@pytest.mark.parametrize(
    "fields",
    [
        None,
        True,
        "archive_requests",
        [],
        {"archive_requests"},
        frozenset(),
        frozenset({"*"}),
        frozenset({"working_history"}),
        frozenset({"archive_requests", "private_files"}),
        frozenset({1}),
    ],
)
def test_unknown_or_untyped_fields_deny_before_any_scope_read(scope, fields):
    with pytest.raises(auth.ProgrammeAuthorizationDeniedError):
        archive.authorize_programme_archive_scope(**scope.ids, requested_fields=fields)
    scope.edition.assert_not_called()
    scope.actor.assert_not_called()
    scope.policy.assert_not_called()
    scope.profile.assert_not_called()


@pytest.mark.parametrize("missing", ["actor", "edition"])
def test_absent_actor_or_wrong_tenant_edition_denies_before_policy(scope, missing):
    getattr(scope, missing).return_value = None
    with pytest.raises(auth.ProgrammeAuthorizationDeniedError):
        archive.authorize_programme_archive_scope(
            **scope.ids, requested_fields=archive.PROGRAMME_ARCHIVE_FIELDS
        )
    scope.policy.assert_not_called()
    scope.profile.assert_not_called()


@pytest.mark.parametrize(
    "defect", ["denied", "partial", "boolean", "no-profile", "adapter"]
)
def test_each_required_admission_fails_closed(scope, defect):
    if defect == "denied":
        scope.policy.return_value = replace(scope.decision, allowed=False)
    elif defect == "partial":
        scope.policy.return_value = replace(
            scope.decision, fields=frozenset({"archive_requests"})
        )
    elif defect == "boolean":
        scope.policy.return_value = True
    elif defect == "no-profile":
        scope.profile.return_value = None
    else:
        scope.adapter.return_value = False
    with pytest.raises(auth.ProgrammeAuthorizationDeniedError):
        archive.authorize_programme_archive_scope(
            **scope.ids, requested_fields=archive.PROGRAMME_ARCHIVE_FIELDS
        )


def test_current_policy_is_repeated_not_cached(scope):
    args = scope.ids | {"requested_fields": archive.PROGRAMME_ARCHIVE_FIELDS}
    archive.authorize_programme_archive_scope(**args)
    scope.policy.return_value = replace(scope.decision, allowed=False)
    with pytest.raises(auth.ProgrammeAuthorizationDeniedError):
        archive.authorize_programme_archive_scope(**args)
    assert scope.policy.call_count == 2


def test_replacement_authorizer_remains_sealed_outside_isolated_test_database(
    scope, monkeypatch
):
    monkeypatch.setitem(auth.connection.settings_dict, "NAME", "not_an_isolated_test")
    replacement = Mock()
    with pytest.raises(auth.ProgrammeAuthorizationDeniedError):
        archive.authorize_programme_archive_scope(
            **scope.ids,
            requested_fields=archive.PROGRAMME_ARCHIVE_FIELDS,
            authorizer=replacement,
        )
    replacement.authorize.assert_not_called()
    scope.edition.assert_not_called()


def test_dormant_extra_purpose_does_not_broaden_source_rights_or_existing_recipes():
    definition = require_capability(auth.PROGRAMME_EXPORT_ARCHIVE)
    assert definition.maximum_scope is ScopeLevel.EDITION
    assert definition.sensitivity_ceiling is Sensitivity.RESTRICTED
    assert definition.field_ceiling == archive.PROGRAMME_ARCHIVE_FIELDS
    assert definition.obligations == {"reason", "audit", "audit_sensitive_read"}
    recipe = PROGRAMME_ROLE_RECIPES[("exit-archive", 1)]
    assert recipe.capability_codes == (auth.PROGRAMME_EXPORT_ARCHIVE,)
    assert recipe.target_scopes == (ScopeLevel.EDITION,)
    assert all(
        auth.PROGRAMME_EXPORT_ARCHIVE not in r.capability_codes
        for r in PROGRAMME_ROLE_RECIPES.values()
        if r is not recipe
    )
    for code in (
        auth.PROGRAMME_VIEW_PRIVATE,
        auth.PROGRAMME_VIEW_DELIVERY,
        auth.PROGRAMME_VIEW_READINESS,
        auth.PROGRAMME_VIEW_DISCUSSION,
    ):
        assert (
            not require_capability(code).field_ceiling
            & archive.PROGRAMME_ARCHIVE_FIELDS
        )
    snapshot = current_adoption_catalog_snapshot()
    assert snapshot.registry_problem_codes == ()
    assert archive.PROGRAMME_EXIT_ARCHIVE_ADAPTER in snapshot.adapter_codes
    for profile in ADOPTION_PROFILES.values():
        assert auth.PROGRAMME_EXPORT_ARCHIVE not in profile.capability_codes
        assert recipe.catalog_entry not in profile.catalog_entries
        assert not profile_allows_adapter(
            profile.code, profile.version, archive.PROGRAMME_EXIT_ARCHIVE_ADAPTER
        )


@pytest.mark.parametrize(
    ("grant", "bundle"), [(False, False), (True, False), (False, True)]
)
def test_capability_reverse_locks_and_fences_any_retained_authority(grant, bundle):
    migration = import_module(
        "maru.authorization.migrations.0037_programme_archive_capability"
    )
    apps, editor = Mock(), Mock()
    models = {"CapabilityGrant": Mock(), "RoleBundle": Mock()}
    apps.get_model.side_effect = lambda _app, name: models[name]
    models["CapabilityGrant"].objects.filter.return_value.exists.return_value = grant
    models["RoleBundle"].objects.filter.return_value.exists.return_value = bundle
    if grant or bundle:
        with pytest.raises(RuntimeError, match="retain it and fix forward"):
            migration.refuse_used_archive_capability_downgrade(apps, editor)
    else:
        migration.refuse_used_archive_capability_downgrade(apps, editor)
    editor.execute.assert_called_once_with(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    models["CapabilityGrant"].objects.filter.assert_called_once_with(
        capability_code="programme.export_archive"
    )
    if not grant:
        models["RoleBundle"].objects.filter.assert_called_once_with(
            capability_codes__contains=["programme.export_archive"]
        )


def test_recipe_reverse_requires_unused_evidence_and_restores_exact_predecessor():
    migration = import_module(
        "maru.authorization.migrations.0038_programme_archive_recipe"
    )
    previous = import_module(
        "maru.authorization.migrations.0036_programme_room_operations_recipe"
    )
    assert migration._OLD_RECIPES == previous._FROZEN_RECIPES
    assert migration.FORWARD_SQL.startswith(previous._LOCKS)
    assert migration.REVERSE_SQL.startswith(previous._LOCKS + migration._UNUSED_ONLY)
    assert (
        "recipe_code = 'exit-archive' AND recipe_version = 1" in migration._UNUSED_ONLY
    )
    assert "code = 'programme-exit-archive'" in migration._UNUSED_ONLY
    assert "retain it and fix forward" in migration._UNUSED_ONLY


def test_native_scope_vocabulary_adds_only_the_archive_edition_capability():
    migration = import_module(
        "maru.authorization.migrations.0037_programme_archive_capability"
    )
    previous = import_module(
        "maru.authorization.migrations.0031_programme_change_communication_capabilities"
    )
    names = (
        "ORGANIZATION_CAPABILITIES",
        "EDITION_CAPABILITIES",
        "DEPARTMENT_CAPABILITIES",
        "RESOURCE_CAPABILITIES",
    )
    declared = set()
    for name, level in zip(names, ScopeLevel, strict=True):
        codes = getattr(migration, name)
        old = getattr(previous, name)
        assert codes == (
            (*old, "programme.export_archive") if level is ScopeLevel.EDITION else old
        )
        assert len(codes) == len(set(codes))
        assert not declared.intersection(codes)
        declared.update(codes)
        # Earlier native floors retain legacy Organization authority while some
        # current policy ceilings are Edition. Do not rewrite that history here.
    assert CAPABILITIES["programme.export_archive"].maximum_scope is ScopeLevel.EDITION
    assert declared == {
        code for code, definition in CAPABILITIES.items() if definition.persistable
    }
    assert "RETURN -1;" in migration.FORWARD_SQL
    assert migration.REVERSE_SQL == previous.FORWARD_SQL
    assert migration.Migration.operations[1].reverse_code is (
        migration.refuse_used_archive_capability_downgrade
    )
