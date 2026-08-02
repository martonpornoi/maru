from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.workforce.structure_snapshot import (
    current_structure_version,
    repeatable_read_only_snapshot,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _statements(queries: CaptureQueriesContext) -> list[str]:
    return [str(query["sql"]).strip().upper() for query in queries.captured_queries]


def test_projection_snapshot_owns_repeatable_read_read_only_transaction() -> None:
    with (
        CaptureQueriesContext(connection) as queries,
        repeatable_read_only_snapshot(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT current_setting('transaction_isolation'), "
            "current_setting('transaction_read_only')"
        )
        isolation_level, read_only = cursor.fetchone()

    statements = _statements(queries)
    isolation_statement = next(
        statement for statement in statements if statement.startswith("SET TRANSACTION")
    )
    setting_probe = next(
        statement
        for statement in statements
        if "CURRENT_SETTING('TRANSACTION_ISOLATION')" in statement
    )
    assert isolation_statement == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )
    assert statements.index(isolation_statement) < statements.index(setting_probe)
    assert isolation_level == "repeatable read"
    assert read_only == "on"


def test_post_snapshot_version_probe_owns_read_committed_read_only_transaction() -> (
    None
):
    with CaptureQueriesContext(connection) as queries:
        version = current_structure_version(
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    statements = _statements(queries)
    isolation_statement = next(
        statement for statement in statements if statement.startswith("SET TRANSACTION")
    )
    control_probe = next(
        statement
        for statement in statements
        if "WORKFORCE_EDITIONSTRUCTURECONTROL" in statement
    )
    assert isolation_statement == (
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY"
    )
    assert statements.index(isolation_statement) < statements.index(control_probe)
    assert version == 0
