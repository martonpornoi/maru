"""Private bounded derived chunk storage, never an authorization boundary."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

from .archive_tasks import ProgrammeArchiveUnavailableError
from .exit_archive_stream import (
    MAX_CONTENT_BYTES,
    MAX_METADATA_BYTES,
    WRITE_CHUNK_BYTES,
)
from .models import ProgrammeArchiveChunk

MAX_CHUNKS = (MAX_CONTENT_BYTES + MAX_METADATA_BYTES) // WRITE_CHUNK_BYTES

if TYPE_CHECKING:
    from collections.abc import Buffer
    from uuid import UUID

    from .models import ProgrammeArchiveTask


class _ArchiveChunkSink(io.RawIOBase):
    """Hold at most one partial chunk between writes inside atomic completion."""

    def __init__(self, task_id: UUID) -> None:
        """Bind a fresh sink to the worker's already locked running request.

        Parameters
        ----------
        task_id : UUID
            Exact owner request whose completion transaction contains all writes.
        """
        super().__init__()
        self.task_id = task_id
        self.pending = bytearray()
        self.count = 0
        self.size = 0
        self.digest = hashlib.sha256()
        self.root = hashlib.sha256()
        self.finished = False

    def writable(self) -> bool:
        return not self.finished

    def write(self, data: Buffer, /) -> int:
        value = memoryview(data).cast("B")
        if (
            self.finished
            or self.size + len(value) > MAX_CONTENT_BYTES + MAX_METADATA_BYTES
        ):
            raise ProgrammeArchiveUnavailableError
        self.size += len(value)
        self.digest.update(value)
        offset = 0
        while offset < len(value):
            length = min(WRITE_CHUNK_BYTES - len(self.pending), len(value) - offset)
            self.pending.extend(value[offset : offset + length])
            offset += length
            if len(self.pending) == WRITE_CHUNK_BYTES:
                self._store()
        return len(value)

    def _store(self) -> None:
        payload = bytes(self.pending)
        digest = hashlib.sha256(payload).hexdigest()
        self.count += 1
        ProgrammeArchiveChunk.objects.create(
            task_id=self.task_id,
            sequence=self.count,
            size_bytes=len(payload),
            sha256=digest,
            payload=payload,
        )
        self.root.update(f"{self.count}:{len(payload)}:{digest}\n".encode())
        self.pending.clear()

    def finish(self) -> None:
        if self.finished or not self.size:
            raise ProgrammeArchiveUnavailableError
        if self.pending:
            self._store()
        self.finished = True


def _verified_chunks(task: ProgrammeArchiveTask) -> tuple[bytes, ...]:
    # Only the owner disclosure service calls this after current source admission
    # and a task lock. Validate everything before returning the first response byte.
    if (
        task.state != "ready"
        or not 1 <= task.chunk_count <= MAX_CHUNKS
        or not 1 <= task.artifact_bytes <= MAX_CONTENT_BYTES + MAX_METADATA_BYTES
    ):
        raise ProgrammeArchiveUnavailableError
    rows = ProgrammeArchiveChunk.objects.filter(task_id=task.id).order_by("sequence")
    result = []
    digest, root = hashlib.sha256(), hashlib.sha256()
    total = 0
    for sequence, row in enumerate(rows.iterator(chunk_size=1), 1):
        payload = bytes(row.payload)
        actual = hashlib.sha256(payload).hexdigest()
        if (
            sequence > task.chunk_count
            or row.sequence != sequence
            or row.size_bytes != len(payload)
            or not 1 <= len(payload) <= WRITE_CHUNK_BYTES
            or (sequence < task.chunk_count and len(payload) != WRITE_CHUNK_BYTES)
            or actual != row.sha256
        ):
            raise ProgrammeArchiveUnavailableError
        total += len(payload)
        if total > task.artifact_bytes:
            raise ProgrammeArchiveUnavailableError
        result.append(payload)
        digest.update(payload)
        root.update(f"{sequence}:{len(payload)}:{actual}\n".encode())
    if (
        len(result) != task.chunk_count
        or total != task.artifact_bytes
        or digest.hexdigest() != task.artifact_digest
        or root.hexdigest() != task.chunk_root
    ):
        raise ProgrammeArchiveUnavailableError
    return tuple(result)
