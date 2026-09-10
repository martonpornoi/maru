"""Closed ORM boundary for dormant Workforce Programme-binding evidence."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

_BINDING_WRITER: ContextVar[bool] = ContextVar(
    "maru_programme_binding_writer", default=False
)


@contextmanager
def programme_staffing_writer() -> Iterator[None]:
    """Allow ORM writes inside the owner command, without granting authority.

    Yields
    ------
    None
        Control while the calling transaction creates exact binding evidence.
    """
    token = _BINDING_WRITER.set(True)
    try:
        yield
    finally:
        _BINDING_WRITER.reset(token)


def require_programme_staffing_writer() -> None:
    """Reject accidental ORM writes outside the governed adapter.

    Raises
    ------
    ValidationError
        If the owner command has not entered its local writer context.
    """
    if not _BINDING_WRITER.get():
        raise ValidationError(
            "Programme staffing links require their governed owner command."
        )
