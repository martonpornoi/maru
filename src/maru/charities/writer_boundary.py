"""Closed ORM writer boundary for charity aggregates and evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

_CHARITY_WRITER_ACTIVE: ContextVar[bool] = ContextVar(
    "maru_charity_writer_active",
    default=False,
)


@contextmanager
def charity_writer() -> Iterator[None]:
    """Allow writes only while one code-owned command owns the transaction.

    Yields
    ------
    None
        The resolved Iterator[None] for charity writer.

    Returns
    -------
    Iterator[None]
        An iterator that manages the charity writer boundary.
    """
    token = _CHARITY_WRITER_ACTIVE.set(True)
    try:
        yield
    finally:
        _CHARITY_WRITER_ACTIVE.reset(token)


def require_charity_writer() -> None:
    """Require charity writer.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not _CHARITY_WRITER_ACTIVE.get():
        raise ValidationError(
            "Charity records may change only through a registered command.",
            code="charity_writer_required",
        )
