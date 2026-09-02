"""PostgreSQL reversal and fix-forward coverage for Programme imports."""

from __future__ import annotations

from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython, RunSQL
from django.utils import timezone

from tests.factories import (
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

APPLICATIONS_BEFORE = (
    "applications",
    "0006_programme_populated_downgrade_fence",
)
APPLICATIONS_SCHEMA = (
    "applications",
    "0007_programme_import_persistence",
)
APPLICATIONS_GUARDS = (
    "applications",
    "0008_programme_import_integrity_guards",
)
APPLICATIONS_AFTER = (
    "applications",
    "0009_programme_import_populated_downgrade_fence",
)
AUTHORIZATION_BEFORE = (
    "authorization",
    "0021_applications_programme_capabilities",
)
AUTHORIZATION_AFTER = (
    "authorization",
    "0022_programme_import_capabilities",
)
WORKFORCE_BEFORE = (
    "workforce",
    "0016_programme_call_department_fk_contract",
)
WORKFORCE_AFTER = (
    "workforce",
    "0017_programme_import_department_fk_contract",
)
IMPORT_CAPABILITIES = (
    "applications.import_programme",
    "applications.dispose_programme_import",
)
IMPORT_RELATIONS = (
    "applications_programmeimportbatch",
    "applications_programmeimportitem",
    "applications_programmeimportpreviewrevision",
    "applications_programmeimportpreviewitemresult",
    "applications_programmeimportsourcebinding",
    "applications_programmeimportappliedcommand",
    "applications_programmeimportcommandreceipt",
)
IMPORT_MODELS = (
    "ProgrammeImportBatch",
    "ProgrammeImportItem",
    "ProgrammeImportPreviewRevision",
    "ProgrammeImportPreviewItemResult",
    "ProgrammeImportSourceBinding",
    "ProgrammeImportAppliedCommand",
    "ProgrammeImportCommandReceipt",
)
IMPORT_FUNCTIONS = (
    "maru_applications_guard_programme_import_current",
    "maru_applications_guard_programme_import_evidence",
    "maru_applications_guard_programme_import_receipt",
    "maru_applications_validate_programme_import_contract",
    "maru_applications_refuse_programme_import_truncate",
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _migration_is_applied(target: tuple[str, str]) -> bool:
    return target in MigrationExecutor(connection).loader.applied_migrations


def _relation_presence() -> dict[str, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation_name,
                   pg_catalog.to_regclass('public.' || relation_name) IS NOT NULL
              FROM unnest(%s::text[]) AS relation_name
            """,
            [list(IMPORT_RELATIONS)],
        )
        rows = cursor.fetchall()
    return {str(name): bool(installed) for name, installed in rows}


def _function_presence() -> dict[str, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT function_name,
                   pg_catalog.to_regprocedure(
                       'public.' || function_name || '()'
                   ) IS NOT NULL
              FROM unnest(%s::text[]) AS function_name
            """,
            [list(IMPORT_FUNCTIONS)],
        )
        rows = cursor.fetchall()
    return {str(name): bool(installed) for name, installed in rows}


def _import_trigger_count() -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND trigger.tgname LIKE 'applications_prg_imp_%'
               AND NOT trigger.tgisinternal
            """
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _minimum_scope(capability_code: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authorization_capability_min_scope(%s)",
            [capability_code],
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _workforce_contract_state() -> tuple[str, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.prosrc,
                   public.maru_workforce_department_fk_contract_is_current()
              FROM pg_catalog.pg_proc AS procedure
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND procedure.oid = pg_catalog.to_regprocedure(
                   'public.maru_workforce_department_fk_contract_is_current()'
               )
            """
        )
        row = cursor.fetchone()
    assert row is not None
    return str(row[0]), bool(row[1])


def _retained_row_counts() -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM applications_programmeimportbatch),
                (SELECT count(*) FROM applications_programmeimportitem),
                (SELECT count(*) FROM applications_programmeimportpreviewrevision),
                (SELECT count(*) FROM applications_programmeimportpreviewitemresult),
                (SELECT count(*) FROM applications_programmeimportsourcebinding),
                (SELECT count(*) FROM applications_programmeimportappliedcommand),
                (SELECT count(*) FROM applications_programmeimportcommandreceipt)
            """
        )
        row = cursor.fetchone()
    assert row is not None
    return {
        relation: int(count)
        for relation, count in zip(IMPORT_RELATIONS, row, strict=True)
    }


def _retained_row_count(relation: str) -> int:
    assert relation in IMPORT_RELATIONS
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM public.{relation}"  # noqa: S608
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _insert_isolated_retained_row(relation: str) -> None:
    """Insert one check-valid row while bypassing unrelated foreign-key graphs.

    The migration fence must reject every physically retained relation even if
    a damaged restore has lost its referenced rows. PostgreSQL foreign keys are
    trigger-backed, so the migration-owner test connection temporarily enters
    replica mode for this adversarial setup only. Static check constraints
    remain authoritative.
    """

    assert relation in IMPORT_RELATIONS
    now = timezone.now()
    identifiers = [uuid4() for _index in range(10)]
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        if relation == "applications_programmeimportbatch":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportbatch (
                    id, created_at, updated_at, source_system, schema_version,
                    source_digest, item_count, retention_policy_code,
                    expires_at, state, aggregate_version, discarded_at,
                    discard_reason, discarded_by_id, edition_id,
                    organization_id, owner_department_id, staged_by_id
                ) VALUES (
                    %s, %s, %s, 'legacy.programme.migration', 1, %s, 1,
                    'applications.programme-import-staging.test-v1', %s,
                    'discarded', 2, %s, 'Retain discarded batch evidence.',
                    %s, %s, %s, %s, %s
                )
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    "1" * 64,
                    now + timedelta(days=1),
                    now,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                    identifiers[5],
                ],
            )
        elif relation == "applications_programmeimportitem":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportitem (
                    id, created_at, updated_at, sequence, kind, source_key,
                    source_digest, canonical_payload, payload_size_bytes,
                    dependency_source_system, dependency_source_key, state,
                    aggregate_version, batch_id, edition_id, organization_id
                ) VALUES (
                    %s, %s, %s, 1, 'call', 'discarded-call', %s, NULL, 10,
                    '', '', 'discarded', 2, %s, %s, %s
                )
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    "2" * 64,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                ],
            )
        elif relation == "applications_programmeimportpreviewrevision":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportpreviewrevision (
                    id, created_at, updated_at, revision_number,
                    source_batch_version, preview_digest, item_count, actor_id,
                    batch_id, edition_id, organization_id
                ) VALUES (%s, %s, %s, 1, 1, %s, 1, %s, %s, %s, %s)
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    "3" * 64,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                ],
            )
        elif relation == "applications_programmeimportpreviewitemresult":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportpreviewitemresult (
                    id, created_at, updated_at, item_version, status, action,
                    dependency_state, dependency_digest, dependency_version,
                    safe_field_keys, reason_codes, result_digest, edition_id,
                    item_id, organization_id, preview_id
                ) VALUES (
                    %s, %s, %s, 1, 'blocked', 'none', 'none', '', NULL,
                    '[]'::jsonb, '[]'::jsonb, %s, %s, %s, %s, %s
                )
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    "4" * 64,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                ],
            )
        elif relation == "applications_programmeimportsourcebinding":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportsourcebinding (
                    id, created_at, updated_at, source_system, kind, source_key,
                    source_digest, call_id, created_by_id, edition_id, item_id,
                    organization_id, proposal_id
                ) VALUES (
                    %s, %s, %s, 'legacy.programme.migration', 'call',
                    'bound-call', %s, %s, %s, %s, %s, %s, NULL
                )
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    "5" * 64,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                    identifiers[5],
                ],
            )
        elif relation == "applications_programmeimportappliedcommand":
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportappliedcommand (
                    id, created_at, updated_at, sequence, binding_id,
                    edition_id, import_receipt_id, organization_id,
                    programme_receipt_id
                ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s)
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    identifiers[1],
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                    identifiers[5],
                ],
            )
        else:
            cursor.execute(
                """
                INSERT INTO public.applications_programmeimportcommandreceipt (
                    id, created_at, updated_at, aggregate_kind, action,
                    retry_key, request_digest, reason, correlation_id,
                    source_channel, adopted_preview_digest, result_kind,
                    expected_version, resulting_version,
                    applied_command_count, actor_id, batch_id, edition_id,
                    item_id, organization_id, preview_item_result_id,
                    preview_revision_id, source_binding_id
                ) VALUES (
                    %s, %s, %s, 'batch', 'batch_staged', %s, %s,
                    'Retain receipt-only import evidence.', %s, 'test', '',
                    'batch', 0, 1, 0, %s, %s, %s, NULL, %s, NULL, NULL, NULL
                )
                """,
                [
                    identifiers[0],
                    now,
                    now,
                    identifiers[1],
                    "6" * 64,
                    identifiers[2],
                    identifiers[3],
                    identifiers[4],
                    identifiers[5],
                    identifiers[6],
                ],
            )


def _delete_isolated_retained_row(relation: str) -> None:
    assert relation in IMPORT_RELATIONS
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(
            f"DELETE FROM public.{relation}"  # noqa: S608
        )


def test_import_graph_and_fences_cover_the_exact_seven_relations() -> None:
    """Pin dependency order and both independent downgrade preflights."""

    persistence = import_module(
        "maru.applications.migrations.0007_programme_import_persistence"
    )
    guards = import_module(
        "maru.applications.migrations.0008_programme_import_integrity_guards"
    )
    fence = import_module(
        "maru.applications.migrations.0009_programme_import_populated_downgrade_fence"
    )
    authority = import_module(
        "maru.authorization.migrations.0022_programme_import_capabilities"
    )
    workforce = import_module(
        "maru.workforce.migrations.0017_programme_import_department_fk_contract"
    )

    assert persistence.Migration.dependencies == [APPLICATIONS_BEFORE]
    assert guards.Migration.dependencies == [APPLICATIONS_SCHEMA, AUTHORIZATION_AFTER]
    assert fence.Migration.dependencies == [APPLICATIONS_GUARDS]
    assert authority.Migration.dependencies == [AUTHORIZATION_BEFORE]
    assert workforce.Migration.dependencies == [APPLICATIONS_SCHEMA, WORKFORCE_BEFORE]
    assert tuple(fence.PROGRAMME_IMPORT_MODEL_NAMES) == IMPORT_MODELS
    assert isinstance(persistence.Migration.operations[-1], RunSQL)
    assert isinstance(fence.Migration.operations[0], RunPython)
    assert isinstance(authority.Migration.operations[0], RunSQL)
    assert isinstance(authority.Migration.operations[1], RunPython)
    for relation in IMPORT_RELATIONS:
        assert relation in persistence.REVERSE_PREFLIGHT_SQL


def test_empty_slice_reverses_and_reapplies_with_dependent_contracts() -> None:
    """Rehearse an unused additive slice from predecessors to current leaves."""

    _migrate(APPLICATIONS_BEFORE, AUTHORIZATION_BEFORE, WORKFORCE_BEFORE)

    assert not any(_relation_presence().values())
    assert not any(_function_presence().values())
    assert _import_trigger_count() == 0
    assert all(_minimum_scope(code) == -1 for code in IMPORT_CAPABILITIES)
    reverse_source, reverse_is_current = _workforce_contract_state()
    assert "applications_programmeimportbatch" not in reverse_source
    assert reverse_is_current

    _migrate(AUTHORIZATION_AFTER, APPLICATIONS_AFTER, WORKFORCE_AFTER)

    assert all(_relation_presence().values())
    assert all(_function_presence().values())
    assert _import_trigger_count() == 21
    assert _minimum_scope("applications.import_programme") == 2
    assert _minimum_scope("applications.dispose_programme_import") == 1
    forward_source, forward_is_current = _workforce_contract_state()
    assert "applications_programmeimportbatch" in forward_source
    assert forward_is_current


def test_each_populated_relation_independently_blocks_terminal_downgrade() -> None:
    """Exercise all seven fences, including scrubbed and discarded evidence."""

    _migrate(APPLICATIONS_SCHEMA)
    assert all(count == 0 for count in _retained_row_counts().values())

    for relation in IMPORT_RELATIONS:
        _insert_isolated_retained_row(relation)
        assert _retained_row_count(relation) == 1, relation
        _migrate(APPLICATIONS_AFTER)

        with pytest.raises(
            RuntimeError,
            match="Cannot remove Programme-import database integrity",
        ):
            _migrate(APPLICATIONS_GUARDS)

        assert _migration_is_applied(APPLICATIONS_AFTER), relation
        assert all(_function_presence().values()), relation
        assert _retained_row_count(relation) == 1, relation
        _delete_isolated_retained_row(relation)
        assert _retained_row_count(relation) == 0, relation
        _migrate(APPLICATIONS_SCHEMA)

    _migrate(APPLICATIONS_AFTER)


def test_populated_schema_preflight_refuses_after_guard_reversal() -> None:
    """Keep a payload-cleared item when the lower schema fence is reached."""

    _migrate(APPLICATIONS_SCHEMA)
    relation = "applications_programmeimportitem"
    _insert_isolated_retained_row(relation)
    assert _retained_row_count(relation) == 1

    with pytest.raises(
        DatabaseError,
        match="Cannot remove Applications Programme-import schema",
    ):
        _migrate(APPLICATIONS_BEFORE, WORKFORCE_BEFORE)

    assert _migration_is_applied(APPLICATIONS_SCHEMA)
    assert not _migration_is_applied(APPLICATIONS_GUARDS)
    assert not _migration_is_applied(APPLICATIONS_AFTER)
    assert all(_relation_presence().values())
    assert not any(_function_presence().values())
    assert _retained_row_count(relation) == 1


@pytest.mark.parametrize(
    "evidence_factory",
    [
        pytest.param("grant", id="direct-grant"),
        pytest.param("role", id="role-bundle"),
    ],
)
def test_capability_contraction_refuses_retained_authority(
    evidence_factory: str,
) -> None:
    """Preserve the scope catalog for direct and reusable authority evidence."""

    if evidence_factory == "grant":
        edition = EventEditionFactory()
        department = create_department_for_test(
            edition=edition,
            name="Programme",
            expected_code="programme",
        )
        evidence = CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            department=department,
            capability_code="applications.import_programme",
        )
        relation = "authorization_capabilitygrant"
    else:
        evidence = RoleBundleFactory(capability_codes=list(IMPORT_CAPABILITIES))
        relation = "authorization_rolebundle"

    with pytest.raises(
        RuntimeError,
        match="Cannot remove Programme-import authority",
    ):
        _migrate(AUTHORIZATION_BEFORE)

    assert _migration_is_applied(AUTHORIZATION_AFTER)
    assert _minimum_scope("applications.import_programme") == 2
    assert _minimum_scope("applications.dispose_programme_import") == 1
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM public.{relation} WHERE id = %s",  # noqa: S608
            [evidence.id],
        )
        assert cursor.fetchone() == (1,)


def test_workforce_contract_reverses_fail_closed_and_reapplies_exactly() -> None:
    """Remove and restore only the import batch Department dependency."""

    _migrate(WORKFORCE_BEFORE)
    reverse_source, reverse_is_current = _workforce_contract_state()
    assert "applications_programmeimportbatch" not in reverse_source
    assert "applications_programmecall" in reverse_source
    assert not reverse_is_current

    _migrate(WORKFORCE_AFTER)
    forward_source, forward_is_current = _workforce_contract_state()
    assert "applications_programmeimportbatch" in forward_source
    assert "applications_programmecall" in forward_source
    assert forward_is_current
