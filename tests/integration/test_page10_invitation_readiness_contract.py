"""Exact PostgreSQL evidence for Page 10's additive invitation catalog."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from psycopg import sql

from maru.identity import invitation_readiness

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _expected_trigger_rows() -> dict[str, tuple[object, ...]]:
    return {
        name: (
            contract.table,
            contract.function,
            contract.trigger_type,
            "O",
            contract.deferrable,
            contract.initially_deferred,
            contract.when_sha256,
            0,
            contract.columns,
        )
        for name, contract in invitation_readiness._TRIGGER_CONTRACTS.items()
    }


def test_page10_additive_catalog_is_installed_but_cutover_is_inactive() -> None:
    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    report = invitation_readiness.build_platform_invitation_readiness_report()

    assert catalog.additive_contract_ready
    assert catalog.reconciliation_migration_applied
    assert catalog.reconciliation_relations_installed
    assert catalog.digest_key_migration_applied
    assert catalog.digest_key_column_installed
    assert catalog.hardened_integrity_migration_applied
    assert catalog.audit_cardinality_migration_applied
    assert catalog.scheduler_heartbeat_migration_applied
    assert catalog.scheduler_heartbeat_relation_installed
    assert catalog.prefix_index_migration_applied
    assert catalog.retention_audit_cardinality_migration_applied
    assert catalog.retention_workflow_migration_applied
    assert catalog.retention_relations_installed
    assert len(invitation_readiness._FUNCTION_DEFINITION_SHA256) == 50
    assert len(invitation_readiness._TRIGGER_CONTRACTS) == 75
    assert len(invitation_readiness._INDEX_CONTRACTS) == 16
    assert report["status"] == "ready"
    assert report["production_status"] == "blocked"
    assert report["writer_cutover_status"] == "inactive"
    assert report["schema_generation"] == "page10-invitations-additive-v10"
    assert report["additive_gates"]["digest_key_schema_migration"] == "resolved"
    assert report["additive_gates"]["digest_key_column"] == "resolved"
    assert report["additive_gates"]["hardened_integrity_migration"] == "resolved"
    assert (
        report["additive_gates"]["reconciliation_audit_cardinality_migration"]
        == "resolved"
    )
    assert report["additive_gates"]["scheduler_heartbeat_migration"] == "resolved"
    assert report["additive_gates"]["scheduler_heartbeat_relation"] == "resolved"
    assert report["additive_gates"]["prefix_index_migration"] == "resolved"
    assert (
        report["additive_gates"]["retention_audit_cardinality_migration"] == "resolved"
    )
    assert report["additive_gates"]["retention_workflow_migration"] == "resolved"
    assert report["additive_gates"]["retention_relations"] == "resolved"
    assert catalog.uncataloged_function_identities == ()
    assert catalog.uncataloged_trigger_names == ()
    assert invitation_readiness.PAGE10_INVITATION_STOPPED_WRITER_GENERATION is None
    assert report["known_production_gates"]["stopped_writer_generation"] == (
        "unresolved"
    )
    assert (
        report["known_production_gates"]["account_prefix_search_query_plan"]
        == "resolved"
    )
    assert (
        report["known_production_gates"]["live_token_digest_key_coverage"]
        == "unresolved"
    )
    assert report["known_production_gates"]["expiry_scheduler_heartbeat"] == (
        "unresolved"
    )
    assert (
        report["known_production_gates"]["invitation_retention_policy_and_job"]
        == "unresolved"
    )
    assert not invitation_readiness.platform_invitation_runtime_contract_is_ready()


def test_page10_readiness_command_is_data_free_and_fails_production_closed() -> None:
    output = StringIO()

    call_command("check_platform_invitation_readiness", "--no-fail", stdout=output)

    report = json.loads(output.getvalue())
    assert report["status"] == "ready"
    assert report["production_status"] == "blocked"
    assert set(report) == {
        "additive_gates",
        "integrity_review_scope",
        "known_production_gates",
        "production_status",
        "schema_generation",
        "status",
        "writer_cutover_status",
    }
    rendered = output.getvalue().casefold()
    assert "email" not in rendered
    assert "account_id" not in rendered
    assert "invitation_id" not in rendered

    with pytest.raises(CommandError, match="production readiness is blocked"):
        call_command("check_platform_invitation_readiness", stdout=StringIO())


def test_page10_declared_trigger_contract_matches_the_fresh_catalog() -> None:
    names = list(invitation_readiness._TRIGGER_CONTRACTS)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure.proname || '(' ||
                       pg_catalog.pg_get_function_identity_arguments(procedure.oid) ||
                       ')',
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   CASE WHEN trigger.tgqual IS NULL THEN NULL ELSE
                       pg_catalog.encode(
                           pg_catalog.sha256(
                               pg_catalog.convert_to(trigger.tgqual::text, 'UTF8')
                           ),
                           'hex'
                       )
                   END,
                   trigger.tgnargs,
                   ARRAY(
                       SELECT attribute.attname::text
                         FROM pg_catalog.unnest(trigger.tgattr::smallint[])
                              WITH ORDINALITY AS selected(attnum, position)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = trigger.tgrelid
                          AND attribute.attnum = selected.attnum
                        ORDER BY selected.position
                   )
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = trigger.tgfoid
             WHERE NOT trigger.tgisinternal
               AND trigger.tgname = ANY(%s::text[])
             ORDER BY trigger.tgname
            """,
            [names],
        )
        rows = cursor.fetchall()
    assert {str(row[0]): (*tuple(row[1:9]), tuple(row[9] or ())) for row in rows} == (
        _expected_trigger_rows()
    )


