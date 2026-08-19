"""Closed ORM writer boundary for venue aggregates and evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

_VENUE_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_venue_writer_active",
    default=False,
)


@contextmanager
def venue_writer() -> Iterator[None]:
    """Return venue writer.

    Yields
    ------
    None
        The normalized value for venue writer.

    Returns
    -------
    Iterator[None]
        An iterator that manages the venue writer boundary.
    """
    token = _VENUE_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _VENUE_WRITER_ACTIVE.reset(token)


def require_venue_writer() -> None:
    """Require venue writer.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not _VENUE_WRITER_ACTIVE.get():
        raise ValidationError(
            "Venue records may change only through a registered command.",
            code="venue_writer_required",
        )
