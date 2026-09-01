"""Exact PostgreSQL readiness evidence for the Page 9 write boundary."""

from __future__ import annotations

from collections import Counter
from typing import cast

import pytest
from django.db import connection
from psycopg import sql

from maru.authorization import provenance_readiness

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _trigger(
    table: str,
    function: str,
    trigger_type: int,
    *,
    columns: tuple[str, ...] = (),
    deferrable: bool = False,
    initially_deferred: bool = False,
    definition: str | None = None,
) -> tuple[object, ...]:
    return (
        table,
        function,
        trigger_type,
        "O",
        deferrable,
        initially_deferred,
        definition is None,
        0,
        columns,
        definition,
    )


PAGE9_TRIGGER_CONTRACTS = {
    "aa_workforce_page9_department_barrier": _trigger(
        "workforce_department",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_control_barrier": _trigger(
        "workforce_editionstructurecontrol",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_receipt_barrier": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_position_barrier": _trigger(
        "workforce_position",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_assignment_barrier": _trigger(
        "workforce_positionassignment",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_binding_barrier": _trigger(
        "authorization_scopedresourcebinding",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_capability_barrier": _trigger(
        "authorization_capabilitygrant",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "aa_workforce_page9_role_barrier": _trigger(
        "authorization_roleassignment",
        "maru_workforce_page9_writer_barrier()",
        62,
    ),
    "ab_workforce_page9_department_scope": _trigger(
        "workforce_department",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_control_scope": _trigger(
        "workforce_editionstructurecontrol",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_receipt_scope": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_position_scope": _trigger(
        "workforce_position",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_assignment_scope": _trigger(
        "workforce_positionassignment",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_binding_scope": _trigger(
        "authorization_scopedresourcebinding",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_capability_scope": _trigger(
        "authorization_capabilitygrant",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ab_workforce_page9_role_scope": _trigger(
        "authorization_roleassignment",
        "maru_workforce_page9_scope_mutex()",
        31,
    ),
    "ac_workforce_page9_control_guard": _trigger(
        "workforce_editionstructurecontrol",
        "maru_validate_edition_structure_control()",
        23,
    ),
    "ac_workforce_page9_control_no_delete": _trigger(
        "workforce_editionstructurecontrol",
        "maru_prevent_edition_structure_control_mutation()",
        11,
    ),
    "ac_workforce_page9_control_no_truncate": _trigger(
        "workforce_editionstructurecontrol",
        "maru_prevent_edition_structure_control_mutation()",
        34,
    ),
    "ac_workforce_page9_receipt_guard": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_validate_edition_structure_receipt()",
        7,
        definition=(
            "CREATE TRIGGER ac_workforce_page9_receipt_guard BEFORE INSERT ON "
            "workforce_editionstructurecommandreceipt FOR EACH ROW WHEN "
            "(new.action::text <> ALL (ARRAY['position_created'::character "
            "varying, 'position_updated'::character varying, "
            "'position_closed'::character varying, "
            "'opportunity_updated'::character varying]::text[])) EXECUTE "
            "FUNCTION maru_validate_edition_structure_receipt()"
        ),
    ),
    "ac_workforce_position_receipt_guard": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_validate_position_structure_receipt()",
        7,
        definition=(
            "CREATE TRIGGER ac_workforce_position_receipt_guard BEFORE INSERT ON "
            "workforce_editionstructurecommandreceipt FOR EACH ROW WHEN "
            "(new.action::text = ANY (ARRAY['position_created'::character "
            "varying, 'position_updated'::character varying, "
            "'position_closed'::character varying, "
            "'opportunity_updated'::character varying]::text[])) EXECUTE "
            "FUNCTION maru_validate_position_structure_receipt()"
        ),
    ),
    "ac_workforce_page9_receipt_immutable": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_prevent_edition_structure_receipt_mutation()",
        27,
    ),
    "ac_workforce_page9_receipt_no_truncate": _trigger(
        "workforce_editionstructurecommandreceipt",
        "maru_prevent_edition_structure_receipt_mutation()",
        34,
    ),
    "ac_workforce_page9_department_guard": _trigger(
        "workforce_department",
        "maru_validate_department_structure_write()",
        31,
    ),
    "ac_workforce_page9_department_no_truncate": _trigger(
        "workforce_department",
        "maru_prevent_department_structure_truncate()",
        34,
    ),
    "ac_workforce_page9_position_retired_guard": _trigger(
        "workforce_position",
        "maru_guard_position_retired_department()",
        23,
        columns=("department_id", "organization_id", "edition_id", "status"),
    ),
    "ac_workforce_page9_assignment_retired_guard": _trigger(
        "workforce_positionassignment",
        "maru_guard_assignment_retired_department()",
        23,
        columns=("position_id", "organization_id", "edition_id", "status"),
    ),
    "workforce_page9_control_evidence": _trigger(
        "workforce_editionstructurecontrol",
        "maru_assert_edition_structure_control_evidence()",
        21,
        deferrable=True,
        initially_deferred=True,
    ),
    "workforce_page9_department_evidence": _trigger(
        "workforce_department",
        "maru_assert_department_structure_evidence()",
        29,
        deferrable=True,
        initially_deferred=True,
    ),
    "ac_workforce_position_structure_guard": _trigger(
        "workforce_position",
        "maru_validate_position_structure_write()",
        23,
    ),
    "workforce_position_structure_evidence": _trigger(
        "workforce_position",
        "maru_assert_position_structure_evidence()",
        21,
        deferrable=True,
        initially_deferred=True,
    ),
    "ac_workforce_opportunity_structure_guard": _trigger(
        "workforce_volunteeropportunity",
        "maru_validate_opportunity_structure_write()",
        23,
    ),
    "workforce_opportunity_structure_evidence": _trigger(
        "workforce_volunteeropportunity",
        "maru_assert_opportunity_structure_evidence()",
        21,
        deferrable=True,
        initially_deferred=True,
    ),
}

