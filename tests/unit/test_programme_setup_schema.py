"""Database-free setup schema contracts, not native migration acceptance."""

from dataclasses import replace
from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, models

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.core import database_integrity_readiness as integrity
from maru.events import programme_setup_readiness as readiness
from maru.events.adoption import ADOPTION_PROFILES
from maru.events.adoption_persistence import PERSISTED_ADOPTION_PROFILE_KEYS
from maru.events.models import ProgrammeAdoptionSetupReceipt
from maru.events.programme_setup_inputs import ProgrammeSetupMode

RELATION = readiness.PROGRAMME_SETUP_RELATION
CONTRACT = readiness.PROGRAMME_SETUP_INTEGRITY_CONTRACT
SCHEMA = import_module("maru.events.migrations.0012_programme_setup_receipt")
GUARDS = import_module("maru.events.migrations.0013_programme_setup_integrity")
FENCE = import_module("maru.events.migrations.0014_programme_setup_downgrade_fence")


def test_setup_schema_remains_dormant_with_exact_owner_evidence():
    fields = {
        field.name: field
        for field in ProgrammeAdoptionSetupReceipt._meta.fields
        if field.is_relation
    }
    assert {
        name: field.related_model._meta.label for name, field in fields.items()
    } == {
        "edition": "events.EventEdition",
        "organization": "organizations.Organization",
        "series": "organizations.ConventionSeries",
        "department": "workforce.Department",
        "representation": "organizations.OrganizationRepresentation",
        "actor": "identity.Account",
        "source_audit": "audit.AuditEvent",
        "edition_creation": "events.EditionCreationReceipt",
        "department_creation": "workforce.EditionStructureCommandReceipt",
    }
    assert all(
        field.remote_field.on_delete is models.PROTECT for field in fields.values()
    )
    assert all(
        fields[name].unique
        for name in (
            "edition",
            "source_audit",
            "edition_creation",
            "department_creation",
        )
    )
    assert f"public.{RELATION}" in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
    assert all(code != "programme_operations" for code, _version in ADOPTION_PROFILES)
    assert ("programme_operations", 1) not in PERSISTED_ADOPTION_PROFILE_KEYS
    choices = ProgrammeAdoptionSetupReceipt._meta.get_field("mode").choices
    assert {value for value, _label in choices} == set(ProgrammeSetupMode)


@pytest.mark.parametrize("operation", ["save", "delete"])
@pytest.mark.parametrize("adding", [True, False])
def test_orm_cannot_write_or_discard_dormant_setup_receipts(operation, adding):
    receipt = ProgrammeAdoptionSetupReceipt()
    receipt._state.adding = adding
    with pytest.raises(ValidationError, match="Programme setup receipts"):
        getattr(receipt, operation)()


def test_model_validation_does_not_dereference_other_owner_rows(monkeypatch):
    base_clean = MagicMock()
    monkeypatch.setattr(models.Model, "full_clean", base_clean)
    ProgrammeAdoptionSetupReceipt().full_clean(
        exclude=("reason",),
        validate_unique=False,
        validate_constraints=False,
    )
    base_clean.assert_called_once_with(
        exclude={
            "reason",
            "edition",
            "organization",
            "series",
            "department",
            "representation",
            "actor",
            "source_audit",
            "edition_creation",
            "department_creation",
        },
        validate_unique=False,
        validate_constraints=False,
    )


def test_setup_guard_contract_is_source_derived_and_purpose_scoped():
    assert CONTRACT.source_contract_current
    assert CONTRACT.owned_relations == (RELATION,)
    assert set(CONTRACT.required_migrations) == {
        ("events", "0012_programme_setup_receipt"),
        ("events", "0013_programme_setup_integrity"),
        ("events", "0014_programme_setup_downgrade_fence"),
    }
    assert set(CONTRACT.triggers) == {
        "events_programme_setup_receipt_guard",
        "events_programme_setup_no_truncate",
    }
    assert set(CONTRACT.functions) == {
        "maru_programme_setup_receipt_guard()",
        "maru_programme_setup_refuse_truncate()",
    }
    assert not CONTRACT.runtime_executable_functions
    assert all(
        not function.security_definer for function in CONTRACT.functions.values()
    )
    assert all(
        function.configuration == ("search_path=pg_catalog, public, pg_temp",)
        for function in CONTRACT.functions.values()
    )
    assert integrity._contract_relation_names(CONTRACT) == (RELATION,)


def test_schema_and_downgrade_source_pins_reject_changed_code(monkeypatch):
    assert readiness._retained_migration_sources_current()
    monkeypatch.setattr(
        readiness.inspect, "getsource", lambda _module: "changed source"
    )
    assert not readiness._retained_migration_sources_current()


def test_legacy_whole_app_contract_selection_is_unchanged():
    ordinary = replace(CONTRACT, owned_relations=None)
    assert integrity._contract_relation_names(
        ordinary
    ) == integrity.bounded_context_relation_names("events")
    assert len(integrity._contract_relation_names(ordinary)) > 1


