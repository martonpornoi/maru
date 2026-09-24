"""Private original-requester inspection with fresh complete owner checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from maru.audit.services import AuditRecord, append_audit

from .archive_custody import _verified_chunks
from .archive_tasks import (
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
    _archive_transaction,
    _authorize,
    _now,
    _task,
)
from .authorization import DEFAULT_PROGRAMME_AUTHORIZER
from .exit_composition import collect_programme_exit
from .models import ProgrammeArchiveTask

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveInspection:
    """Minimized currently authorized phase and optional completely verified bytes.

    Attributes
    ----------
    task_id, version, state
        Exact requester-owned task and truthful optimistic lifecycle version/phase.
    requested_at, expires_at
        Database-clock request and fixed expiry, never a refreshed download lease.
    failure_code
        Closed non-content reason, never raw worker exception information.
    expired
        Whether access expired by database clock, independent of worker disposal.
    source_changed
        Whether currently authorized sources differ, requiring a new request.
    size_bytes, sha256
        Ready artifact identity only; zero/blank when no download is available.
    chunks
        Optional verified attachment bytes; private and omitted from repr.
    """

    task_id: UUID
    version: int
    state: str
    requested_at: datetime
    expires_at: datetime
    failure_code: str
    expired: bool
    source_changed: bool
    size_bytes: int
    sha256: str
    chunks: tuple[bytes, ...] = field(repr=False)


def inspect_programme_archive(
    *, scope: ProgrammeArchiveScope, task_id: UUID, download: bool = False
) -> ProgrammeArchiveInspection:
    """Recheck all independent owners before private inspection or byte disclosure.

    Parameters
    ----------
    scope : ProgrammeArchiveScope
        Actual authenticated requester and independently selected tenant/edition.
    task_id : UUID
        Exact request identity, never a shareable bearer capability.
    download : bool, default=False
        Verify and include every byte for a private attachment response.

    Returns
    -------
    ProgrammeArchiveInspection
        Current complete projection after mandatory source and task-read auditing.

    Raises
    ------
    ProgrammeArchiveUnavailableError
        If request scope, source identity, current expiry or byte custody is invalid.

    Notes
    -----
    Any owner denial or failure propagates without partial metadata or bytes.
    No stored permission snapshot substitutes for current collection. Callers must
    use private/no-store attachment responses and must not cache this projection.
    """
    _authorize(scope, DEFAULT_PROGRAMME_AUTHORIZER)
    if (
        type(download) is not bool
        or not ProgrammeArchiveTask.objects.filter(
            id=task_id,
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        ).exists()
    ):
        raise ProgrammeArchiveUnavailableError
    trace = uuid4()
    with _archive_transaction():
        fresh = collect_programme_exit(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            correlation_id=trace,
        )
        task = _task(scope, task_id)
        source_changed = (
            task.state == "ready" and task.source_digest != fresh.source_digest
        )
        if download and source_changed:
            raise ProgrammeArchiveUnavailableError
        chunks: tuple[bytes, ...] = ()
        if download:
            if task.expires_at <= _now():
                raise ProgrammeArchiveUnavailableError
            chunks = _verified_chunks(task)
        _authorize(scope, DEFAULT_PROGRAMME_AUTHORIZER)
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=scope.actor_id,
                principal_context_id=None,
                organization_id=scope.organization_id,
                event_edition_id=scope.edition_id,
                capability_code="programme.export_archive",
                operation="programme.exit.task.download"
                if download
                else "programme.exit.task.inspect",
                target_type="programme.archive_task",
                target_id=task.id,
                outcome="allow",
                reason_code="current_archive_sources_verified",
                correlation_id=trace,
                source_channel="programme-exit",
                obligations=("audit",),
                retention_class="programme-restricted",
            )
        )
        observed = _now()
        if download and task.expires_at <= observed:
            raise ProgrammeArchiveUnavailableError
        available = (
            task.state == "ready" and task.expires_at > observed and not source_changed
        )
        return ProgrammeArchiveInspection(
            task.id,
            task.version,
            task.state,
            task.requested_at,
            task.expires_at,
            task.failure_code,
            task.expires_at <= observed,
            source_changed,
            task.artifact_bytes if available else 0,
            task.artifact_digest if available else "",
            chunks,
        )
