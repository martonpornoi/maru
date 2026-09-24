"""Single purpose child supervision and bounded database-only queue processing."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

from django.conf import settings
from django.db import connection
from django.db.models import Q

from .archive_generation import (
    dispose_due_programme_archive,
    generate_programme_archive,
)
from .archive_tasks import ACTIVE_STATES, EXECUTION_LIMIT, _now
from .models import ProgrammeArchiveTask
from .readiness import programme_database_integrity_is_ready

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_CLEANUP_TASKS: Final = 32
WORKER_LOCK: Final = "programme:exit:single-worker@1"
CHILD_BUSY: Final = 3
CHILD_IDLE: Final = 4


@contextmanager
def _bounded_connection() -> Iterator[None]:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        statement = cursor.fetchone()[0]
        cursor.execute("SHOW lock_timeout")
        lock = cursor.fetchone()[0]
        cursor.execute("SELECT set_config('statement_timeout', '120s', false)")
        cursor.execute("SELECT set_config('lock_timeout', '5s', false)")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)", [statement]
            )
            cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock])


def process_archive_queue_once() -> str:
    """Process at most one request and bounded due cleanup with one global worker.

    Returns
    -------
    str
        Closed phase, idle or busy; no task/requester/source details.

    Raises
    ------
    RuntimeError
        If schema is not ready or this child is nested in a transaction.

    Notes
    -----
    Internal child entrypoint only. The public supervisor enforces the hard process
    timeout; this child holds the session advisory lock through claim, complete
    generation and cleanup. Process death releases both locks and partial writes.
    """
    if connection.in_atomic_block or not programme_database_integrity_is_ready():
        raise RuntimeError("programme_archive_worker_unavailable")
    with _bounded_connection(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [WORKER_LOCK]
        )
        if not cursor.fetchone()[0]:
            return "busy"
        try:
            observed = _now()
            due = tuple(
                ProgrammeArchiveTask.objects.filter(state__in=ACTIVE_STATES)
                .filter(
                    Q(expires_at__lte=observed)
                    | Q(state="running", started_at__lte=observed - EXECUTION_LIMIT)
                )
                .order_by("expires_at", "id")
                .values_list("id", flat=True)[:MAX_CLEANUP_TASKS]
            )
            for task_id in due:
                dispose_due_programme_archive(task_id=task_id)
            queued = (
                ProgrammeArchiveTask.objects.filter(
                    state="queued", expires_at__gt=_now()
                )
                .order_by("requested_at", "id")
                .values_list("id", flat=True)
                .first()
            )
            return (
                "idle" if queued is None else generate_programme_archive(task_id=queued)
            )
        finally:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [WORKER_LOCK]
            )


def supervise_archive_queue_once() -> str:
    """Run one silent child with a non-optional twenty-minute wall-clock limit.

    Returns
    -------
    str
        Completed, failed, timed_out, busy or idle; never child output or private data.

    Notes
    -----
    Uses the current interpreter, fixed checked-in management entrypoint and current
    environment; no alternate actor, database, owner credentials or shell is supplied.
    A timeout kills and waits for the child. Retained running requests are disposed
    by a subsequent bounded pass after their database-clock execution deadline.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed interpreter/entrypoint, no user arguments.
            [
                sys.executable,
                str(Path(settings.BASE_DIR) / "src" / "manage.py"),
                "programme_archive_run_once",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=EXECUTION_LIMIT.total_seconds(),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return "timed_out"
    except OSError:
        return "failed"
    return {0: "completed", CHILD_BUSY: "busy", CHILD_IDLE: "idle"}.get(
        result.returncode, "failed"
    )
