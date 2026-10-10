"""Private Events command scope; native guards remain the integrity boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError

_WRITER: ContextVar[bool] = ContextVar("announcements_setup_writer", default=False)


@contextmanager
def _announcements_setup_writer() -> Iterator[None]:
    token = _WRITER.set(True)
    try:
        yield
    finally:
        _WRITER.reset(token)


def _require_announcements_edition_setup() -> None:
    """Reject edition creation outside the dedicated Announcements setup.

    Raises
    ------
    ValidationError
        Unless the dedicated command owns the current private writer scope.
    """
    if not _WRITER.get():
        raise ValidationError(
            {
                "adoption_profile_code": ValidationError(
                    "Use Set up Announcements to create this edition.",
                    code="edition_adoption_profile_requires_setup",
                )
            }
        )


def _require_announcements_setup_writer() -> None:
    if not _WRITER.get():
        raise ValidationError(
            "Announcements setup receipts require an accepted setup command."
        )
