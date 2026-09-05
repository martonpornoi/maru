"""Static persistence and migration contracts for Programme imports."""

from __future__ import annotations

import importlib

import pytest
from django.core.exceptions import ValidationError

from maru.applications.models import (
    ProgrammeImportAggregateKind,
    ProgrammeImportAppliedCommand,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportCommandAction,
    ProgrammeImportCommandReceipt,
    ProgrammeImportCommandResultKind,
    ProgrammeImportDependencyState,
    ProgrammeImportItem,
    ProgrammeImportItemKind,
    ProgrammeImportItemState,
    ProgrammeImportPreviewAction,
    ProgrammeImportPreviewItemResult,
    ProgrammeImportPreviewRevision,
    ProgrammeImportPreviewStatus,
    ProgrammeImportSourceBinding,
)
from maru.applications.readiness import (
    APPLICATIONS_INTEGRITY_CONTRACT,
    APPLICATIONS_RELATION_SEMANTICS,
    APPLICATIONS_SCHEMA_CATALOG_SHA256,
)
from maru.authorization.catalog import POLICY_VERSION, ScopeLevel, capability
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3,
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)

_SCHEMA_MIGRATION = importlib.import_module(
    "maru.applications.migrations.0007_programme_import_persistence"
)
_INTEGRITY_MIGRATION = importlib.import_module(
    "maru.applications.migrations.0008_programme_import_integrity_guards"
)
_FENCE_MIGRATION = importlib.import_module(
    "maru.applications.migrations.0009_programme_import_populated_downgrade_fence"
)
_PROGRAMME_INTEGRITY_MIGRATION = importlib.import_module(
    "maru.applications.migrations.0005_programme_integrity_guards"
)
_AUTHORIZATION_MIGRATION = importlib.import_module(
    "maru.authorization.migrations.0022_programme_import_capabilities"
)
_WORKFORCE_MIGRATION = importlib.import_module(
    "maru.workforce.migrations.0017_programme_import_department_fk_contract"
)

_IMPORT_RELATIONS = {
    "public.applications_programmeimportbatch",
    "public.applications_programmeimportitem",
    "public.applications_programmeimportpreviewrevision",
    "public.applications_programmeimportpreviewitemresult",
    "public.applications_programmeimportsourcebinding",
    "public.applications_programmeimportappliedcommand",
    "public.applications_programmeimportcommandreceipt",
}


def test_import_model_and_enum_surface_is_closed() -> None:
    """The accepted seven-model surface and persisted catalogs stay exact."""

    assert {
        model._meta.db_table
        for model in (
            ProgrammeImportBatch,
            ProgrammeImportItem,
            ProgrammeImportPreviewRevision,
            ProgrammeImportPreviewItemResult,
            ProgrammeImportSourceBinding,
            ProgrammeImportAppliedCommand,
            ProgrammeImportCommandReceipt,
        )
    } == {
        "applications_programmeimportbatch",
        "applications_programmeimportitem",
        "applications_programmeimportpreviewrevision",
        "applications_programmeimportpreviewitemresult",
        "applications_programmeimportsourcebinding",
        "applications_programmeimportappliedcommand",
        "applications_programmeimportcommandreceipt",
    }
    assert ProgrammeImportBatchState.values == ["staged", "discarded"]
    assert ProgrammeImportItemKind.values == ["call", "proposal"]
    assert ProgrammeImportItemState.values == ["staged", "applied", "discarded"]
    assert ProgrammeImportPreviewStatus.values == [
        "ready",
        "blocked",
        "no_op",
        "conflict",
    ]
    assert ProgrammeImportPreviewAction.values == [
        "commit_call",
        "claim_proposal",
        "none",
    ]
    assert ProgrammeImportDependencyState.values == [
        "none",
        "missing",
        "draft",
        "active",
        "retired",
    ]
    assert ProgrammeImportAggregateKind.values == ["batch", "preview", "item"]
    assert ProgrammeImportCommandAction.values == [
        "batch_staged",
        "batch_reassigned",
        "batch_previewed",
        "call_committed",
        "proposal_claimed",
        "batch_discarded",
    ]
    assert ProgrammeImportCommandResultKind.values == [
        "batch",
        "preview",
        "call_binding",
        "proposal_binding",
        "discard",
    ]


