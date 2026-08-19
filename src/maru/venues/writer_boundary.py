"""Closed ORM writer boundary for venue aggregates and evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_VENUE_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_venue_writer_active",
    default=False,
)


@contextmanager
def venue_writer() -> Iterator[None]:
    token = _VENUE_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _VENUE_WRITER_ACTIVE.reset(token)


def require_venue_writer() -> None:
    if not _VENUE_WRITER_ACTIVE.get():
        raise ValidationError(
            "Venue records may change only through a registered command.",
            code="venue_writer_required",
        )
