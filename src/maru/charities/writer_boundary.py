"""Closed ORM writer boundary for charity aggregates and evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_CHARITY_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_charity_writer_active",
    default=False,
)


@contextmanager
def charity_writer() -> Iterator[None]:
    """Allow writes only while one code-owned command owns the transaction."""

    token = _CHARITY_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _CHARITY_WRITER_ACTIVE.reset(token)


def require_charity_writer() -> None:
    if not _CHARITY_WRITER_ACTIVE.get():
        raise ValidationError(
            "Charity records may change only through a registered command.",
            code="charity_writer_required",
        )
