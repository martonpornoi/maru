"""Database-free custody shape, writer, drift and contraction contracts."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.db import migrations, models

from maru.applications import readiness
from maru.applications.models import (
    MAX_PROGRAMME_FILE_INTAKES,
    MAX_PROGRAMME_PROPOSAL_FILE_BYTES,
    ProgrammeFileContent,
    ProgrammeFileIntake,
)
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3,
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)

schema = import_module("maru.applications.migrations.0019_programme_file_custody")
integrity = import_module("maru.applications.migrations.0020_programme_file_integrity")
fence = import_module(
    "maru.applications.migrations.0021_programme_file_downgrade_fence"
)


def test_private_content_is_separate_bounded_and_not_an_ordinary_field():
    intake_fields = {field.name for field in ProgrammeFileIntake._meta.fields}
    assert "payload" not in intake_fields
    assert {
        "proposal",
        "question",
        "actor",
        "source_version",
        "call_version",
        "definition_version",
        "retry_key",
        "scanned_at",
        "file_receipt",
    } <= intake_fields
    assert not {"filename", "url", "path", "quarantine"} & intake_fields
    payload = ProgrammeFileContent._meta.get_field("payload")
    assert isinstance(payload, models.BinaryField)
    assert not payload.editable
    assert payload.max_length == 10 * 1024 * 1024
    assert MAX_PROGRAMME_FILE_INTAKES == 64
    assert MAX_PROGRAMME_PROPOSAL_FILE_BYTES == 64 * 1024 * 1024
    assert {
        constraint.name for constraint in ProgrammeFileIntake._meta.constraints
    } == {
        "app_prg_file_source_uq",
        "app_prg_file_retry_uq",
        "app_prg_file_versions",
    }
    for model in (ProgrammeFileIntake, ProgrammeFileContent):
        for field in model._meta.fields:
            if field.is_relation:
                assert field.remote_field.on_delete is models.PROTECT


@pytest.mark.parametrize("model", [ProgrammeFileIntake, ProgrammeFileContent])
def test_new_file_rows_require_closed_writer_before_any_database_access(model):
    with pytest.raises(ValidationError):
        model().save()


@pytest.mark.parametrize("model", [ProgrammeFileIntake, ProgrammeFileContent])
@pytest.mark.parametrize("operation", ["save", "delete"])
def test_existing_file_custody_is_immutable_before_database_access(model, operation):
    row = model()
    row._state.adding = False
    with pytest.raises(ValidationError):
        getattr(row, operation)()


def test_file_schema_guard_and_fence_form_one_dependency_chain():
    assert len(schema.Migration.operations) == 5
    assert [op.name for op in schema.Migration.operations[:2]] == [
        "ProgrammeFileIntake",
        "ProgrammeFileContent",
    ]
    assert integrity.Migration.atomic
    assert fence.Migration.atomic
    assert integrity.Migration.dependencies == [
        ("applications", "0019_programme_file_custody")
    ]
    assert fence.Migration.dependencies == [
        ("applications", "0020_programme_file_integrity")
    ]
    assert isinstance(integrity.Migration.operations[0], migrations.RunSQL)
    assert integrity.Migration.operations[0].sql == integrity.FORWARD_SQL
    assert integrity.Migration.operations[0].reverse_sql == integrity.REVERSE_SQL
    assert readiness._file_migration_contract_is_current()


def test_file_readiness_includes_all_guards_and_runtime_remains_read_only():
    contract = readiness.APPLICATIONS_INTEGRITY_CONTRACT
    assert contract.source_contract_current
    assert contract.terminal_migration == (
        "applications",
        "0021_programme_file_downgrade_fence",
    )
    assert len(readiness._FILE_TRIGGERS) == 9
    assert len(readiness._FILE_FUNCTIONS) == 5
    assert readiness._FILE_TRIGGERS.items() <= contract.triggers.items()
    assert readiness._FILE_FUNCTIONS.items() <= contract.functions.items()
    for kind in ("intake", "content"):
        assert (
            f"public.applications_programmefile{kind}"
            in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
        )
    for identity, function in readiness._FILE_FUNCTIONS.items():
        assert not function.security_definer
        assert identity not in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3


@pytest.mark.parametrize(
    "fragment",
    [
        "FOR UPDATE OF d, s",
        "maru_workforce_page9_try_scope_mutex",
        "retained_count >= 64",
        "retained_bytes + receipt.size_bytes > 67108864",
        "receipt.size_bytes NOT BETWEEN 1 AND 10485760",
        "NEW.proposal_id",
        "NEW.question_id",
        "receipt.account_id IS DISTINCT FROM NEW.actor_id",
        "source.aggregate_version",
        "source.call_version",
        "source.definition_version",
        "source.condition",
        "condition_value",
        "q.applicant_writable",
        "NOT q.reviewer_visible",
        "owner.retired_at IS NULL",
        "d.status = 'active'",
        "p.state = 'draft'",
        "co.state = 'accepted'",
        "clamav-instream@1",
        "pg_catalog.isfinite(NEW.scanned_at)",
    ],
)
def test_intake_sql_retains_native_purpose_freshness_and_serialized_quota_guards(
    fragment,
):
    assert fragment in integrity.INTAKE_SQL


def test_native_content_and_deferred_evidence_do_not_create_a_parallel_receipt():
    assert "pg_catalog.sha256(NEW.payload)" in integrity.CONTENT_SQL
    assert (
        "pg_catalog.octet_length(NEW.payload) = r.size_bytes" in integrity.CONTENT_SQL
    )
    for fragment in (
        "r.retry_key = NEW.retry_key",
        "r.actor_id = NEW.actor_id",
        "a.question_id = NEW.question_id",
        "r.action = 'proposal_answer_revised'",
        "a.value = pg_catalog.to_jsonb(NEW.file_receipt_id::text)",
        "r.resulting_version = NEW.source_version + 1",
        "applications_programmefilecontent",
    ):
        assert fragment in integrity.EVIDENCE_SQL
    assert "DEFERRABLE INITIALLY DEFERRED" in integrity.TRIGGER_SQL
    assert "review_retry_namespace" not in integrity.FORWARD_SQL
    assert (
        "Programme storage references require exact private custody"
        in integrity.RECEIPT_SQL
    )
    assert "i.actor_id = NEW.actor_id" in integrity.ANSWER_SQL
    assert "i.question_id = NEW.question_id" in integrity.ANSWER_SQL
    assert "p.submission_id = NEW.submission_id" in integrity.ANSWER_SQL
    assert (
        "Unproven Programme files require explicit reconciliation"
        in integrity.PREFLIGHT_SQL
    )


@pytest.mark.parametrize(
    "populated",
    [None, "ProgrammeFileIntake", "ProgrammeFileContent", "ApplicationFileReceipt"],
)
def test_downgrade_locks_first_and_refuses_any_retained_custody(populated):
    events = []

    def get_model(app, name):
        assert app == "applications"
        assert events == ["locked"]
        manager = Mock()
        manager.exists.return_value = name == populated
        manager.filter.return_value = manager
        return SimpleNamespace(objects=manager)

    editor = SimpleNamespace(
        execute=lambda sql: (
            events.append("locked") if "ACCESS EXCLUSIVE MODE" in sql else None
        )
    )
    registry = SimpleNamespace(get_model=get_model)
    if populated:
        with pytest.raises(RuntimeError, match="fix forward"):
            fence.refuse_populated_programme_file_downgrade(registry, editor)
    else:
        fence.refuse_populated_programme_file_downgrade(registry, editor)
    assert events == ["locked"]


def test_readiness_rejects_file_migration_and_fence_source_drift(monkeypatch):
    monkeypatch.setattr(integrity.Migration, "operations", [])
    assert not readiness._file_migration_contract_is_current()
    monkeypatch.undo()
    monkeypatch.setattr(readiness, "_FILE_DOWNGRADE_FENCE_SOURCE_SHA256", "0" * 64)
    assert not readiness._file_migration_contract_is_current()
