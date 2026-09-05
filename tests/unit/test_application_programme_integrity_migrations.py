"""Static contract tests for Applications Programme integrity migrations."""

from __future__ import annotations

import inspect
from importlib import import_module

from django.db import DatabaseError, migrations

import maru.applications.readiness as applications_readiness
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
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.triggers) == 134
    assert len(APPLICATIONS_INTEGRITY_CONTRACT.functions) == 27


def test_schema_fingerprint_covers_the_complete_applications_namespace() -> None:
    """Keep every generic and Programme Applications table fail closed."""
    relations = applications_readiness.APPLICATIONS_RELATION_SEMANTICS

    assert set(relations) == {
        "applications_applicationanswerrevision",
        "applications_applicationcommandreceipt",
        "applications_applicationdefinition",
        "applications_applicationfilereceipt",
        "applications_applicationownerdepartment",
        "applications_applicationquestion",
        "applications_applicationreviewdecision",
        "applications_applicationreviewerperson",
        "applications_applicationreviewerrole",
        "applications_applicationsection",
        "applications_applicationsubmission",
        "applications_applicationtargetrecord",
        "applications_programmecall",
        "applications_programmecallcontributorfield",
        "applications_programmecallformat",
        "applications_programmecalltrack",
        "applications_programmecommandreceipt",
        "applications_programmeimportappliedcommand",
        "applications_programmeimportbatch",
        "applications_programmeimportcommandreceipt",
        "applications_programmeimportitem",
        "applications_programmeimportpreviewitemresult",
        "applications_programmeimportpreviewrevision",
        "applications_programmeimportsourcebinding",
        "applications_programmeproposal",
        "applications_programmeproposalcollaborator",
        "applications_programmeproposalcollaboratortransition",
        "applications_programmeproposalcontributorprofilerevision",
        "applications_programmeproposalrevision",
        "applications_programmeproposalrevisionanswer",
        "applications_programmeproposalrevisioncontributor",
        "applications_programmeproposalrevisionresponse",
        "applications_programmeproposalselectionrevision",
        "applications_programmereviewpolicy",
        "applications_programmereviewcase",
        "applications_programmereviewassignment",
        "applications_programmereviewentry",
        "applications_programmereviewdecision",
        "applications_programmedecisionacknowledgement",
        "applications_programmereviewreceipt",
    }
    assert set(relations.values()) == {("r", "p", False, False, False, "d")}
    assert applications_readiness._applications_relation_names() == tuple(
        sorted(relations)
    )


def test_schema_fingerprint_covers_exact_column_and_collation_semantics() -> None:
    """Keep generic and Programme column metadata inside readiness."""
    columns = applications_readiness._expected_applications_columns()

    assert all(not column[4] for column in columns)
    assert {(column[5], column[6]) for column in columns} == {("", "")}
    assert any(
        column[:7]
        == (
            "applications_applicationanswerrevision",
            "resulting_version",
            "bigint",
            False,
            False,
            "",
            "",
        )
        and column[7:] == applications_readiness._NO_COLLATION_IDENTITY
        for column in columns
    )
    assert any(
        column[:7]
        == (
            "applications_programmecall",
            "content_policy_code",
            "varchar(120)",
            True,
            False,
            "",
            "",
        )
        and column[7:] == applications_readiness._DEFAULT_COLLATION_IDENTITY
        for column in columns
    )
    source = inspect.getsource(applications_readiness._installed_column_rows)
    for catalog_field in (
        "atttypid",
        "atttypmod",
        "attnotnull",
        "atthasdef",
        "attidentity",
        "attgenerated",
        "collprovider",
        "collisdeterministic",
        "collencoding",
        "collcollate",
        "collctype",
        "colllocale",
        "collicurules",
        "collversion",
    ):
        assert catalog_field in source


def test_schema_fingerprint_pins_complete_constraint_and_index_catalogs() -> None:
    """Keep code-owned PostgreSQL 17 object catalogs complete and immutable."""
    assert applications_readiness.APPLICATIONS_SCHEMA_CATALOG_SHA256 == {
        "constraint:": (
            437,
            "d6ad577b25b7ac87592a27fb40169adf32453c96d69010526449f0022dd1b2de",
        ),
        "index:": (
            303,
            "abeb82036b95c051d009bb05a4809e7e868078e0afa0b6f60a014b8e5638fb4d",
        ),
    }
    source = inspect.getsource(applications_readiness._schema_definition_rows)
    for catalog_field in (
        "pg_get_constraintdef",
        "convalidated",
        "confupdtype",
        "confdeltype",
        "confmatchtype",
        "pg_get_indexdef",
        "indisvalid",
        "indisready",
        "indislive",
        "indnkeyatts",
        "indnatts",
    ):
        assert catalog_field in source


def test_complete_schema_object_digest_rejects_missing_extra_and_changed_rows() -> None:
    """Reject any difference anywhere in one complete object kind."""
    rows = {
        "constraint:applications_one:one_check": ("a" * 64, "b" * 64),
        "constraint:applications_two:two_check": ("c" * 64, "d" * 64),
    }
    expected = {
        "constraint:": applications_readiness._schema_object_catalog_sha256(
            rows,
            prefix="constraint:",
        )
    }

    assert applications_readiness._schema_object_rows_are_current(
        rows,
        expected,
        prefix="constraint:",
    )
    assert not applications_readiness._schema_object_rows_are_current(
        {key: value for key, value in rows.items() if key.endswith("one_check")},
        expected,
        prefix="constraint:",
    )
    assert not applications_readiness._schema_object_rows_are_current(
        {
            **rows,
            "constraint:applications_three:unexpected": ("e" * 64, "f" * 64),
        },
        expected,
        prefix="constraint:",
    )
    assert not applications_readiness._schema_object_rows_are_current(
        {
            **rows,
            "constraint:applications_one:one_check": ("a" * 64, "f" * 64),
        },
        expected,
        prefix="constraint:",
    )


def test_applications_readiness_skips_schema_scan_after_generic_failure(
    monkeypatch,
) -> None:
    """Avoid the expensive schema scan when the cheap integrity gate is red."""
    monkeypatch.setattr(
        applications_readiness,
        "database_integrity_contract_is_ready",
        lambda _contract: False,
    )

    def unexpected_catalog_scan() -> None:
        raise AssertionError("schema catalog should not be inspected")

    monkeypatch.setattr(
        applications_readiness,
        "inspect_applications_schema_catalog",
        unexpected_catalog_scan,
    )

    assert not applications_readiness.applications_database_integrity_is_ready()


def test_applications_schema_catalog_error_fails_public_readiness_closed(
    monkeypatch,
) -> None:
    """Keep identifier-free public health unavailable on catalog failure."""
    monkeypatch.setattr(
        applications_readiness,
        "database_integrity_contract_is_ready",
        lambda _contract: True,
    )

    def fail_catalog() -> None:
        raise DatabaseError("private catalog detail")

    monkeypatch.setattr(
        applications_readiness,
        "inspect_applications_schema_catalog",
        fail_catalog,
    )

    assert not applications_readiness.applications_database_integrity_is_ready()


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


def test_legacy_fence_remains_while_0012_is_the_terminal_node() -> None:
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
        "0015_programme_review_downgrade_fence",
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