def test_source_identity_lengths_match_the_wire_contract() -> None:
    """Source-system and source-key columns retain the accepted wire bounds."""

    assert ProgrammeImportBatch._meta.get_field("source_system").max_length == 80
    assert ProgrammeImportItem._meta.get_field("source_key").max_length == 200
    assert (
        ProgrammeImportItem._meta.get_field("dependency_source_system").max_length == 80
    )
    assert (
        ProgrammeImportItem._meta.get_field("dependency_source_key").max_length == 200
    )
    assert (
        ProgrammeImportSourceBinding._meta.get_field("source_system").max_length == 80
    )
    assert ProgrammeImportSourceBinding._meta.get_field("source_key").max_length == 200


@pytest.mark.parametrize(
    ("model", "field_name"),
    [
        (ProgrammeImportItem, "source_key"),
        (ProgrammeImportItem, "dependency_source_key"),
        (ProgrammeImportSourceBinding, "source_key"),
    ],
)
def test_source_keys_enforce_the_closed_ascii_wire_alphabet(
    model: type[object],
    field_name: str,
) -> None:
    """Persisted source identities reject whitespace and private Unicode."""

    field = model._meta.get_field(field_name)  # type: ignore[attr-defined]
    field.clean("source/path:item-1", model())
    with pytest.raises(ValidationError, match="bounded ASCII"):
        field.clean("private key", model())
    with pytest.raises(ValidationError, match="bounded ASCII"):
        field.clean("éxternal", model())


@pytest.mark.parametrize(
    ("safe_field_keys", "reason_codes"),
    [
        (["private_email"], []),
        (["definition", "configuration"], []),
        (["configuration", "configuration"], []),
        ([], ["private_reason"]),
        ([], ["source_digest_conflict", "source_already_applied"]),
        ([], ["source_already_applied", "source_already_applied"]),
    ],
)
def test_preview_metadata_rejects_unknown_duplicate_or_noncanonical_values(
    safe_field_keys: list[str],
    reason_codes: list[str],
) -> None:
    """Retained preview metadata is minimized to ordered public catalogs."""

    result = ProgrammeImportPreviewItemResult(
        safe_field_keys=safe_field_keys,
        reason_codes=reason_codes,
    )
    with pytest.raises(
        ValidationError,
        match="closed ordered value list",
    ):
        result.clean()


def test_preview_metadata_accepts_canonical_catalog_order() -> None:
    """The model accepts only the documented canonical subset ordering."""

    result = ProgrammeImportPreviewItemResult(
        safe_field_keys=["configuration", "answers", "selection"],
        reason_codes=[
            "source_already_applied",
            "call_dependency_unavailable",
            "proposal_mapping_invalid",
        ],
    )

    result.clean()


def test_preview_metadata_fields_admit_empty_canonical_arrays() -> None:
    """Ready/no-op outcomes may legitimately retain no safe keys or reasons."""

    result = ProgrammeImportPreviewItemResult(
        safe_field_keys=[],
        reason_codes=[],
    )

    result._meta.get_field("safe_field_keys").clean([], result)
    result._meta.get_field("reason_codes").clean([], result)
    result.clean()
    assert result._meta.get_field("safe_field_keys").blank
    assert result._meta.get_field("reason_codes").blank