PAGE9_FUNCTION_DEFINITION_SHA256 = {
    "maru_assert_department_structure_evidence()": (
        "7887c7c42b9770b592af5743b74f2ac47891e1d021aed3c9de45db3c5fe0a3bf"
    ),
    "maru_assert_edition_structure_control_evidence()": (
        "1c37f07d8fa5b7b6765ddeb2fccc0f852c21b0e55e1ed6b27e432d0559fb60f8"
    ),
    "maru_guard_assignment_retired_department()": (
        "e6265228b38fd359960c4e5e3506265b221f6bfb29628873f8d9df0e206611da"
    ),
    "maru_guard_position_retired_department()": (
        "6518f7456d68cd68fba7bf3eb3b2056de1c9a2308c49160bfcca7e052834c19d"
    ),
    "maru_assert_opportunity_structure_evidence()": (
        "ccdadc120d19afccdb078986412dd48151b3458f7b178dbcd1d172a5d010689c"
    ),
    "maru_assert_position_structure_evidence()": (
        "5669006e6ede713832cf294c8b1d192b990c064eec90e52d0d5b622770a74110"
    ),
    "maru_validate_opportunity_structure_write()": (
        "ab2f366a1aed806f637d82aa32ddeee0d8823fcdb84b5bf112d88ecec43ff830"
    ),
    "maru_validate_position_structure_receipt()": (
        "5490ada7d1367482d743391b9a0a0cca0e6ed0a96ab8c5dab3e0a477a0d1304d"
    ),
    "maru_validate_position_structure_write()": (
        "89807ac3c1e9eb9cc35568a2b2e4b4ced17e661c25e2ef037dee2842e1644d48"
    ),
    "maru_prevent_department_structure_truncate()": (
        "747cdf967ed6a518d641beed4abba918ae69938ad5f4ae4c5b99e3129b8cce1f"
    ),
    "maru_prevent_edition_structure_control_mutation()": (
        "3f765a5c19d7da7c2796b15ef175251492fe5302f0590c6ded011b9f048a282f"
    ),
    "maru_prevent_edition_structure_receipt_mutation()": (
        "f5f6dc38198cf2978e3c7613152b869375f1d26232ebcd4560986104e00f11fa"
    ),
    "maru_validate_department_structure_write()": (
        "e4a44adc84bce76b97a4e6d0f8fef19825b891d94bf41dc17f92225d1808f22a"
    ),
    "maru_validate_edition_structure_control()": (
        "52daa0c470438ca34cdd2a00e1b0aa5e61b9bed98a9cfc320b21a92fc6911686"
    ),
    "maru_validate_edition_structure_receipt()": (
        "0856108aaf1bf9fd11092d908fd289542e36faeb815a47e7d5de5680f2abd5a4"
    ),
    "maru_workforce_department_fk_contract_is_current()": (
        "789dee83be83009521d10eb1db382c0eac4e549f20e2105a7941f4d8f35f105b"
    ),
    "maru_workforce_page9_scope_mutex()": (
        "75e5f8a98fd059d1e5d2de0db420e77beec79f3c6eb12b051388ab66c85790c6"
    ),
    "maru_workforce_page9_try_scope_mutex(bigint)": (
        "4ebf99f0177936704c44598ee63a058e57bf6aaca130c51b8a8fa4fb799cb86f"
    ),
    "maru_workforce_page9_writer_barrier()": (
        "a5ca2897e19293a78e805a1a8fb4484f6822def7713c35141c0e7f2fbb4ad429"
    ),
}

