"""Atomic background archive generation under original requester source policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from .archive_custody import _ArchiveChunkSink
from .archive_tasks import (
    ACTIVE_STATES,
    EXECUTION_LIMIT,
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
    _archive_transaction,
    _authorize,
    _finish,
    _lock_retained_scope,
    _now,
    _record,
    _task,
)
from .authorization import DEFAULT_PROGRAMME_AUTHORIZER
from .exit_archive_protocol import ProgrammeArchiveContext, ProgrammeArchiveInvalidError
from .exit_archive_stream import write_programme_exit_archive
from .exit_composition import collect_programme_exit
from .models import ProgrammeArchiveTask
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from typing import BinaryIO


def _retained_scope(task_id: UUID) -> ProgrammeArchiveScope:
    row = (
        ProgrammeArchiveTask.objects.filter(id=task_id)
        .values("actor_id", "organization_id", "edition_id")
        .first()
    )
    if row is None:
        raise ProgrammeArchiveUnavailableError
    return ProgrammeArchiveScope(**row)


def _dispose(task_id: UUID, failure_code: str) -> str:
    scope = _retained_scope(task_id)
    with _archive_transaction(), programme_writer():
        _lock_retained_scope(scope)
        task = _task(scope, task_id)
        if task.state not in ACTIVE_STATES:
            return task.state
        state = "expired" if task.expires_at <= _now() else "failed"
        _finish(
            task,
            state,
            worker=True,
            failure_code=failure_code if state == "failed" else "",
        )
        return state


def _claim(scope: ProgrammeArchiveScope, task_id: UUID) -> bool:
    with _archive_transaction(), programme_writer():
        _authorize(scope, DEFAULT_PROGRAMME_AUTHORIZER, lock=True)
        task = _task(scope, task_id)
        if task.state != "queued":
            return False
        if task.expires_at <= _now():
            _finish(task, "expired", worker=True)
            return False
        task.state = "running"
        task.version += 1
        task.started_at = _now()
        task.generation_correlation_id = uuid4()
        task.save()
        _record(task, task.started_at, worker=True)
        return True


def _generate(scope: ProgrammeArchiveScope, task_id: UUID) -> None:
    # No task/person lock is held ahead of the complete Department/person closure.
    # The outer transaction retains every owner fence through ready + native evidence.
    with _archive_transaction(), programme_writer():
        reference = ProgrammeArchiveTask.objects.get(id=task_id)
        if reference.generation_correlation_id is None:
            raise ProgrammeArchiveUnavailableError
        collection = collect_programme_exit(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            correlation_id=reference.generation_correlation_id,
        )
        task = _task(scope, task_id)
        observed = _now()
        if (
            task.state != "running"
            or task.started_at is None
            or task.generation_correlation_id is None
            or task.expires_at <= observed
            or task.started_at + EXECUTION_LIMIT <= observed
        ):
            raise ProgrammeArchiveUnavailableError
        sink = _ArchiveChunkSink(task.id)
        encoded = write_programme_exit_archive(
            context=ProgrammeArchiveContext(
                scope.organization_id,
                scope.edition_id,
                scope.actor_id,
                task.generation_correlation_id,
                task.started_at,
            ),
            sections=collection.sections,
            files=collection.files,
            source_digest=collection.source_digest,
            sink=cast("BinaryIO", sink),
        )
        sink.finish()
        if (
            encoded.size_bytes != sink.size
            or encoded.sha256 != sink.digest.hexdigest()
            or task.started_at + EXECUTION_LIMIT <= _now()
        ):
            raise ProgrammeArchiveUnavailableError
        _authorize(scope, DEFAULT_PROGRAMME_AUTHORIZER)
        task.source_digest = collection.source_digest
        task.artifact_digest = encoded.sha256
        task.artifact_bytes = encoded.size_bytes
        task.chunk_count = sink.count
        task.chunk_root = sink.root.hexdigest()
        _finish(task, "ready", worker=True)


def generate_programme_archive(*, task_id: UUID) -> str:
    """Process one retained request using its actual requester's current source rights.

    Parameters
    ----------
    task_id : UUID
        Internal retained queue identity selected by the single purpose worker.

    Returns
    -------
    str
        Closed phase only; no private labels, counts, source data or exception text.

    Notes
    -----
    This is a server worker seam, not an authenticated HTTP command or a service
    principal grant. The management worker supplies global serialization, hard
    process deadline and finite database timeouts. Claim commits independently;
    source collection, complete chunks and ready evidence commit together. Any
    collection/encoding failure rolls back all chunks before terminal evidence.
    """
    scope = _retained_scope(task_id)
    try:
        claimed = _claim(scope, task_id)
    except Exception:  # noqa: BLE001 - job boundary records only a closed safe failure.
        return _dispose(task_id, "source_unavailable")
    if not claimed:
        return "skipped"
    try:
        _generate(scope, task_id)
    except (MemoryError, ProgrammeArchiveInvalidError):
        return _dispose(task_id, "resource_limit")
    except Exception:  # noqa: BLE001 - no private source exception text crosses jobs.
        return _dispose(task_id, "source_unavailable")
    return "ready"


def dispose_due_programme_archive(*, task_id: UUID) -> bool:
    """Expire derived custody or fail a crashed generation without source impersonation.

    Parameters
    ----------
    task_id : UUID
        Internal exact retained task selected by the single purpose worker.

    Returns
    -------
    bool
        Whether this call disposed due derived custody and appended phase evidence.

    Notes
    -----
    Uses the database clock and retained requester for attribution, even after
    deactivation or export revocation. It reads no source content and cannot extend
    expiry, resurrect work, change scope or remove immutable task/source evidence.
    """
    scope = _retained_scope(task_id)
    with _archive_transaction(), programme_writer():
        _lock_retained_scope(scope)
        task = _task(scope, task_id)
        if task.state not in ACTIVE_STATES:
            return False
        observed = _now()
        if task.expires_at <= observed:
            _finish(task, "expired", worker=True)
        elif (
            task.state == "running"
            and task.started_at is not None
            and task.started_at + EXECUTION_LIMIT <= observed
        ):
            _finish(task, "failed", worker=True, failure_code="worker_deadline")
        else:
            return False
        return True
