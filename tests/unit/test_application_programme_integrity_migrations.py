"""Static contract tests for Applications Programme integrity migrations."""

from __future__ import annotations

from importlib import import_module

from django.db import migrations

from maru.applications.readiness import APPLICATIONS_INTEGRITY_CONTRACT


def test_0005_is_one_atomic_cross_domain_integrity_step() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )

    assert migration.Migration.atomic
    assert tuple(migration.Migration.dependencies) == (
        ("applications", "0004_programme_calls_and_proposals"),
        ("identity", "0020_programme_proposal_person_guard"),
        ("authorization", "0021_applications_programme_capabilities"),
    )
    assert len(migration.Migration.operations) == 1
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunSQL)
    assert operation.sql == migration.FORWARD_SQL
    assert operation.reverse_sql == migration.REVERSE_SQL
    assert APPLICATIONS_INTEGRITY_CONTRACT.source_contract_current
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.triggers) == 66
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.functions) == 17


def test_shared_retry_lock_and_writer_latch_names_are_exact() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )

    assert migration.FORWARD_SQL.count("maru:applications:retry:") == 2
    assert migration.FORWARD_SQL.count("pg_advisory_xact_lock") == 2
    assert migration.FORWARD_SQL.count("maru.applications_programme_writer") >= 6
    assert "pg_catalog.lower(NEW.edition_id::text)" in migration.FORWARD_SQL
    assert "pg_catalog.lower(NEW.actor_id::text)" in migration.FORWARD_SQL
    assert "pg_catalog.lower(NEW.retry_key::text)" in migration.FORWARD_SQL


def test_0005_reverse_restores_the_exact_legacy_definition_and_acl_contract() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )
    legacy = import_module("maru.applications.migrations.0002_integrity_guards")
    acl = import_module(
        "maru.applications.migrations.0003_integrity_function_execute_boundary"
    )
    expected_suffix = f"{legacy.FORWARD_SQL.strip()}\n\n{acl.FORWARD_SQL.strip()}"

    assert migration.REVERSE_SQL.endswith(expected_suffix)
    assert migration.FORWARD_SQL.count("REVOKE ALL ON FUNCTION") == 13
    assert all(
        len(trigger.name) <= 63
        for trigger in APPLICATIONS_INTEGRITY_CONTRACT.triggers.values()
    )


def test_0006_is_the_populated_downgrade_fence_terminal_node() -> None:
    migration = import_module(
        "maru.applications.migrations.0006_programme_populated_downgrade_fence"
    )

    assert tuple(migration.Migration.dependencies) == (
        ("applications", "0005_programme_integrity_guards"),
    )
    assert len(migration.PROGRAMME_MODEL_NAMES) == 14
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migrations.RunPython.noop
    assert (
        operation.reverse_code is migration.refuse_used_applications_programme_downgrade
    )
    assert APPLICATIONS_INTEGRITY_CONTRACT.terminal_migration == (
        "applications",
        "0006_programme_populated_downgrade_fence",
    )


def test_reopen_and_answer_result_kind_are_frozen_in_schema_sql() -> None:
    schema = import_module(
        "maru.applications.migrations.0004_programme_calls_and_proposals"
    )
    integrity = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )

    assert "answer_revision" in str(schema.Migration.operations)
    assert "proposal_reopened" in integrity.FORWARD_SQL
    assert "OLD.state = 'submitted'" in integrity.FORWARD_SQL
    assert "'submitted', 'draft', 'withdrawn'" in integrity.FORWARD_SQL
    assert "receipt_row.result_kind <> 'answer_revision'" in integrity.FORWARD_SQL


def test_snapshot_semantics_match_canonical_missing_and_contains_rules() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )
    source = migration.PROGRAMME_CONTRACT_FUNCTION_SQL

    assert "COALESCE(" in source
    assert "'null'::jsonb" in source
    assert "pg_catalog.jsonb_typeof" in source
    assert "= 'array'" in source
    assert "WHEN 'string'" not in source
    for missing in ("'\"\"'::jsonb", "'[]'::jsonb", "'{}'::jsonb"):
        assert missing in source


