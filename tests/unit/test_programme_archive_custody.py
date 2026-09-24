"""Pure resource and corruption checks; native custody is exercised separately."""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from maru.programme import archive_custody as custody
from maru.programme.archive_tasks import (
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
)


@pytest.mark.parametrize("value", [None, "uuid", 0, False, UUID(int=0)])
@pytest.mark.parametrize("field", ["actor_id", "organization_id", "edition_id"])
def test_scope_requires_three_exact_nonzero_uuids(value, field):
    values = {key: uuid4() for key in ("actor_id", "organization_id", "edition_id")}
    values[field] = value
    with pytest.raises(ProgrammeArchiveUnavailableError):
        ProgrammeArchiveScope(**values)


@pytest.fixture
def rows(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(custody.ProgrammeArchiveChunk, "objects", manager)
    payload = b"synthetic private bytes"
    digest = hashlib.sha256(payload).hexdigest()
    row = SimpleNamespace(
        sequence=1, size_bytes=len(payload), sha256=digest, payload=payload
    )
    manager.filter.return_value.order_by.return_value.iterator.return_value = iter(
        (row,)
    )
    task = SimpleNamespace(
        id=uuid4(),
        state="ready",
        artifact_bytes=len(payload),
        chunk_count=1,
        artifact_digest=digest,
        chunk_root=hashlib.sha256(f"1:{len(payload)}:{digest}\n".encode()).hexdigest(),
    )
    return manager, row, task


def test_verified_chunks_accept_exact_bytes_and_order(rows):
    _, row, task = rows
    assert custody._verified_chunks(task) == (row.payload,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "running"),
        ("chunk_count", 0),
        ("chunk_count", 1027),
        ("artifact_bytes", 0),
        ("artifact_bytes", custody.MAX_CONTENT_BYTES + custody.MAX_METADATA_BYTES + 1),
        ("artifact_bytes", 1),
        ("artifact_bytes", 100),
        ("artifact_digest", "0" * 64),
        ("chunk_root", "0" * 64),
        ("chunk_count", 2),
    ],
)
def test_corrupt_task_identity_never_releases_bytes(rows, field, value):
    _, _, task = rows
    setattr(task, field, value)
    with pytest.raises(ProgrammeArchiveUnavailableError):
        custody._verified_chunks(task)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", 2),
        ("size_bytes", 1),
        ("payload", b""),
        ("payload", b"x" * (custody.WRITE_CHUNK_BYTES + 1)),
        ("sha256", "0" * 64),
    ],
    ids=("sequence", "size", "empty", "oversized", "digest"),
)
def test_missing_or_corrupt_chunk_identity_fails_before_return(rows, field, value):
    _, row, task = rows
    setattr(row, field, value)
    with pytest.raises(ProgrammeArchiveUnavailableError):
        custody._verified_chunks(task)


@pytest.mark.parametrize("items", [0, 2])
def test_missing_and_extra_chunks_are_not_partial_success(rows, items):
    manager, row, task = rows
    manager.filter.return_value.order_by.return_value.iterator.return_value = iter(
        [row] * items
    )
    with pytest.raises(ProgrammeArchiveUnavailableError):
        custody._verified_chunks(task)


def test_sink_buffers_one_partial_chunk_and_refuses_writes_after_finish(rows):
    manager, _, task = rows
    sink = custody._ArchiveChunkSink(task.id)
    assert sink.writable()
    assert sink.write(b"a" * custody.WRITE_CHUNK_BYTES) == custody.WRITE_CHUNK_BYTES
    assert sink.pending == b""
    assert sink.write(b"z") == 1
    sink.finish()
    assert not sink.writable()
    assert manager.create.call_count == 2
    assert manager.create.call_args.kwargs["payload"] == b"z"
    assert (
        sink.digest.hexdigest()
        == hashlib.sha256(b"a" * custody.WRITE_CHUNK_BYTES + b"z").hexdigest()
    )
    with pytest.raises(ProgrammeArchiveUnavailableError):
        sink.write(b"x")
    with pytest.raises(ProgrammeArchiveUnavailableError):
        sink.finish()


def test_sink_rejects_empty_completion_and_overflow_before_custody_write(
    rows, monkeypatch
):
    manager, _, task = rows
    sink = custody._ArchiveChunkSink(task.id)
    with pytest.raises(ProgrammeArchiveUnavailableError):
        sink.finish()
    monkeypatch.setattr(custody, "MAX_CONTENT_BYTES", 1)
    monkeypatch.setattr(custody, "MAX_METADATA_BYTES", 0)
    with pytest.raises(ProgrammeArchiveUnavailableError):
        sink.write(b"xx")
    manager.create.assert_not_called()
