"""Database-free approval storage contracts, never native acceptance."""

import json
from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, models

from maru.authorization import programme_role_readiness as readiness
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.authorization.models import ProgrammeRoleDecisionRecord, ProgrammeRoleRequest
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.core import database_integrity_readiness as integrity
from maru.events.adoption import ADOPTION_PROFILES
from maru.events.adoption_persistence import PERSISTED_ADOPTION_PROFILE_KEYS

STORAGE = import_module(
    "maru.authorization.migrations.0032_programme_role_approval_records"
)
GUARDS = import_module(
    "maru.authorization.migrations.0033_programme_role_approval_integrity"
)
FENCE = import_module(
    "maru.authorization.migrations.0034_programme_role_approval_downgrade_fence"
)
CONTRACT = readiness.PROGRAMME_ROLE_INTEGRITY_CONTRACT


def test_two_retained_relations_are_read_only_and_leave_profiles_unmodified():
    for model in (ProgrammeRoleRequest, ProgrammeRoleDecisionRecord):
        assert (
            f"public.{model._meta.db_table}" in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
        )
        for field in model._meta.fields:
            if field.is_relation:
                assert field.remote_field.on_delete is models.PROTECT
    for name in ("request", "role_assignment", "source_audit"):
        assert ProgrammeRoleDecisionRecord._meta.get_field(name).unique
    assert ProgrammeRoleRequest._meta.get_field("source_audit").unique
    assert ("programme_operations", 1) not in ADOPTION_PROFILES
    assert ("programme_operations", 1) not in PERSISTED_ADOPTION_PROFILE_KEYS


@pytest.mark.parametrize("model", [ProgrammeRoleRequest, ProgrammeRoleDecisionRecord])
@pytest.mark.parametrize("operation", ["save", "delete"])
@pytest.mark.parametrize("adding", [True, False])
def test_no_direct_orm_writer_or_deletion(model, operation, adding):
    record = model()
    record._state.adding = adding
    with pytest.raises(ValidationError, match="Programme role evidence"):
        getattr(record, operation)()


@pytest.mark.parametrize("model", [ProgrammeRoleRequest, ProgrammeRoleDecisionRecord])
def test_local_validation_never_follows_other_owner_relations(model, monkeypatch):
    base_clean = MagicMock()
    monkeypatch.setattr(models.Model, "full_clean", base_clean)
    model().full_clean(
        exclude=("reason",), validate_unique=False, validate_constraints=False
    )
    base_clean.assert_called_once_with(
        exclude={"reason"} | {f.name for f in model._meta.fields if f.is_relation},
        validate_unique=False,
        validate_constraints=False,
    )


def test_frozen_native_recipe_contents_match_every_reviewed_definition():
    frozen = json.loads(GUARDS._FROZEN_RECIPES)
    assert set(frozen) == {
        f"{code}@{version}" for code, version in PROGRAMME_ROLE_RECIPES
    }
    for (code, version), recipe in PROGRAMME_ROLE_RECIPES.items():
        assert frozen[f"{code}@{version}"] == {
            "digest": recipe.digest,
            "role_code": recipe.role_code,
            "version": recipe.version,
            "name": recipe.name,
            "capabilities": list(recipe.capability_codes),
            "scopes": [level.value for level in recipe.target_scopes],
            "resource_kind": recipe.resource_kind,
        }


def test_native_boundary_is_source_derived_and_complete_not_authorization_wide():
    assert CONTRACT.source_contract_current
    assert CONTRACT.owned_relations == readiness.PROGRAMME_ROLE_RELATIONS
    assert set(CONTRACT.required_migrations) == {
        ("authorization", "0032_programme_role_approval_records"),
        ("authorization", "0033_programme_role_approval_integrity"),
        ("authorization", "0034_programme_role_approval_downgrade_fence"),
    }
    assert len(CONTRACT.triggers) == 4
    assert set(CONTRACT.functions) == {
        "maru_programme_role_recipe(text, integer)",
        "maru_programme_role_scope_current(uuid, uuid, uuid, uuid)",
        "maru_programme_role_request_guard()",
        "maru_programme_role_decision_guard()",
        "maru_programme_role_refuse_truncate()",
    }
    assert not CONTRACT.runtime_executable_functions
    assert all(
        not function.security_definer for function in CONTRACT.functions.values()
    )
    assert all(
        function.configuration == ("search_path=pg_catalog, public, pg_temp",)
        for function in CONTRACT.functions.values()
    )
    assert (
        integrity._contract_relation_names(CONTRACT)
        == readiness.PROGRAMME_ROLE_RELATIONS
    )


