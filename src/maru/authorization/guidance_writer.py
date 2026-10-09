"""Private lexical Guidance writers; native evidence is the enforcement boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER: ContextVar[bool] = ContextVar("guidance_authority_writer", default=False)


@contextmanager
def _guidance_authority_writer() -> Iterator[None]:
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def _require_guidance_authority_writer() -> None:
    if not _WRITER.get():
        raise ValidationError(
            "Use the accepted Guidance responsibility command.",
            code="guidance_typed_command_required",
        )
