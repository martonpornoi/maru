"""Upgrade/reverse evidence for the Applications function ACL boundary."""

from __future__ import annotations

import hashlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from maru.applications.readiness import APPLICATIONS_INTEGRITY_CONTRACT

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

APPLICATIONS_BEFORE_ACL = ("applications", "0002_integrity_guards")
APPLICATIONS_WITH_ACL = (
    "applications",
    "0003_integrity_function_execute_boundary",
)
LEGACY_FUNCTION_IDENTITIES = (
    "maru_applications_guard_definition()",
    "maru_applications_guard_definition_child()",
    "maru_applications_guard_submission()",
    "maru_applications_guard_answer()",
    "maru_applications_guard_review()",
    "maru_applications_guard_target()",
    "maru_applications_append_only()",
)
LEGACY_TRIGGER_NAMES = (
    "applications_definition_guard",
    "applications_owner_guard",
    "applications_reviewer_role_guard",
    "applications_reviewer_person_guard",
    "applications_section_guard",
    "applications_question_guard",
    "applications_submission_guard",
    "applications_answer_guard",
    "applications_review_guard",
    "applications_target_guard",
    "applications_receipt_guard",
    "applications_file_guard",
)


def _function_acl_catalog(
    identities: tuple[str, ...] = LEGACY_FUNCTION_IDENTITIES,
) -> dict[str, tuple[bool, bool, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT required.identity,
                   EXISTS (
                       SELECT 1
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault(
                                     'f'::pg_catalog."char",
                                     procedure.proowner
                                 )
                             )
                         ) AS privilege
                        WHERE privilege.privilege_type = 'EXECUTE'
                          AND privilege.grantee = 0
                   ),
                   (
                       SELECT count(*) = 1
                          AND bool_and(
                              privilege.grantee = procedure.proowner
                          )
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault(
                                     'f'::pg_catalog."char",
                                     procedure.proowner
                                 )
                             )
                         ) AS privilege
                        WHERE privilege.privilege_type = 'EXECUTE'
                   ),
                   procedure.prosrc
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
             ORDER BY required.identity
            """,
            [list(identities)],
        )
        rows = cursor.fetchall()
    return {
        str(identity): (
            bool(public_execute),
            bool(owner_only),
            hashlib.sha256(
                str(source).replace("\r\n", "\n").strip().encode("utf-8")
            ).hexdigest(),
        )
        for identity, public_execute, owner_only, source in rows
    }


def _trigger_catalog(
    names: tuple[str, ...] = LEGACY_TRIGGER_NAMES,
) -> tuple[tuple[object, ...], ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND trigger.tgname = ANY(%s::text[])
               AND NOT trigger.tgisinternal
             ORDER BY trigger.tgname
            """,
            [list(names)],
        )
        return tuple(tuple(row) for row in cursor.fetchall())


def test_acl_migration_reverses_and_reapplies_without_definition_drift() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([APPLICATIONS_BEFORE_ACL])

    before_acl = _function_acl_catalog()
    before_triggers = _trigger_catalog()
    assert set(before_acl) == set(LEGACY_FUNCTION_IDENTITIES)
    assert all(
        public and not owner_only
        for public, owner_only, _definition in before_acl.values()
    )

    executor = MigrationExecutor(connection)
    executor.migrate([APPLICATIONS_WITH_ACL])

    after_acl = _function_acl_catalog()
    assert set(after_acl) == set(before_acl)
    assert all(
        not public and owner_only
        for public, owner_only, _definition in after_acl.values()
    )
    assert {
        identity: definition
        for identity, (_public, _owner_only, definition) in before_acl.items()
    } == {
        identity: definition
        for identity, (_public, _owner_only, definition) in after_acl.items()
    }
    assert _trigger_catalog() == before_triggers


def test_programme_integrity_reverse_restores_legacy_and_reapplies_exactly() -> None:
    current_functions = tuple(APPLICATIONS_INTEGRITY_CONTRACT.functions)
    current_triggers = tuple(APPLICATIONS_INTEGRITY_CONTRACT.triggers)
    before_functions = _function_acl_catalog(current_functions)
    before_triggers = _trigger_catalog(current_triggers)
    assert set(before_functions) == set(current_functions)

    executor = MigrationExecutor(connection)
    executor.migrate([APPLICATIONS_WITH_ACL])

    legacy_functions = _function_acl_catalog()
    assert set(legacy_functions) == set(LEGACY_FUNCTION_IDENTITIES)
    assert len(_trigger_catalog()) == len(LEGACY_TRIGGER_NAMES)
    assert all(
        not public and owner_only
        for public, owner_only, _definition in legacy_functions.values()
    )

    executor = MigrationExecutor(connection)
    executor.migrate(
        [
            (
                "applications",
                "0006_programme_populated_downgrade_fence",
            )
        ]
    )

    after_functions = _function_acl_catalog(current_functions)
    after_triggers = _trigger_catalog(current_triggers)
    assert after_functions == before_functions
    assert after_triggers == before_triggers
