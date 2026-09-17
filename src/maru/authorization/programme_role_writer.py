"""Private append scope for Programme commands; native guards remain mandatory."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER: ContextVar[bool] = ContextVar("programme_role_writer", default=False)


@contextmanager
def _programme_role_writer() -> Iterator[None]:
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def _require_programme_role_writer() -> None:
    if not _WRITER.get():
        raise ValidationError("Programme role evidence requires its owning command.")
