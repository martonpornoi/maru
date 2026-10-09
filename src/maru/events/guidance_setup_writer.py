"""Private Events command scope; native guards remain the integrity boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER: ContextVar[bool] = ContextVar("guidance_setup_writer", default=False)


@contextmanager
def _guidance_setup_writer() -> Iterator[None]:
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def _require_guidance_setup_writer() -> None:
    if not _WRITER.get():
        raise ValidationError(
            "Guidance setup receipts require an accepted setup command."
        )
