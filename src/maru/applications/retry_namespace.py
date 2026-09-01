"""Serialize the shared Applications command retry-key namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection

if TYPE_CHECKING:
    from uuid import UUID

_TRANSACTION_REQUIRED = "Applications retry locks require an atomic transaction."


def lock_applications_retry_namespace(
    *,
    edition_id: UUID,
    actor_id: UUID,
    retry_key: UUID,
) -> None:
    """Lock one cross-workflow Applications retry key for this transaction.

    Generic Applications commands and collaborative Programme commands retain
    receipts in separate tables. This shared PostgreSQL advisory lock closes the
    race between their replay checks; database receipt guards use the same key
    before accepting either insert.

    Parameters
    ----------
    edition_id : UUID
        The exact edition that scopes the command.
    actor_id : UUID
        The exact authenticated actor that owns the retry key.
    retry_key : UUID
        The caller-supplied idempotency key.

    Raises
    ------
    RuntimeError
        If called outside an atomic transaction, where the lock would not span
        the replay check and receipt insert.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(_TRANSACTION_REQUIRED)
    namespace = ":".join(
        (
            "maru",
            "applications",
            "retry",
            str(edition_id).lower(),
            str(actor_id).lower(),
            str(retry_key).lower(),
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(%s, 0))",
            [namespace],
        )
