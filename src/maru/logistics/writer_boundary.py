"""Closed ORM writer boundary for logistics aggregates and evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOGISTICS_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_logistics_writer_active",
    default=False,
)


@contextmanager
def logistics_writer() -> Iterator[None]:
    """Return logistics writer.

    Yields
    ------
    None
        The normalized value for logistics writer.

    Returns
    -------
    Iterator[None]
        An iterator that manages the logistics writer boundary.
    """
    token = _LOGISTICS_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _LOGISTICS_WRITER_ACTIVE.reset(token)


def require_logistics_writer() -> None:
    """Require logistics writer.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not _LOGISTICS_WRITER_ACTIVE.get():
        raise ValidationError(
            "Logistics records may change only through a registered command.",
            code="logistics_writer_required",
        )
