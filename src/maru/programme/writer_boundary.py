"""Closed ORM writer boundary for Programme aggregates and evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

_PROGRAMME_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_programme_writer_active",
    default=False,
)


@contextmanager
def programme_writer() -> Iterator[None]:
    """Authorize ORM writes within a registered Programme command.

    Yields
    ------
    None
        Control while the closed writer boundary is active.
    """
    token = _PROGRAMME_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _PROGRAMME_WRITER_ACTIVE.reset(token)


def require_programme_writer() -> None:
    """Reject a Programme ORM write outside the command boundary.

    Raises
    ------
    ValidationError
        If no registered Programme command activated the writer boundary.
    """
    if not _PROGRAMME_WRITER_ACTIVE.get():
        raise ValidationError(
            "Programme records may change only through a registered command.",
            code="programme_writer_required",
        )


__all__ = ["programme_writer", "require_programme_writer"]
