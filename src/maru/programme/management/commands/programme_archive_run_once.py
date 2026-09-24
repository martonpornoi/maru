"""Internal child entrypoint; operators use programme_archive_worker."""

from typing import Any

from django.core.management.base import BaseCommand

from maru.programme.archive_worker import (
    CHILD_BUSY,
    CHILD_IDLE,
    process_archive_queue_once,
)


class Command(BaseCommand):
    """Run one child holding the single-worker lease; no source data is printed."""

    help = "Internal archive child; use programme_archive_worker for hard supervision."

    def handle(self, *args: Any, **options: Any) -> None:
        """Exit with a closed child code, suppressing private exception details.

        Parameters
        ----------
        *args : Any
            Unused positional framework arguments.
        **options : Any
            Django standard management options; no actor/tenant override is accepted.

        Raises
        ------
        SystemExit
            Safe failure, busy or idle code; ready or deliberately skipped returns zero.
        """
        del args, options
        try:
            result = process_archive_queue_once()
        except Exception:  # noqa: BLE001 - terminal child boundary must not print private errors.
            raise SystemExit(1) from None
        if result == "busy":
            raise SystemExit(CHILD_BUSY)
        if result == "idle":
            raise SystemExit(CHILD_IDLE)
        if result not in {"ready", "skipped", "expired"}:
            raise SystemExit(1)
