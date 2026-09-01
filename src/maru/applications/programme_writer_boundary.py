"""Closed ORM writer boundary for Applications-owned Programme records."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection

if TYPE_CHECKING:
    from collections.abc import Iterator

_PROGRAMME_APPLICATION_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_programme_application_writer_active",
    default=False,
)
PROGRAMME_APPLICATION_WRITER_SETTING = "maru.applications_programme_writer"
_TRANSACTION_REQUIRED = (
    "Programme application database writes require an atomic transaction."
)


@contextmanager
def programme_application_writer() -> Iterator[None]:
    """Open the in-process Programme writer boundary.

    Runtime commands use :func:`programme_application_database_writer`, which
    nests this context with the PostgreSQL guard. This narrower context exists
    for model-level validation and must not be treated as database authority.

    Yields
    ------
    None
        Control while the Applications-owned Programme writer is active.
    """
    token = _PROGRAMME_APPLICATION_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _PROGRAMME_APPLICATION_WRITER_ACTIVE.reset(token)


@contextmanager
def programme_application_database_writer() -> Iterator[None]:
    """Open the ORM and transaction-local PostgreSQL writer boundaries.

    Yields
    ------
    None
        Control while both the in-process and database guards admit writes.

    Raises
    ------
    RuntimeError
        If called outside an atomic transaction.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(_TRANSACTION_REQUIRED)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.current_setting(%s, true)",
            [PROGRAMME_APPLICATION_WRITER_SETTING],
        )
        row = cursor.fetchone()
        previous = row[0] if row else None
        cursor.execute(
            "SELECT pg_catalog.set_config(%s, 'on', true)",
            [PROGRAMME_APPLICATION_WRITER_SETTING],
        )
    try:
        with programme_application_writer():
            yield
    finally:
        # A database error inside the writer marks the surrounding atomic block
        # for rollback. The transaction-local setting will be discarded by that
        # rollback, and attempting another query here would mask the original
        # integrity error with TransactionManagementError.
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config(%s, %s, true)",
                    [PROGRAMME_APPLICATION_WRITER_SETTING, previous or ""],
                )


def require_programme_application_writer() -> None:
    """Reject a Programme-call ORM write outside the command boundary.

    Raises
    ------
    ValidationError
        If no registered Programme-call command activated the boundary.
    """
    if not _PROGRAMME_APPLICATION_WRITER_ACTIVE.get():
        raise ValidationError(
            "Programme application records may change only through a registered "
            "command.",
            code="programme_application_writer_required",
        )


__all__ = [
    "PROGRAMME_APPLICATION_WRITER_SETTING",
    "programme_application_database_writer",
    "programme_application_writer",
    "require_programme_application_writer",
]
