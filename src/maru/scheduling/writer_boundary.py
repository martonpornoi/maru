"""Closed ORM writer scope; database guards remain independently required."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

_WRITER_ACTIVE: ContextVar[bool] = ContextVar("maru_scheduling_writer", default=False)
_ACTIVE_RECEIPT: ContextVar[UUID | None] = ContextVar(
    "maru_scheduling_receipt", default=None
)


@contextmanager
def _command_receipt_scope(receipt_id: UUID) -> Iterator[None]:
    token = _ACTIVE_RECEIPT.set(receipt_id)
    try:
        yield
    finally:
        _ACTIVE_RECEIPT.reset(token)


def _require_active_receipt(receipt_id: UUID) -> None:
    require_scheduling_writer()
    if _ACTIVE_RECEIPT.get() != receipt_id:
        raise ValidationError(
            "Physical source proof requires its active Scheduling command."
        )


@contextmanager
def scheduling_writer() -> Iterator[None]:
    """Enter the Scheduling-owned ORM mutation scope.

    Yields
    ------
    None
        Control while a registered command retains its transaction.
    """
    token = _WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _WRITER_ACTIVE.reset(token)


def require_scheduling_writer() -> None:
    """Reject an ORM write outside a registered Scheduling command.

    Raises
    ------
    ValidationError
        If no command activated the current writer scope.
    """
    if not _WRITER_ACTIVE.get():
        raise ValidationError("Scheduling records require a registered command.")
