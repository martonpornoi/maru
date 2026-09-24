"""Requester-bound exit requests and minimized native lifecycle evidence.

This module never returns source data or private task inspection. Archive reads
must additionally re-collect every owner through the disclosure boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from django.db import connection, transaction

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord
from maru.identity.queries import lock_account_references_for_evidence
from maru.workforce.programme_references import lock_programme_staffing_scope

from .archive_authorization import authorize_programme_archive_scope
from .authorization import DEFAULT_PROGRAMME_AUTHORIZER
from .exit_archive_protocol import CONTRACT
from .models import (
    ProgrammeArchiveChunk,
    ProgrammeArchiveTask,
    ProgrammeArchiveTaskEvent,
)
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from .authorization import ProgrammeAuthorizer

ACTIVE_STATES: Final = frozenset({"queued", "running", "ready"})
TERMINAL_STATES: Final = frozenset({"failed", "cancelled", "expired"})
EXECUTION_LIMIT: Final = timedelta(minutes=20)
MAX_RETAINED_TASKS: Final = 1000
MAX_ACTIVE_TASKS: Final = 4


class ProgrammeArchiveUnavailableError(RuntimeError):
    """Hide absent, foreign, expired, changed and unauthorized artifact details."""

    reason_code = "programme_archive_unavailable"


class ProgrammeArchiveConflictError(RuntimeError):
    """Require deliberate correction of an authorized request or stale command."""

    reason_code = "programme_archive_conflict"


class ProgrammeArchiveCapacityError(RuntimeError):
    """Refuse capacity without disclosing other tenants, tasks or counts."""

    reason_code = "programme_archive_capacity_unavailable"


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveScope:
    """Independently selected scope, not authority obtained from a task URL.

    Attributes
    ----------
    actor_id, organization_id, edition_id
        Actual authenticated requester and exact independently selected tenant scope.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID

    def __post_init__(self) -> None:
        """Reject malformed scope before any data-dependent lookup.

        Raises
        ------
        ProgrammeArchiveUnavailableError
            If any identifier is not an exact nonzero UUID.
        """
        if any(
            type(value) is not UUID or not value.int
            for value in (self.actor_id, self.organization_id, self.edition_id)
        ):
            raise ProgrammeArchiveUnavailableError


def _now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]  # type: ignore[no-any-return]


@contextmanager
def _archive_transaction() -> Iterator[None]:
    # Transaction-local bounds also protect synchronous request and disclosure
    # paths. Savepoint rollback restores caller settings on failure; success
    # explicitly restores them before returning to a possible outer transaction.
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        statement = cursor.fetchone()[0]
        cursor.execute("SHOW lock_timeout")
        lock = cursor.fetchone()[0]
        cursor.execute("SELECT set_config('statement_timeout', '120s', true)")
        cursor.execute("SELECT set_config('lock_timeout', '5s', true)")
        yield
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", [statement])
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [lock])


def _authorize(
    scope: ProgrammeArchiveScope, authorizer: ProgrammeAuthorizer, *, lock: bool = False
) -> None:
    authorize_programme_archive_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        requested_fields=frozenset({"archive_requests"}),
        authorizer=authorizer,
        lock=lock,
    )


