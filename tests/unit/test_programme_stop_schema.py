"""Dormant receipt storage and writer scope, not completed stop acceptance."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.events.models import ProgrammeStopReceipt
from maru.events.programme_stop_writer import (
    _programme_stop_writer,
    _require_programme_stop_writer,
)

SCHEMA = import_module("maru.events.migrations.0015_programme_stop_receipt")


def test_stop_receipt_references_preserve_exact_history_without_traversal_rights():
    fields = {
        field.name: field
        for field in ProgrammeStopReceipt._meta.fields
        if field.is_relation
    }
    assert {
        name: field.related_model._meta.label for name, field in fields.items()
    } == {
        "organization": "organizations.Organization",
        "edition": "events.EventEdition",
        "actor": "identity.Account",
        "transition": "events.EditionLifecycleTransition",
        "source_audit": "audit.AuditEvent",
    }
    assert all(
        field.remote_field.on_delete is models.PROTECT for field in fields.values()
    )
    assert all(
        fields[name].unique for name in ("edition", "transition", "source_audit")
    )
    assert (
        "public.events_programmestopreceipt" in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
    )


@pytest.mark.parametrize("operation", ["save", "delete"])
@pytest.mark.parametrize("adding", [True, False])
def test_stop_receipt_refuses_ordinary_orm_writes(operation, adding):
    receipt = ProgrammeStopReceipt()
    receipt._state.adding = adding
    with pytest.raises(ValidationError, match="Programme stop receipts"):
        getattr(receipt, operation)()


def test_writer_scope_allows_only_validated_first_insert(monkeypatch):
    receipt = ProgrammeStopReceipt()
    clean = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(receipt, "full_clean", clean)
    monkeypatch.setattr(models.Model, "save", save)
    with _programme_stop_writer():
        receipt.save(force_insert=True)
    clean.assert_called_once_with()
    save.assert_called_once_with(force_insert=True)
    receipt._state.adding = False
    with _programme_stop_writer(), pytest.raises(ValidationError, match="immutable"):
        receipt.save()
    assert save.call_count == 1


def test_writer_scope_restores_after_nested_exception():
    with pytest.raises(ValidationError):
        _require_programme_stop_writer()
    with _programme_stop_writer():
        _require_programme_stop_writer()
        with pytest.raises(RuntimeError), _programme_stop_writer():
            raise RuntimeError("synthetic exception")
        _require_programme_stop_writer()
    with pytest.raises(ValidationError):
        _require_programme_stop_writer()


def test_validation_does_not_follow_cross_owner_foreign_keys(monkeypatch):
    clean = MagicMock()
    monkeypatch.setattr(models.Model, "full_clean", clean)
    ProgrammeStopReceipt().full_clean(
        exclude=("reason",), validate_unique=False, validate_constraints=False
    )
    clean.assert_called_once_with(
        exclude={
            "reason",
            "organization",
            "edition",
            "actor",
            "transition",
            "source_audit",
        },
        validate_unique=False,
        validate_constraints=False,
    )


@pytest.mark.parametrize("used", [True, False])
def test_used_receipt_reverse_fences_before_schema_or_guard_removal(used):
    events = []
    apps = MagicMock()
    editor = MagicMock()
    editor.execute.side_effect = lambda _sql: events.append("lock")

    def exists():
        events.append("read")
        return used

    apps.get_model.return_value.objects.exists.side_effect = exists
    if used:
        with pytest.raises(RuntimeError, match="retain it and fix forward"):
            SCHEMA.refuse_used_stop_receipt_downgrade(apps, editor)
    else:
        SCHEMA.refuse_used_stop_receipt_downgrade(apps, editor)
    assert events == ["lock", "read"]
    editor.execute.assert_called_once_with(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    apps.get_model.assert_called_once_with("events", "ProgrammeStopReceipt")
    assert (
        SCHEMA.Migration.operations[-1].reverse_code
        is SCHEMA.refuse_used_stop_receipt_downgrade
    )


def test_initial_storage_cannot_admit_a_stop_before_owner_guard_closure():
    assert "BEFORE INSERT OR UPDATE OR DELETE" in SCHEMA.FORWARD_SQL
    assert "require complete native stop admission" in SCHEMA.FORWARD_SQL
    assert "SECURITY DEFINER" not in SCHEMA.FORWARD_SQL
    assert "FROM PUBLIC" in SCHEMA.FORWARD_SQL