@pytest.mark.parametrize(
    "model",
    [
        ProgrammeImportBatch,
        ProgrammeImportItem,
        ProgrammeImportPreviewRevision,
        ProgrammeImportPreviewItemResult,
        ProgrammeImportSourceBinding,
        ProgrammeImportAppliedCommand,
        ProgrammeImportCommandReceipt,
    ],
)
def test_all_import_models_reject_orm_writes_without_the_dedicated_writer(
    model: type[object],
) -> None:
    """No import relation shares the broader Programme writer latch."""

    with pytest.raises(ValidationError, match="registered command"):
        model().save()  # type: ignore[attr-defined]


def test_import_migration_topology_and_reversal_are_exact() -> None:
    """The additive graph cannot accidentally couple integrity to Workforce 0017."""

    assert tuple(_SCHEMA_MIGRATION.Migration.dependencies) == (
        ("applications", "0006_programme_populated_downgrade_fence"),
    )
    assert tuple(_WORKFORCE_MIGRATION.Migration.dependencies) == (
        ("applications", "0007_programme_import_persistence"),
        ("workforce", "0016_programme_call_department_fk_contract"),
    )
    assert tuple(_AUTHORIZATION_MIGRATION.Migration.dependencies) == (
        ("authorization", "0021_applications_programme_capabilities"),
    )
    assert tuple(_INTEGRITY_MIGRATION.Migration.dependencies) == (
        ("applications", "0007_programme_import_persistence"),
        ("authorization", "0022_programme_import_capabilities"),
    )
    assert ("workforce", "0017_programme_import_department_fk_contract") not in (
        tuple(_INTEGRITY_MIGRATION.Migration.dependencies)
    )
    assert tuple(_FENCE_MIGRATION.Migration.dependencies) == (
        ("applications", "0008_programme_import_integrity_guards"),
    )
    assert _INTEGRITY_MIGRATION.REVERSE_SQL.endswith(
        _PROGRAMME_INTEGRITY_MIGRATION.FORWARD_SQL.strip()
    )


def test_import_database_contract_is_complete_and_owner_only() -> None:
    """Readiness retains old guards and every new review guard and helper."""

    assert APPLICATIONS_INTEGRITY_CONTRACT.source_contract_current
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.triggers) == 134
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.functions) == 27
    assert len(APPLICATIONS_RELATION_SEMANTICS) == 40
    assert APPLICATIONS_SCHEMA_CATALOG_SHA256 == {
        "constraint:": (
            437,
            "d6ad577b25b7ac87592a27fb40169adf32453c96d69010526449f0022dd1b2de",
        ),
        "index:": (
            303,
            "abeb82036b95c051d009bb05a4809e7e868078e0afa0b6f60a014b8e5638fb4d",
        ),
    }
    assert all(
        not function.security_definer
        for function in APPLICATIONS_INTEGRITY_CONTRACT.functions.values()
    )


def test_import_evidence_guard_closes_preview_metadata_catalogs() -> None:
    """The authoritative SQL guard rejects arbitrary or reordered JSON values."""

    assert "NEW.safe_field_keys <> COALESCE" in (
        _INTEGRITY_MIGRATION.IMPORT_EVIDENCE_FUNCTION_SQL
    )
    assert "NEW.reason_codes <> COALESCE" in (
        _INTEGRITY_MIGRATION.IMPORT_EVIDENCE_FUNCTION_SQL
    )
    for value in (
        "configuration",
        "definition",
        "answers",
        "lead_action_required",
        "selection",
        "source_already_applied",
        "source_digest_conflict",
        "definition_code_conflict",
        "call_dependency_unavailable",
        "call_dependency_not_active",
        "proposal_mapping_invalid",
    ):
        assert f"'{value}'" in _INTEGRITY_MIGRATION.IMPORT_EVIDENCE_FUNCTION_SQL


def test_import_truncate_guard_keeps_the_two_factor_test_reset_escape() -> None:
    """Django test flush can truncate only in a test-named database with the GUC."""

    sql = _INTEGRITY_MIGRATION.IMPORT_TRUNCATE_FUNCTION_SQL
    assert "current_database() LIKE 'test\\_%' ESCAPE '\\'" in sql
    assert "'maru.authority_provenance_test_reset', true" in sql
    assert ") = 'on'" in sql
    assert "RETURN NULL;" in sql