def _lock_retained_scope(scope: ProgrammeArchiveScope) -> None:
    # Internal disposal may need to retain evidence after account deactivation.
    # It reads no source content and does not substitute for requester authority.
    lock_programme_staffing_scope(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if lock_account_references_for_evidence(account_ids=(scope.actor_id,)) != (
        scope.actor_id,
    ):
        raise ProgrammeArchiveUnavailableError


def _task(scope: ProgrammeArchiveScope, task_id: UUID) -> ProgrammeArchiveTask:
    if type(task_id) is not UUID or not task_id.int:
        raise ProgrammeArchiveUnavailableError
    task = (
        ProgrammeArchiveTask.objects.select_for_update()
        .filter(
            id=task_id,
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
        .first()
    )
    if task is None:
        raise ProgrammeArchiveUnavailableError
    return task


def _record(task: ProgrammeArchiveTask, observed: datetime, *, worker: bool) -> None:
    trace = uuid4()
    with audited_mutation(
        AuditRecord(
            principal_kind="account",
            principal_id=task.actor_id,
            principal_context_id=None,
            organization_id=task.organization_id,
            event_edition_id=task.edition_id,
            capability_code="programme.export_archive",
            operation=f"programme.exit.task.{task.state}",
            target_type="programme.archive_task",
            target_id=task.id,
            outcome="allow",
            reason_code="archive_worker_phase" if worker else "archive_request_phase",
            correlation_id=trace,
            source_channel="programme-exit-worker" if worker else "programme-exit",
            obligations=("audit",),
            retention_class="programme-restricted",
        ),
        occurred_at=observed,
    ) as evidence:
        ProgrammeArchiveTaskEvent.objects.create(
            task=task,
            version=task.version,
            state=task.state,
            occurred_at=observed,
            correlation_id=trace,
            failure_code=task.failure_code,
            audit_event_id=evidence.audit_id,
        )


def _finish(
    task: ProgrammeArchiveTask,
    state: str,
    *,
    worker: bool,
    failure_code: str = "",
) -> None:
    task.version += 1
    task.state = state
    task.finished_at = _now()
    task.failure_code = failure_code
    task.save()
    if state in TERMINAL_STATES:
        ProgrammeArchiveChunk.objects.filter(task_id=task.id).delete()
    _record(task, task.finished_at, worker=worker)


def request_programme_archive(
    *,
    scope: ProgrammeArchiveScope,
    request_key: UUID,
    previous_task_id: UUID | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> UUID:
    """Queue one exact requester-bound archive without synchronously reading owners.

    Parameters
    ----------
    scope : ProgrammeArchiveScope
        Actual requester and independently selected tenant/edition.
    request_key : UUID
        Nonzero idempotency key, reused only for this exact request.
    previous_task_id : UUID | None, default=None
        Explicit failed, cancelled or expired request being deliberately replaced.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Exact current policy; nondefault adapters require the sealed test harness.

    Returns
    -------
    UUID
        Acknowledged task identifier only, never source access or private metadata.

    Raises
    ------
    ProgrammeArchiveConflictError
        If request identity or retry semantics differ from the retained request.
    ProgrammeArchiveCapacityError
        If bounded request capacity is unavailable.

    Notes
    -----
    Current export authority is checked before lookup and under canonical locks.
    Generation and private inspection separately require every owner source right.
    Audit/native integrity failure rolls back the request. Replay never renews expiry.
    """
    _authorize(scope, authorizer)
    if any(
        type(value) is not UUID or not value.int
        for value in (request_key, *((previous_task_id,) if previous_task_id else ()))
    ) or (previous_task_id is not None and not isinstance(previous_task_id, UUID)):
        raise ProgrammeArchiveConflictError
    with _archive_transaction(), programme_writer():
        _authorize(scope, authorizer, lock=True)
        existing = ProgrammeArchiveTask.objects.filter(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            request_key=request_key,
        ).first()
        if existing is not None:
            if existing.previous_task_id != previous_task_id:
                raise ProgrammeArchiveConflictError
            return existing.id
        if previous_task_id is not None:
            previous = _task(scope, previous_task_id)
            if previous.state not in TERMINAL_STATES:
                raise ProgrammeArchiveConflictError
        # The native guard repeats these bounds. This lock makes normal contention
        # a stable generic capacity result instead of leaking database diagnostics.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('programme:exit:capacity@1', 0))"
            )
        observed = _now()
        tasks = ProgrammeArchiveTask.objects
        active = tasks.filter(state__in=ACTIVE_STATES, expires_at__gt=observed)
        if (
            tasks.filter(edition_id=scope.edition_id).count() >= MAX_RETAINED_TASKS
            or active.count() >= MAX_ACTIVE_TASKS
            or active.filter(edition_id=scope.edition_id).exists()
        ):
            raise ProgrammeArchiveCapacityError
        task = tasks.create(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            request_key=request_key,
            previous_task_id=previous_task_id,
            contract=CONTRACT,
            state="queued",
            version=1,
            requested_at=observed,
            expires_at=observed + timedelta(hours=24),
        )
        _record(task, observed, worker=False)
        _authorize(scope, authorizer)
        return task.id


def cancel_programme_archive(
    *,
    scope: ProgrammeArchiveScope,
    task_id: UUID,
    expected_version: int,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> None:
    """Dispose only the requester's derived bytes, preserving lifecycle and sources.

    Parameters
    ----------
    scope : ProgrammeArchiveScope
        Current authenticated requester and exact independent tenant scope.
    task_id : UUID
        Previously acknowledged request, not authority to inspect another task.
    expected_version : int
        Exact positive state version observed by this requester.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Current exact export policy with the sealed test replacement boundary.

    Raises
    ------
    ProgrammeArchiveConflictError
        If the version is malformed/stale or the task is already terminal.

    Notes
    -----
    Cancellation returns no source content or metadata, so does not re-export
    owners merely to remove derived bytes. Current export authority and exact
    requester binding remain required. The worker can expire inaccessible tasks.
    """
    _authorize(scope, authorizer)
    if type(expected_version) is not int or expected_version < 1:
        raise ProgrammeArchiveConflictError
    with _archive_transaction(), programme_writer():
        _authorize(scope, authorizer, lock=True)
        task = _task(scope, task_id)
        if task.version != expected_version or task.state not in ACTIVE_STATES:
            raise ProgrammeArchiveConflictError
        _finish(
            task,
            "expired" if task.expires_at <= _now() else "cancelled",
            worker=False,
        )
        _authorize(scope, authorizer)
