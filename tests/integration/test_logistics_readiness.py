from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection
from psycopg import sql

from maru.logistics import readiness

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def test_installed_logistics_catalog_matches_the_fingerprinted_contract(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    role_name = f"maru_logistics_runtime_{uuid4().hex}"
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role_name))
        )
    try:
        settings.RUNTIME_DATABASE_ROLE = role_name  # type: ignore[attr-defined]
        monkeypatch.setattr(
            readiness,
            "probe_runtime_database_role_safety",
            lambda **_kwargs: SimpleNamespace(target_role_is_safe=True),
        )

        catalog = readiness.inspect_logistics_production_catalog()

        assert catalog.ready
        assert readiness.collect_logistics_schema_definition_sha256() == dict(
            readiness.SCHEMA_DEFINITION_SHA256
        )
        assert len(readiness.TRIGGER_CONTRACTS) == 91
        assert len(readiness.FUNCTION_CONTRACTS) == 9
        assert len(readiness.declared_schema_object_contracts()) == 102
        assert len(readiness.declared_implicit_unique_contracts()) == 13
        assert readiness.relation_privilege_profiles_are_declared()
        assert readiness.MIGRATION_CONTRACT_SYMMETRIC
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
