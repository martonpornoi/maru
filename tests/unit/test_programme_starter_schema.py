"""Source and model contract checks, without PostgreSQL collection or execution."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, models

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.events.adoption import ADOPTION_PROFILES
from maru.workforce import programme_starter_readiness as readiness
from maru.workforce.models import ProgrammeStarterDecision, ProgrammeStarterRequest
from maru.workforce.programme_starter_inputs import PROGRAMME_STARTER_DEFINITION
from maru.workforce.programme_starter_writer import _programme_starter_writer

GUARDS = import_module("maru.workforce.migrations.0026_programme_starter_integrity")
FENCE = import_module(
    "maru.workforce.migrations.0027_programme_starter_downgrade_fence"
)


def test_two_records_are_dormant_read_only_and_protect_all_links():
    for model in (ProgrammeStarterRequest, ProgrammeStarterDecision):
        assert (
            f"public.{model._meta.db_table}" in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
        )
        assert model._meta.get_field("source_audit").unique
        for field in model._meta.fields:
            if field.is_relation:
                assert field.remote_field.on_delete is models.PROTECT
    assert ProgrammeStarterDecision._meta.get_field("request").unique
    assert ("programme_operations", 1) not in ADOPTION_PROFILES


@pytest.mark.parametrize("model", [ProgrammeStarterRequest, ProgrammeStarterDecision])
@pytest.mark.parametrize("operation", ["save", "delete"])
@pytest.mark.parametrize("adding", [True, False])
def test_no_direct_orm_write_or_delete(model, operation, adding):
    record = model()
    record._state.adding = adding
    with pytest.raises(ValidationError):
        getattr(record, operation)()


@pytest.mark.parametrize("model", [ProgrammeStarterRequest, ProgrammeStarterDecision])
def test_writer_scope_does_not_allow_updating_retained_evidence(model):
    record = model()
    record._state.adding = False
    with _programme_starter_writer(), pytest.raises(ValidationError, match="retained"):
        record.save()


@pytest.mark.parametrize("model", [ProgrammeStarterRequest, ProgrammeStarterDecision])
def test_clean_never_traverses_foreign_owners(model, monkeypatch):
    clean = MagicMock()
    monkeypatch.setattr(models.Model, "full_clean", clean)
    model().full_clean(
        exclude=("reason",), validate_unique=False, validate_constraints=False
    )
    clean.assert_called_once_with(
        exclude={"reason"}
        | {field.name for field in model._meta.fields if field.is_relation},
        validate_unique=False,
        validate_constraints=False,
    )


def test_native_source_contract_pins_all_three_migrations_and_four_guards():
    contract = readiness.PROGRAMME_STARTER_INTEGRITY_CONTRACT
    assert contract.source_contract_current
    assert contract.owned_relations == readiness.PROGRAMME_STARTER_RELATIONS
    assert set(contract.required_migrations) == {
        ("workforce", "0025_programme_starter_records"),
        ("workforce", "0026_programme_starter_integrity"),
        ("workforce", "0027_programme_starter_downgrade_fence"),
    }
    assert len(contract.triggers) == 4
    assert set(contract.functions) == {
        "maru_workforce_starter_request_guard()",
        "maru_workforce_starter_decision_guard()",
        "maru_workforce_starter_refuse_truncate()",
    }
    assert not contract.runtime_executable_functions
    assert all(
        not function.security_definer for function in contract.functions.values()
    )
    assert PROGRAMME_STARTER_DEFINITION.digest in GUARDS.FORWARD_SQL
    assert "authorization.role_bundle.version_create.approve" in GUARDS.FORWARD_SQL
    assert "clock_timestamp() >= original.approval_deadline" in GUARDS.FORWARD_SQL


def test_any_migration_source_drift_fails_closed(monkeypatch):
    monkeypatch.setattr(readiness.inspect, "getsource", lambda _: "changed")
    assert not readiness._sources_current()


@pytest.mark.parametrize("fault", [None, "schema", "native", "error", "missing_pin"])
def test_readiness_requires_actual_native_and_table_metadata(monkeypatch, fault):
    native = MagicMock(return_value=fault != "native")
    if fault == "error":
        native.side_effect = DatabaseError("private")
    schema = MagicMock(return_value=fault != "schema")
    monkeypatch.setattr(readiness, "database_integrity_contract_is_ready", native)
    monkeypatch.setattr(readiness, "relation_schema_is_current", schema)
    if fault == "missing_pin":
        monkeypatch.setattr(readiness, "PROGRAMME_STARTER_SCHEMA_SHA256", {})
    assert readiness.programme_starter_database_integrity_is_ready() is (fault is None)
    if fault == "missing_pin":
        native.assert_not_called()
    elif fault in {"native", "error"}:
        schema.assert_not_called()


@pytest.mark.parametrize(
    "used", [None, "ProgrammeStarterRequest", "ProgrammeStarterDecision"]
)
def test_reverse_fences_both_retained_sources_before_contraction(used):
    trace = []
    apps = SimpleNamespace(
        get_model=lambda _app, name: SimpleNamespace(
            objects=SimpleNamespace(
                exists=lambda: (trace.append(name), used == name)[1]
            )
        )
    )
    editor = SimpleNamespace(execute=trace.append)
    if used:
        with pytest.raises(RuntimeError, match="fix forward"):
            FENCE.refuse_used_starter_downgrade(apps, editor)
    else:
        FENCE.refuse_used_starter_downgrade(apps, editor)
    assert trace[0] == (
        "LOCK TABLE public.workforce_programmestarterrequest, "
        "public.workforce_programmestarterdecision IN ACCESS EXCLUSIVE MODE"
    )
