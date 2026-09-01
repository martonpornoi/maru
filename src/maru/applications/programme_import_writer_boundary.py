"""Closed ORM and PostgreSQL writer boundary for Programme import staging."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection

if TYPE_CHECKING:
    from collections.abc import Iterator


_PROGRAMME_IMPORT_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_programme_import_writer_active",
    default=False,
)
PROGRAMME_IMPORT_WRITER_SETTING = "maru.applications_programme_import_writer"
_TRANSACTION_REQUIRED = "Programme import writes require an atomic transaction."


@contextmanager
def programme_import_writer() -> Iterator[None]:
    """Open only the in-process Programme-import writer boundary.

    Yields
    ------
    None
        Control to the registered import command while the ORM guard is open.
    """
    token = _PROGRAMME_IMPORT_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _PROGRAMME_IMPORT_WRITER_ACTIVE.reset(token)


@contextmanager
def programme_import_database_writer() -> Iterator[None]:
    """Open both import writer guards for the current transaction.

    Yields
    ------
    None
        Control while the in-process and transaction-local database guards are
        both open.

    Raises
    ------
    RuntimeError
        If no surrounding transaction can retain the database-local setting.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(_TRANSACTION_REQUIRED)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.current_setting(%s, true)",
            [PROGRAMME_IMPORT_WRITER_SETTING],
        )
        row = cursor.fetchone()
        previous = row[0] if row else None
        cursor.execute(
            "SELECT pg_catalog.set_config(%s, 'on', true)",
            [PROGRAMME_IMPORT_WRITER_SETTING],
        )
    try:
        with programme_import_writer():
            yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config(%s, %s, true)",
                    [PROGRAMME_IMPORT_WRITER_SETTING, previous or ""],
                )


def require_programme_import_writer() -> None:
    """Reject import ORM writes outside a registered import command.

    Raises
    ------
    ValidationError
        If no in-process Programme import writer context is active.
    """
    if not _PROGRAMME_IMPORT_WRITER_ACTIVE.get():
        raise ValidationError(
            "Programme import records may change only through a registered command.",
            code="programme_import_writer_required",
        )


__all__ = [
    "PROGRAMME_IMPORT_WRITER_SETTING",
    "programme_import_database_writer",
    "programme_import_writer",
    "require_programme_import_writer",
]