PAGE9_DEPARTMENT_FK_CONTRACT = (
    ("applications_applicationownerdepartment", ("department_id",)),
    ("applications_programmecall", ("owner_department_id",)),
    ("authorization_capabilitygrant", ("department_id",)),
    ("authorization_roleassignment", ("department_id",)),
    ("authorization_scopedresourcebinding", ("department_id",)),
    ("charities_charityselection", ("responsible_department_id",)),
    ("logistics_equipmentoffer", ("responsible_department_id",)),
    ("logistics_logisticsmanifest", ("responsible_department_id",)),
    (
        "registration_registrationprofileextensionfield",
        ("audience_department_id",),
    ),
    ("venues_editionspaceselection", ("responsible_department_id",)),
    ("venues_editionvenueselection", ("responsible_department_id",)),
    ("venues_venuebooking", ("responsible_department_id",)),
    ("workforce_department", ("parent_id",)),
    ("workforce_position", ("department_id",)),
)


def _declared_page9_triggers() -> dict[str, tuple[object, ...]]:
    return {
        contract.name: (
            contract.table,
            contract.function,
            contract.trigger_type,
            "O",
            contract.deferrable,
            contract.initially_deferred,
            contract.definition is None,
            0,
            contract.columns,
            contract.definition,
        )
        for contract in provenance_readiness._TRIGGER_CONTRACTS
        if contract.name in PAGE9_TRIGGER_CONTRACTS
    }


