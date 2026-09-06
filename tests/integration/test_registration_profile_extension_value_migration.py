"""Committed schema round trips and durable profile-value recovery evidence."""

import pytest
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

from maru.registration.profile_extension_values import append_profile_extension_value
from tests.integration import (
    test_registration_profile_extension_value_commands as value_tests,
)
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = (
    "registration",
    "0035_configuration_source_binding_guards",
)
REGISTRATION_AFTER = (
    "registration",
    "0036_profile_extension_value_commands",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def test_profile_value_schema_and_closed_helpers_migrate_forward_and_reverse() -> None:
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_value_control()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None, None)

    _migrate(REGISTRATION_AFTER)
    expected_functions = {
        "maru_assert_registration_profile_value_control_complete",
        "maru_assert_registration_profile_value_revision_evidence",
        "maru_guard_registration_profile_value_control",
        "maru_guard_registration_profile_value_immutable",
        "maru_guard_registration_profile_value_receipt",
        "maru_guard_registration_profile_value_revision_v2",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.proname,
                   procedure.prosecdef,
                   procedure.proconfig,
                   NOT EXISTS (
                       SELECT 1
                         FROM aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   ) AS public_execute_revoked
              FROM pg_proc AS procedure
             WHERE procedure.proname = ANY(%s)
             ORDER BY procedure.proname
            """,
            [list(expected_functions)],
        )
        functions = cursor.fetchall()
        assert {str(row[0]) for row in functions} == expected_functions
        for _name, security_definer, settings, public_execute_revoked in functions:
            assert security_definer is True
            assert "search_path=pg_catalog, public, pg_temp" in settings
            assert public_execute_revoked is True

        cursor.execute(
            """
            SELECT trigger.tgname,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred
              FROM pg_trigger AS trigger
             WHERE trigger.tgrelid IN (
                'registration_registrationprofileextensionvaluerevision'::regclass,
                'registration_registrationprofileextensionvaluecontrol'::regclass,
                'registration_registrationprofileextensionvaluecommandreceipt'::regclass
             )
               AND NOT trigger.tgisinternal
               AND trigger.tgname LIKE 'registration_profile_value_%'
             ORDER BY trigger.tgname
            """
        )
        triggers = cursor.fetchall()
        assert [str(row[0]) for row in triggers] == [
            "registration_profile_value_control_complete",
            "registration_profile_value_control_guard",
            "registration_profile_value_control_no_truncate",
            "registration_profile_value_receipt_guard",
            "registration_profile_value_receipt_no_truncate",
            "registration_profile_value_revision_evidence",
            "registration_profile_value_revision_no_truncate",
        ]
        for trigger_name in (
            "registration_profile_value_control_complete",
            "registration_profile_value_revision_evidence",
        ):
            deferred = next(row for row in triggers if row[0] == trigger_name)
            assert deferred[1:] == (True, True)
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE tgrelid = (
                'registration_registrationprofileextensionvaluerevision'::regclass
             )
               AND NOT tgisinternal
               AND tgname = 'registration_profile_extension_value_guard'
            """
        )
        assert cursor.fetchone() == ("registration_profile_extension_value_guard",)

    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_value_control()'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_extension_value()'
                   ) IS NOT NULL
            """
        )
        assert cursor.fetchone() == (None, None, None, True)

    _migrate(REGISTRATION_AFTER)


def test_empty_reverse_and_reapply_are_exact() -> None:
    _migrate(REGISTRATION_AFTER)
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_assert_registration_profile_value_revision_evidence()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None, None)

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ) IS NOT NULL,
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ) IS NOT NULL,
                   to_regprocedure(
                       'public.maru_assert_registration_profile_value_revision_evidence()'
                   ) IS NOT NULL
            """
        )
        assert cursor.fetchone() == (True, True, True)


def test_durable_command_receipt_fences_populated_reverse() -> None:
    registration, owner = value_tests._registration_world()
    field = value_tests._field(registration, actor=owner, key="durable-command")
    result = append_profile_extension_value(
        **value_tests._append_values(
            actor=owner,
            registration=registration,
            field=field,
        )
    )
    _migrate(REGISTRATION_AFTER)

    with pytest.raises(DatabaseError, match="use fix-forward recovery"):
        _migrate(REGISTRATION_BEFORE)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*), min(result_sequence), max(result_sequence)
              FROM registration_registrationprofileextensionvaluecommandreceipt
             WHERE id = %s
            """,
            [result.receipt_id],
        )
        assert cursor.fetchone() == (1, 1, 1)
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_guard_registration_profile_value_receipt()'
            ) IS NOT NULL
            """
        )
        assert cursor.fetchone()[0] is True
