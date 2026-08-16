"""Closed ORM writer boundary for logistics aggregates and evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_LOGISTICS_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_logistics_writer_active",
    default=False,
)


@contextmanager
def logistics_writer() -> Iterator[None]:
    token = _LOGISTICS_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _LOGISTICS_WRITER_ACTIVE.reset(token)


def require_logistics_writer() -> None:
    if not _LOGISTICS_WRITER_ACTIVE.get():
        raise ValidationError(
            "Logistics records may change only through a registered command.",
            code="logistics_writer_required",
        )