def _installed_page9_triggers() -> dict[str, tuple[object, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure.oid::regprocedure::text,
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   trigger.tgqual IS NULL,
                   trigger.tgnargs,
                   ARRAY(
                       SELECT attribute.attname::text
                         FROM pg_catalog.unnest(trigger.tgattr::smallint[])
                              WITH ORDINALITY AS selected(attnum, position)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = trigger.tgrelid
                          AND attribute.attnum = selected.attnum
                        ORDER BY selected.position
                   ),
                   pg_catalog.pg_get_triggerdef(trigger.oid, TRUE)
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation.relnamespace
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = trigger.tgfoid
              JOIN pg_catalog.pg_namespace AS procedure_namespace
                ON procedure_namespace.oid = procedure.pronamespace
             WHERE NOT trigger.tgisinternal
               AND relation_namespace.nspname = 'public'
               AND procedure_namespace.nspname = 'public'
               AND (
                   trigger.tgname LIKE 'aa_workforce_page9_%'
                   OR trigger.tgname LIKE 'ab_workforce_page9_%'
                   OR trigger.tgname LIKE 'ac_workforce_page9_%'
                   OR trigger.tgname LIKE 'workforce_page9_%'
                   OR trigger.tgname IN (
                       'ac_workforce_position_receipt_guard',
                       'ac_workforce_position_structure_guard',
                       'workforce_position_structure_evidence',
                       'ac_workforce_opportunity_structure_guard',
                       'workforce_opportunity_structure_evidence'
                   )
               )
             ORDER BY trigger.tgname
            """
        )
        rows = cursor.fetchall()
    assert not [
        name for name, count in Counter(row[0] for row in rows).items() if count > 1
    ]
    return {
        str(row[0]): (
            *tuple(row[1:9]),
            tuple(row[9] or ()),
            None if row[7] else str(row[10]),
        )
        for row in rows
    }


def _installed_page9_function_hashes() -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT required.identity,
                   procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_catalog.pg_get_function_result(procedure.oid)
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
               AND namespace.nspname = 'public'
              JOIN pg_catalog.pg_language AS language
                ON language.oid = procedure.prolang
             ORDER BY required.identity
            """,
            [list(PAGE9_FUNCTION_DEFINITION_SHA256)],
        )
        rows = cursor.fetchall()
    return {
        str(row[0]): provenance_readiness._function_definition_fingerprint(
            tuple(row[1:])
        )
        for row in rows
    }


def test_page9_catalog_is_declared_and_installed_exactly() -> None:
    assert len(PAGE9_TRIGGER_CONTRACTS) == 33
    assert _declared_page9_triggers() == PAGE9_TRIGGER_CONTRACTS
    assert _installed_page9_triggers() == PAGE9_TRIGGER_CONTRACTS
    assert {
        identity: provenance_readiness._FUNCTION_DEFINITION_SHA256[identity]
        for identity in PAGE9_FUNCTION_DEFINITION_SHA256
    } == PAGE9_FUNCTION_DEFINITION_SHA256
    assert _installed_page9_function_hashes() == PAGE9_FUNCTION_DEFINITION_SHA256

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert catalog.migration_applied
    assert catalog.guards_installed
    assert catalog.downgrade_fence_installed


@pytest.mark.parametrize("identity", PAGE9_FUNCTION_DEFINITION_SHA256)
def test_each_page9_function_definition_tamper_blocks_readiness(identity: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER FUNCTION public.")
            + sql.SQL(identity)
            + sql.SQL(" SECURITY INVOKER")
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


@pytest.mark.parametrize(
    ("trigger_name", "contract"),
    PAGE9_TRIGGER_CONTRACTS.items(),
)
def test_each_page9_disabled_trigger_blocks_readiness(
    trigger_name: str,
    contract: tuple[object, ...],
) -> None:
    table = cast("str", contract[0])
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(
                sql.Identifier(table),
                sql.Identifier(trigger_name),
            )
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


def test_page9_update_column_tamper_blocks_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DROP TRIGGER ac_workforce_page9_position_retired_guard
                ON public.workforce_position;
            CREATE TRIGGER ac_workforce_page9_position_retired_guard
            BEFORE INSERT OR UPDATE OF status
            ON public.workforce_position
            FOR EACH ROW
            EXECUTE FUNCTION public.maru_guard_position_retired_department();
            """
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


def test_page9_constraint_timing_tamper_blocks_readiness() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DROP TRIGGER workforce_page9_control_evidence
                ON public.workforce_editionstructurecontrol;
            CREATE CONSTRAINT TRIGGER workforce_page9_control_evidence
            AFTER INSERT OR UPDATE
            ON public.workforce_editionstructurecontrol
            DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW
            EXECUTE FUNCTION
                public.maru_assert_edition_structure_control_evidence();
            """
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


@pytest.mark.parametrize(
    "migration_name",
    [
        "0007_structure_write_integrity",
        "0008_department_fk_contract_successor",
        "0009_reconcile_fictional_structure_template",
        "0010_position_structure_commands",
        "0016_programme_call_department_fk_contract",
    ],
)
def test_missing_page9_migration_recorder_row_blocks_readiness(
    migration_name: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'workforce'
               AND name = %s
            """,
            [migration_name],
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.migration_applied
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


def test_page9_department_fk_contract_is_installed_exactly() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT local_relation.relname::text,
                   ARRAY(
                       SELECT local_attribute.attname::text
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS local_key(attnum, position)
                         JOIN pg_catalog.pg_attribute AS local_attribute
                           ON local_attribute.attrelid = constraint_record.conrelid
                          AND local_attribute.attnum = local_key.attnum
                        ORDER BY local_key.position
                   ),
                   ARRAY(
                       SELECT referenced_attribute.attname::text
                         FROM pg_catalog.unnest(constraint_record.confkey)
                              WITH ORDINALITY AS referenced_key(attnum, position)
                         JOIN pg_catalog.pg_attribute AS referenced_attribute
                           ON referenced_attribute.attrelid =
                              constraint_record.confrelid
                          AND referenced_attribute.attnum = referenced_key.attnum
                        ORDER BY referenced_key.position
                   ),
                   constraint_record.confdeltype::text
              FROM pg_catalog.pg_constraint AS constraint_record
              JOIN pg_catalog.pg_class AS local_relation
                ON local_relation.oid = constraint_record.conrelid
             WHERE constraint_record.contype = 'f'
               AND constraint_record.confrelid =
                   'public.workforce_department'::pg_catalog.regclass
             ORDER BY local_relation.relname, constraint_record.conname
            """
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT public.maru_workforce_department_fk_contract_is_current()"
        )
        contract_is_current = cursor.fetchone()

    assert tuple((str(row[0]), tuple(row[1])) for row in rows) == (
        PAGE9_DEPARTMENT_FK_CONTRACT
    )
    assert all(tuple(row[2]) == ("id",) for row in rows)
    assert all(str(row[3]) in {"a", "r"} for row in rows)
    assert contract_is_current == (True,)


def test_page9_contract_sets_are_inside_the_downgrade_fence() -> None:
    assert set(PAGE9_TRIGGER_CONTRACTS) <= (
        provenance_readiness._DOWNGRADE_FENCE_TRIGGER_NAMES
    )
    assert set(PAGE9_FUNCTION_DEFINITION_SHA256) <= (
        provenance_readiness._DOWNGRADE_FENCE_FUNCTIONS
    )
    assert set(PAGE9_FUNCTION_DEFINITION_SHA256) <= set(
        provenance_readiness._CORE_FUNCTIONS
    )
