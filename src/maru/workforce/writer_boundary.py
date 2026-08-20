"""Public transaction boundaries for Page 9 workforce-structure writers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection
from django.db.transaction import TransactionManagementError

if TYPE_CHECKING:
    from uuid import UUID

PAGE_9_STRUCTURE_ACTIVATION_LOCK_KEY = 4_400_460_007
_EDITION_STRUCTURE_LOCK_NAMESPACE = "maru.workforce.department"


def _require_atomic_transaction() -> None:
    if connection.get_autocommit() or not connection.in_atomic_block:
        raise TransactionManagementError(
            "Page 9 structure writer locks require an atomic transaction."
        )


def lock_page_9_structure_writer_boundary() -> None:
    """Join the global Page 9 writer generation before narrower locks."""
    _require_atomic_transaction()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock_shared(%s)",
            [PAGE_9_STRUCTURE_ACTIVATION_LOCK_KEY],
        )


def lock_edition_structure_mutex(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> None:
    """Serialize structure-affecting writes within one exact edition scope.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    """
    _require_atomic_transaction()
    lock_name = f"{_EDITION_STRUCTURE_LOCK_NAMESPACE}:{organization_id}:{edition_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(%s, 0))",
            [lock_name],
        )
