"""Private stop receipt insertion scope; native guards remain authoritative."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER: ContextVar[bool] = ContextVar("programme_stop_writer", default=False)


@contextmanager
def _programme_stop_writer() -> Iterator[None]:
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def _require_programme_stop_writer() -> None:
    if not _WRITER.get():
        raise ValidationError(
            "Programme stop receipts require the owning stop command."
        )
