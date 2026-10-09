"""Closed ORM writer scope, reinforced by independent native evidence guards."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER = ContextVar("announcements_writer", default=False)


@contextmanager
def announcement_writer() -> Iterator[None]:
    """Permit owning command writes for the duration of one transaction.

    Yields
    ------
    None
        The guarded owning writer scope.
    """
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def require_announcement_writer() -> None:
    """Reject ordinary ORM writes outside an Announcements command.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if not _WRITER.get():
        raise ValidationError("Use an Announcements command.")