def test_downgrade_fence_locks_both_relations_before_checking_evidence():
    apps, editor = MagicMock(), MagicMock()
    apps.get_model.return_value.objects.exists.return_value = True
    with pytest.raises(RuntimeError, match="retain it and fix forward"):
        STORAGE.refuse_used_programme_role_downgrade(apps, editor)
    editor.execute.assert_called_once_with(
        "LOCK TABLE public.authorization_programmerolerequest, "
        "public.authorization_programmeroledecisionrecord IN ACCESS EXCLUSIVE MODE"
    )
    assert (
        FENCE.Migration.operations[0].reverse_code
        is FENCE.refuse_used_approval_guard_downgrade
    )
    with pytest.raises(RuntimeError, match="retain it and fix forward"):
        FENCE.refuse_used_approval_guard_downgrade(apps, editor)
    apps.get_model.return_value.objects.exists.return_value = False
    STORAGE.refuse_used_programme_role_downgrade(apps, editor)


def test_readiness_rejects_missing_metadata_and_never_reads_private_data(monkeypatch):
    native, shapes = MagicMock(return_value=True), MagicMock(return_value=True)
    monkeypatch.setattr(readiness, "database_integrity_contract_is_ready", native)
    monkeypatch.setattr(readiness, "relation_schema_is_current", shapes)
    monkeypatch.setattr(readiness, "PROGRAMME_ROLE_SCHEMA_SHA256", {})
    assert not readiness.programme_role_database_integrity_is_ready()
    native.assert_not_called()
    shapes.assert_not_called()


@pytest.mark.parametrize(
    "failure", [DatabaseError, LookupError, RuntimeError, TypeError, ValueError]
)
def test_readiness_fails_closed_for_catalog_errors(monkeypatch, failure):
    monkeypatch.setattr(
        readiness,
        "PROGRAMME_ROLE_SCHEMA_SHA256",
        dict.fromkeys(readiness.PROGRAMME_ROLE_RELATIONS, "a" * 64),
    )
    monkeypatch.setattr(
        readiness,
        "database_integrity_contract_is_ready",
        MagicMock(side_effect=failure("unavailable")),
    )
    assert not readiness.programme_role_database_integrity_is_ready()


def test_readiness_requires_both_native_boundary_and_relation_shape(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "PROGRAMME_ROLE_SCHEMA_SHA256",
        dict.fromkeys(readiness.PROGRAMME_ROLE_RELATIONS, "a" * 64),
    )
    native, shapes = MagicMock(return_value=True), MagicMock(return_value=True)
    monkeypatch.setattr(readiness, "database_integrity_contract_is_ready", native)
    monkeypatch.setattr(readiness, "relation_schema_is_current", shapes)
    assert readiness.programme_role_database_integrity_is_ready()
    native.assert_called_once_with(CONTRACT)
    shapes.assert_called_once_with(readiness.PROGRAMME_ROLE_SCHEMA_SHA256)
    native.return_value = False
    assert not readiness.programme_role_database_integrity_is_ready()
    native.return_value = True
    shapes.return_value = False
    assert not readiness.programme_role_database_integrity_is_ready()


@pytest.mark.parametrize("migration", list(readiness._MIGRATION_SOURCE_SHA256))
def test_storage_and_downgrade_sources_are_pinned(monkeypatch, migration):
    assert readiness._retained_migration_sources_current()
    monkeypatch.setitem(readiness._MIGRATION_SOURCE_SHA256, migration, "0" * 64)
    assert not readiness._retained_migration_sources_current()
