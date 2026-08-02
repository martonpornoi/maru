from __future__ import annotations

import pytest
from django.db import connection, transaction
from django.db.transaction import TransactionManagementError
from django.test.utils import CaptureQueriesContext

from maru.authorization.provenance import (
    lock_authority_provenance_writer_boundary,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_writer_boundary_requires_an_explicit_atomic_transaction() -> None:
    with pytest.raises(TransactionManagementError, match="atomic transaction"):
        lock_authority_provenance_writer_boundary()


def test_writer_boundary_acquires_shared_cutover_lock_before_latch() -> None:
    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        generation = lock_authority_provenance_writer_boundary()

    assert generation in {0, 1}
    boundary_queries = [
        captured["sql"]
        for captured in queries.captured_queries
        if "pg_advisory_xact_lock_shared" in captured["sql"]
    ]
    assert len(boundary_queries) == 1
    assert "maru_lock_authority_provenance_latch" in boundary_queries[0]