def test_nested_proposal_answer_receipt_targets_application_answer_evidence() -> None:
    """Imported answers link to the model written by the nested answer command."""

    sql = _INTEGRITY_MIGRATION.IMPORT_EVIDENCE_FUNCTION_SQL
    assert "FROM public.applications_applicationanswerrevision AS answer" in sql
    assert "proposal.submission_id = answer.submission_id" in sql
    assert "applications_programmeproposalrevisionanswer AS answer" not in sql


def test_import_receipts_bind_each_mutation_to_its_attributed_actor() -> None:
    """Receipt actors and disposal rationale match their owned evidence rows."""

    sql = _INTEGRITY_MIGRATION.IMPORT_RECEIPT_FUNCTION_SQL
    for binding in (
        "NEW.actor_id <> batch_row.staged_by_id",
        "NEW.actor_id <> preview_row.actor_id",
        "NEW.actor_id <> binding_row.created_by_id",
        "NEW.actor_id <> batch_row.discarded_by_id",
        "NEW.reason <> batch_row.discard_reason",
    ):
        assert binding in sql
    assert "OR NEW.reason = ''" in sql


def test_nested_receipts_bind_rationale_and_cover_the_sealed_command_count() -> None:
    """A linked chain must exactly cover its immutable import-time command count."""

    evidence_sql = _INTEGRITY_MIGRATION.IMPORT_EVIDENCE_FUNCTION_SQL
    contract_sql = _INTEGRITY_MIGRATION.IMPORT_CONTRACT_FUNCTION_SQL
    assert "programme_receipt_row.reason <> import_receipt_row.reason" in evidence_sql
    assert "NEW.sequence > import_receipt_row.applied_command_count" in evidence_sql
    assert "SELECT receipt.applied_command_count" in contract_sql
    assert "item_total <> target_version" in contract_sql
    assert "preview_total <> target_version" in contract_sql
    assert ") <> receipt.applied_command_count" in contract_sql
    assert "TG_TABLE_NAME = 'applications_programmeimportappliedcommand'" in (
        contract_sql
    )


def test_import_relations_are_runtime_select_only_without_function_execute() -> None:
    """Dormant schema exposure grants reads but no writes or helper execution."""

    assert set(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS) >= _IMPORT_RELATIONS
    assert not any(
        "programme_import" in identity
        for identity in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3
    )


def test_import_capability_scopes_and_self_field_ceiling_are_exact() -> None:
    """Import authority is Department-bound while disposal is Edition-bound."""

    assert POLICY_VERSION == "2026-09-05.1"
    assert capability("applications.import_programme").maximum_scope is (
        ScopeLevel.DEPARTMENT
    )
    assert capability("applications.dispose_programme_import").maximum_scope is (
        ScopeLevel.EDITION
    )
    assert capability("applications.dispose_programme_import").delegable is True
    recovery = capability("applications.recover_programme_department_ownership")
    assert recovery is not None
    assert recovery.maximum_scope is ScopeLevel.EDITION
    assert recovery.delegable is False
    assert recovery.requires_break_glass is True
    assert (
        "programme_import_claim"
        not in capability("applications.view_self").field_ceiling
    )
    assert (
        "programme_import_claim"
        in capability("applications.view_programme_proposal_self").field_ceiling
    )


def test_department_fk_catalog_names_only_the_batch_owner_reference() -> None:
    """Workforce learns the one new exact Department FK without importing models."""

    assert (
        _WORKFORCE_MIGRATION.FORWARD_SQL.count(
            "'public.applications_programmeimportbatch'::pg_catalog.regclass"
        )
        == 1
    )
    assert "ARRAY['owner_department_id']::text[]" in (_WORKFORCE_MIGRATION.FORWARD_SQL)
