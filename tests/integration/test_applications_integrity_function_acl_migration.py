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


def _function_acl_catalog() -> dict[str, tuple[bool, bool, str]]:
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
            [list(APPLICATIONS_INTEGRITY_CONTRACT.functions)],
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


def _trigger_catalog() -> tuple[tuple[object, ...], ...]:
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
            [list(APPLICATIONS_INTEGRITY_CONTRACT.triggers)],
        )
        return tuple(tuple(row) for row in cursor.fetchall())


def test_acl_migration_reverses_and_reapplies_without_definition_drift() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([APPLICATIONS_BEFORE_ACL])

    before_acl = _function_acl_catalog()
    before_triggers = _trigger_catalog()
    assert set(before_acl) == set(APPLICATIONS_INTEGRITY_CONTRACT.functions)
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