@pytest.mark.parametrize(
    "selected",
    [
        (),
        (RELATION, RELATION),
        ("events_missing",),
        ("audit_auditevent",),
        ("events_eventedition",),
        [RELATION],
        RELATION,
        (None,),
        (123,),
    ],
)
def test_explicit_relation_selection_rejects_ambiguous_or_incomplete_scope(selected):
    with pytest.raises(ValueError, match="relation scope"):
        integrity._contract_relation_names(replace(CONTRACT, owned_relations=selected))


def test_subset_cannot_omit_a_primary_or_same_owner_supporting_attachment():
    trigger = next(iter(CONTRACT.triggers.values()))
    foreign = replace(trigger, table="events_eventedition")
    for changed in (
        replace(CONTRACT, triggers={**CONTRACT.triggers, "extra": foreign}),
        replace(CONTRACT, supporting_triggers={"extra": foreign}),
    ):
        with pytest.raises(ValueError, match="relation scope"):
            integrity._contract_relation_names(changed)


def _catalog_cursor(monkeypatch, *, extra_trigger=False):
    cursor = MagicMock()
    trigger_rows = [value.catalog_row for value in CONTRACT.triggers.values()]
    if extra_trigger:
        trigger_rows.append(trigger_rows[0])
    cursor.fetchall.side_effect = [
        list(CONTRACT.required_migrations),
        trigger_rows,
        [
            (
                identity,
                True,
                value.source,
                value.language,
                value.volatility,
                value.parallel,
                value.security_definer,
                value.leakproof,
                value.strict,
                value.returns_set,
                value.kind,
                list(value.configuration),
                value.result,
                True,
                True,
                True,
            )
            for identity, value in CONTRACT.functions.items()
        ],
    ]
    cursor.fetchone.return_value = (True, True)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(integrity, "connection", connection)
    return cursor


@pytest.mark.parametrize("extra_trigger", [False, True])
def test_subset_inspection_keeps_exact_trigger_equality(monkeypatch, extra_trigger):
    cursor = _catalog_cursor(monkeypatch, extra_trigger=extra_trigger)
    result = integrity.inspect_database_integrity_catalog(CONTRACT)
    assert result.ready is not extra_trigger
    calls = cursor.execute.call_args_list
    assert calls[1].args[1] == [1, [RELATION]]
    assert calls[2].args[1] == [[RELATION], []]
    assert calls[3].args[1][0] == RELATION


def test_bad_subset_fails_before_any_catalog_query(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(integrity, "connection", connection)
    assert not integrity.database_integrity_contract_is_ready(
        replace(CONTRACT, owned_relations=()),
    )
    connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    ("native_current", "schema_current"),
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_setup_readiness_requires_both_independent_boundaries(
    monkeypatch,
    native_current,
    schema_current,
):
    monkeypatch.setattr(
        readiness, "PROGRAMME_SETUP_SCHEMA_SHA256", {RELATION: "a" * 64}
    )
    native = MagicMock(return_value=native_current)
    shape = MagicMock(return_value=schema_current)
    monkeypatch.setattr(readiness, "database_integrity_contract_is_ready", native)
    monkeypatch.setattr(readiness, "relation_schema_is_current", shape)
    assert readiness.programme_setup_database_integrity_is_ready() is (
        native_current and schema_current
    )
    native.assert_called_once_with(CONTRACT)
    assert shape.call_count == int(native_current)


@pytest.mark.parametrize("catalog", [{}, {"events_eventedition": "a" * 64}])
def test_missing_or_wrong_receipt_shape_catalog_cannot_report_ready(
    monkeypatch, catalog
):
    monkeypatch.setattr(readiness, "PROGRAMME_SETUP_SCHEMA_SHA256", catalog)
    native = MagicMock()
    monkeypatch.setattr(readiness, "database_integrity_contract_is_ready", native)
    assert not readiness.programme_setup_database_integrity_is_ready()
    native.assert_not_called()


@pytest.mark.parametrize(
    "error", [DatabaseError, LookupError, RuntimeError, TypeError, ValueError]
)
def test_receipt_metadata_failure_is_unavailable(monkeypatch, error):
    monkeypatch.setattr(
        readiness, "PROGRAMME_SETUP_SCHEMA_SHA256", {RELATION: "a" * 64}
    )
    monkeypatch.setattr(
        readiness, "database_integrity_contract_is_ready", MagicMock(side_effect=error)
    )
    assert not readiness.programme_setup_database_integrity_is_ready()


@pytest.mark.parametrize("used", [True, False])
@pytest.mark.parametrize(
    "fence",
    [
        SCHEMA.refuse_used_setup_receipt_downgrade,
        FENCE.refuse_used_setup_guard_downgrade,
    ],
)
def test_downgrade_serializes_before_reading_evidence(used, fence):
    events = []
    apps = MagicMock()
    schema_editor = MagicMock()
    schema_editor.execute.side_effect = lambda _sql: events.append("lock")

    def exists():
        events.append("read")
        return used

    apps.get_model.return_value.objects.exists.side_effect = exists
    if used:
        with pytest.raises(RuntimeError, match="retain it and fix forward"):
            fence(apps, schema_editor)
    else:
        fence(apps, schema_editor)
    assert events == ["lock", "read"]
    schema_editor.execute.assert_called_once_with(
        f"LOCK TABLE public.{RELATION} IN ACCESS EXCLUSIVE MODE",
    )
    apps.get_model.assert_called_once_with("events", "ProgrammeAdoptionSetupReceipt")