def test_start_and_reopen_use_the_same_inclusive_applicant_edit_window() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )

    assert (
        migration.FORWARD_SQL.count(
            "pg_catalog.transaction_timestamp() < definition_row.opens_at"
        )
        == 3
    )
    assert (
        migration.FORWARD_SQL.count(
            "pg_catalog.transaction_timestamp() >\n"
            "               definition_row.applicant_edit_until"
        )
        >= 1
    )
    assert ">= definition_row.applicant_edit_until" not in migration.FORWARD_SQL
    assert "<= definition_row.opens_at" not in migration.FORWARD_SQL


def test_invitation_expiry_is_capped_by_the_inclusive_applicant_edit_deadline() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )
    current = migration.PROGRAMME_CURRENT_FUNCTION_SQL
    evidence = migration.PROGRAMME_EVIDENCE_FUNCTION_SQL
    comparison = "NEW.invite_expires_at >"

    assert current.count(comparison) == 1
    assert evidence.count(comparison) == 1
    assert "definition.applicant_edit_until" in current
    assert "scope_row.applicant_edit_until" in current
    assert "definition.applicant_edit_until" in evidence
    assert "proposal_row.applicant_edit_until" in evidence
    assert "invite_expires_at >=" not in current
    assert "invite_expires_at >=" not in evidence
    assert "FOR UPDATE OF proposal;" in current
    assert "FOR UPDATE OF submission, collaborator;" in evidence


def test_every_proposal_receipt_action_has_exact_result_and_target_proof() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )
    source = migration.PROGRAMME_CONTRACT_FUNCTION_SQL

    for action in (
        "proposal_started",
        "proposal_selection_revised",
        "proposal_answer_revised",
        "collaborator_invited",
        "collaborator_accepted",
        "collaborator_declined",
        "collaborator_left",
        "collaborator_removed",
        "collaborator_reinvited",
        "contributor_profile_revised",
        "proposal_sealed",
        "revision_acknowledged",
        "revision_declined",
        "proposal_reopened",
        "proposal_submitted",
        "proposal_withdrawn",
    ):
        assert action in source
    for result_kind in (
        "proposal",
        "selection_revision",
        "answer_revision",
        "collaborator_transition",
        "profile_revision",
        "proposal_revision",
        "revision_response",
    ):
        assert f"receipt_row.result_kind <> '{result_kind}'" in source
    assert source.count("receipt_row.target_id") >= 10


def test_programme_question_graph_is_closed_at_activation_and_answer_write() -> None:
    migration = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )
    definition = migration.DEFINITION_FUNCTION_SQL
    answer = migration.ANSWER_FUNCTION_SQL

    for fragment in (
        "NOT BETWEEN 1 AND 100",
        "NOT BETWEEN 1 AND 500",
        "question graph shape is invalid",
        "jsonb_array_elements",
        "COUNT(DISTINCT option->>'code')",
        "question.maximum_choices",
        "question.reference_kind",
        "question.source_binding = ''",
        "NOT question.staff_visible",
        "NOT question.reviewer_visible",
        "NOT question.api_projection",
        "active Programme condition graph is invalid",
    ):
        assert fragment in definition
    for forbidden_source in (
        "'decimal'",
        "'date'",
        "'time'",
        "'instant'",
        "'person_reference'",
        "'domain_reference'",
        "'safe_file'",
    ):
        condition_catalog = definition.split("WHEN source.field_type IN (", maxsplit=1)[
            1
        ].split(") THEN", maxsplit=1)[0]
        assert forbidden_source not in condition_catalog
    for fragment in (
        "question_row.source_binding <> ''",
        "question_row.staff_visible",
        "question_row.staff_writable",
        "question_row.reviewer_visible",
        "question_row.public_after_approval",
        "question_row.api_projection",
    ):
        assert fragment in answer