@pytest.mark.parametrize(
    "identity",
    tuple(invitation_readiness._FUNCTION_DEFINITION_SHA256),
)
def test_each_page10_function_tamper_blocks_additive_readiness(identity: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER FUNCTION public.")
            + sql.SQL(identity)
            + sql.SQL(" SECURITY INVOKER")
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.functions_fingerprinted
    assert not catalog.additive_contract_ready


@pytest.mark.parametrize(
    ("trigger_name", "contract"),
    tuple(invitation_readiness._TRIGGER_CONTRACTS.items()),
)
def test_each_page10_disabled_trigger_blocks_additive_readiness(
    trigger_name: str,
    contract: invitation_readiness._TriggerContract,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(
                sql.Identifier(contract.table),
                sql.Identifier(trigger_name),
            )
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.triggers_attached
    assert not catalog.additive_contract_ready


@pytest.mark.parametrize(
    ("index_name", "contract"),
    tuple(invitation_readiness._INDEX_CONTRACTS.items()),
)
def test_each_page10_supporting_index_tamper_blocks_additive_readiness(
    index_name: str,
    contract: invitation_readiness._IndexContract,
) -> None:
    with connection.cursor() as cursor:
        if contract.constraint_backed:
            cursor.execute(
                sql.SQL("ALTER TABLE public.{} DROP CONSTRAINT {}").format(
                    sql.Identifier(contract.table),
                    sql.Identifier(index_name),
                )
            )
        else:
            cursor.execute(
                sql.SQL("DROP INDEX public.{}").format(sql.Identifier(index_name))
            )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_prefix_index_operator_class_tamper_blocks_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX public.id_account_email_prefix_idx")
        cursor.execute(
            """
            CREATE INDEX id_account_email_prefix_idx
                ON public.identity_account ((upper(email)))
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_scheduler_index_order_tamper_blocks_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX public.id_inv_scheduler_run_idx")
        cursor.execute(
            """
            CREATE INDEX id_inv_scheduler_run_idx
                ON public.identity_platforminvitationschedulerrun
                   (kind, ran_at, id)
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_receipt_bare_unique_index_does_not_fake_constraint() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE public.identity_platformaccountinvitationcommandreceipt
            DROP CONSTRAINT identity_invitation_result_receipt_unique
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX identity_invitation_result_receipt_unique
                ON public.identity_platformaccountinvitationcommandreceipt
                   (invitation_id, result_version)
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_deferred_receipt_constraint_does_not_fake_exact_contract() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE public.identity_platformaccountinvitationcommandreceipt
            DROP CONSTRAINT identity_invitation_result_receipt_unique
            """
        )
        cursor.execute(
            """
            ALTER TABLE public.identity_platformaccountinvitationcommandreceipt
            ADD CONSTRAINT identity_invitation_result_receipt_unique
            UNIQUE (invitation_id, result_version)
            DEFERRABLE INITIALLY DEFERRED
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_audit_index_predicate_tamper_blocks_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX public.audit_identity_reconcile_retry_unique")
        cursor.execute(
            """
            CREATE UNIQUE INDEX audit_identity_reconcile_retry_unique
                ON public.audit_auditevent
                   (principal_id, idempotency_key_hash)
             WHERE capability_code =
                   'identity.reconcile_account_invitation_delivery'
               AND idempotency_key_hash <> ''
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.indexes_installed
    assert not catalog.additive_contract_ready


def test_page10_function_execute_acl_tamper_blocks_additive_readiness() -> None:
    identity = next(iter(invitation_readiness._FUNCTION_DEFINITION_SHA256))
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION public.")
            + sql.SQL(identity)
            + sql.SQL(" TO PUBLIC")
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.function_execute_boundary_closed
    assert not catalog.additive_contract_ready


def test_page10_unreviewed_function_is_reported_outside_the_reviewed_catalog() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE FUNCTION public.identity_page10_unreviewed() RETURNS void
            LANGUAGE sql AS 'SELECT NULL::void'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    report = invitation_readiness.build_platform_invitation_readiness_report()

    assert catalog.functions_fingerprinted
    assert catalog.additive_contract_ready
    assert "identity_page10_unreviewed()" in (catalog.uncataloged_function_identities)
    assert (
        "identity_page10_unreviewed()"
        in report["integrity_review_scope"]["uncataloged_later_generation_functions"]
    )


def test_page10_update_column_tamper_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DROP TRIGGER identity_page10_account_complete
                ON public.identity_account;
            CREATE CONSTRAINT TRIGGER identity_page10_account_complete
            AFTER UPDATE OF email ON public.identity_account
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.identity_page10_account_complete();
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.triggers_attached
    assert not catalog.additive_contract_ready


def test_page10_constraint_timing_tamper_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DROP TRIGGER identity_page10_invitation_complete
                ON public.identity_platformaccountinvitation;
            CREATE CONSTRAINT TRIGGER identity_page10_invitation_complete
            AFTER INSERT OR UPDATE ON public.identity_platformaccountinvitation
            DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW
            EXECUTE FUNCTION public.identity_page10_invitation_complete();
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.triggers_attached
    assert not catalog.additive_contract_ready


def test_missing_page10_migration_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'identity'
               AND name = '0011_platform_account_invitations'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.migration_applied
    assert not catalog.additive_contract_ready


def test_missing_reconciliation_migration_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'identity'
               AND name = '0012_invitation_delivery_reconciliation'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.reconciliation_migration_applied
    assert not catalog.additive_contract_ready


def test_missing_hardened_integrity_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'identity'
               AND name = '0014_invitation_delivery_integrity'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.hardened_integrity_migration_applied
    assert not catalog.additive_contract_ready


def test_missing_audit_cardinality_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'audit'
               AND name = '0007_identity_reconciliation_audit_uniqueness'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()

    assert not catalog.audit_cardinality_migration_applied
    assert not catalog.additive_contract_ready


def test_missing_scheduler_heartbeat_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'identity'
               AND name = '0015_platform_invitation_scheduler_runs'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.scheduler_heartbeat_migration_applied
    assert not catalog.additive_contract_ready


def test_missing_prefix_index_recorder_blocks_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'identity'
               AND name = '0016_account_inventory_prefix_indexes'
            """
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.prefix_index_migration_applied
    assert not catalog.additive_contract_ready


def test_missing_retention_recorders_block_additive_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM public.django_migrations WHERE "
            "(app = 'audit' AND name = "
            "'0008_identity_retention_audit_uniqueness') OR "
            "(app = 'identity' AND name = "
            "'0018_invitation_retention_v8')"
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.retention_audit_cardinality_migration_applied
    assert not catalog.retention_workflow_migration_applied
    assert not catalog.additive_contract_ready


@pytest.mark.parametrize(
    "relation",
    invitation_readiness._RECONCILIATION_RELATIONS,
)
def test_missing_reconciliation_relation_blocks_additive_readiness(
    relation: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP TABLE public.{}").format(sql.Identifier(relation)))

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.reconciliation_relations_installed
    assert not catalog.additive_contract_ready


@pytest.mark.parametrize("relation", invitation_readiness._RETENTION_RELATIONS)
def test_missing_retention_relation_blocks_additive_readiness(relation: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("DROP TABLE public.{} CASCADE").format(sql.Identifier(relation))
        )

    catalog = invitation_readiness.inspect_platform_invitation_additive_catalog()
    assert not catalog.retention_relations_installed
    assert not catalog.additive_contract_ready
