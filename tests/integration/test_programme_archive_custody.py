"""Actual archive schema/state/custody guards, not current profile activation."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord
from maru.programme import archive_authorization, archive_tasks
from maru.programme.archive_custody import _ArchiveChunkSink, _verified_chunks
from maru.programme.archive_tasks import (
    ProgrammeArchiveCapacityError,
    ProgrammeArchiveConflictError,
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
    cancel_programme_archive,
    request_programme_archive,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.models import (
    ProgrammeArchiveChunk,
    ProgrammeArchiveTask,
    ProgrammeArchiveTaskEvent,
)
from maru.programme.readiness import programme_database_integrity_is_ready
from maru.programme.writer_boundary import programme_writer
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_programme_queries import _TrustedAuthorizer

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]


def record(task, observed):
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
            reason_code="synthetic_archive_state",
            correlation_id=trace,
            source_channel="programme-exit-worker",
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


def create(*, evidence=True, **overrides):
    actor, edition = AccountFactory(), EventEditionFactory()
    with transaction.atomic(), programme_writer():
        observed = now()
        values = {
            "actor_id": actor.id,
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
            "request_key": uuid4(),
            "contract": "programme.exit-archive@1",
            "state": "queued",
            "version": 1,
            "requested_at": observed,
            "expires_at": observed + timedelta(hours=24),
        }
        task = ProgrammeArchiveTask.objects.create(**{**values, **overrides})
        if evidence:
            record(task, observed)
    return task


def claim(task):
    with transaction.atomic(), programme_writer():
        task.version += 1
        task.state = "running"
        task.started_at = now()
        task.generation_correlation_id = uuid4()
        task.save()
        record(task, task.started_at)


def complete(task, *, content=b"synthetic opaque derived bytes", bad_root=False):
    with transaction.atomic(), programme_writer():
        digest = hashlib.sha256(content).hexdigest()
        ProgrammeArchiveChunk.objects.create(
            task=task,
            sequence=1,
            size_bytes=len(content),
            sha256=digest,
            payload=content,
        )
        task.version += 1
        task.state = "ready"
        task.finished_at = now()
        task.source_digest = "a" * 64
        task.artifact_digest = digest
        task.chunk_root = hashlib.sha256(
            f"1:{len(content)}:{digest}\n".encode()
        ).hexdigest()
        if bad_root:
            task.chunk_root = "0" * 64
        task.artifact_bytes = len(content)
        task.chunk_count = 1
        task.save()
        record(task, task.finished_at)


def test_native_archive_roundtrip_keeps_task_history_after_derived_disposal():
    task = create()
    claim(task)
    complete(task)
    assert programme_database_integrity_is_ready()
    with transaction.atomic(), programme_writer():
        task.version += 1
        task.state = "cancelled"
        task.finished_at = now()
        task.save()
        ProgrammeArchiveChunk.objects.filter(task=task).delete()
        record(task, task.finished_at)
    assert not ProgrammeArchiveChunk.objects.exists()
    assert list(
        ProgrammeArchiveTaskEvent.objects.filter(task=task)
        .order_by("version")
        .values_list("state", flat=True)
    ) == ["queued", "running", "ready", "cancelled"]
    assert task.artifact_digest


def test_native_request_without_fresh_matching_audit_rolls_back():
    with pytest.raises(DatabaseError, match="lifecycle evidence"):
        create(evidence=False)
    assert not ProgrammeArchiveTask.objects.exists()


def test_native_scope_cannot_name_an_edition_from_a_different_organization():
    foreign = EventEditionFactory()
    with pytest.raises(DatabaseError, match="scope or request"):
        create(edition_id=foreign.id)


@pytest.mark.parametrize("field", ["actor_id", "request_key", "expires_at", "version"])
def test_native_request_identity_and_sequence_cannot_be_rewritten(field):
    task = create()
    value = (
        task.expires_at + timedelta(hours=1)
        if field == "expires_at"
        else (3 if field == "version" else uuid4())
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        ProgrammeArchiveTask.objects.filter(id=task.id).update(**{field: value})
    task.refresh_from_db()
    assert task.version == 1


def test_native_incomplete_or_corrupt_custody_cannot_be_marked_ready():
    task = create()
    claim(task)
    with pytest.raises(DatabaseError, match="complete custody"):
        complete(task, bad_root=True)
    task.refresh_from_db()
    assert task.state == "running"
    assert not ProgrammeArchiveChunk.objects.exists()
    assert ProgrammeArchiveTaskEvent.objects.filter(task=task).count() == 2


@pytest.mark.parametrize("fault", ["queued", "hash", "staged-only"])
def test_native_chunks_require_claim_exact_bytes_and_atomic_completion(fault):
    task = create()
    if fault != "queued":
        claim(task)
    content = b"synthetic"
    with pytest.raises(DatabaseError), transaction.atomic(), programme_writer():
        ProgrammeArchiveChunk.objects.create(
            task=task,
            sequence=1,
            size_bytes=len(content),
            payload=content,
            sha256="0" * 64 if fault == "hash" else hashlib.sha256(content).hexdigest(),
        )
    assert not ProgrammeArchiveChunk.objects.exists()


def test_native_ready_bytes_cannot_be_deleted_or_mutated_without_disposal():
    task = create()
    claim(task)
    complete(task)
    with pytest.raises(DatabaseError), transaction.atomic():
        ProgrammeArchiveChunk.objects.filter(task=task).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        ProgrammeArchiveChunk.objects.filter(task=task).update(payload=b"changed")


def test_native_used_downgrade_refuses_before_removing_guards_or_recorder():
    create()
    with pytest.raises(DatabaseError, match="fix forward"):
        MigrationExecutor(connection).migrate(
            [("programme", "0020_exit_archive_records")]
        )
    assert programme_database_integrity_is_ready()
    assert ProgrammeArchiveTask.objects.count() == 1


def test_native_unused_schema_reverse_and_forward_preserve_readiness():
    assert not ProgrammeArchiveTask.objects.exists()
    try:
        MigrationExecutor(connection).migrate(
            [("programme", "0019_public_copy_withdrawal_integrity")]
        )
        assert (
            "programme_programmearchivetask"
            not in connection.introspection.table_names()
        )
        assert not programme_database_integrity_is_ready()
    finally:
        MigrationExecutor(connection).migrate(
            [("programme", "0021_exit_archive_integrity")]
        )
    assert programme_database_integrity_is_ready()


@pytest.fixture
def request_scope(monkeypatch):
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )
    actor, edition = AccountFactory(), EventEditionFactory()
    return {
        "scope": ProgrammeArchiveScope(actor.id, edition.organization_id, edition.id),
        "authorizer": _TrustedAuthorizer(),
    }


def test_request_replay_is_same_acknowledgement_without_new_evidence_or_expiry(
    request_scope,
):
    key = uuid4()
    task_id = request_programme_archive(**request_scope, request_key=key)
    original = ProgrammeArchiveTask.objects.get(id=task_id)
    assert request_programme_archive(**request_scope, request_key=key) == task_id
    current = ProgrammeArchiveTask.objects.get(id=task_id)
    assert current.expires_at == original.expires_at
    assert current.expires_at == current.requested_at + timedelta(hours=24)
    assert current.version == 1
    assert ProgrammeArchiveTaskEvent.objects.count() == 1


def test_concurrent_same_key_requests_retain_exactly_one_task_and_event(request_scope):
    key, start = uuid4(), Barrier(2)

    def invoke():
        close_old_connections()
        try:
            start.wait(timeout=5)
            return request_programme_archive(**request_scope, request_key=key)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0] == results[1]
    assert ProgrammeArchiveTask.objects.count() == 1
    assert ProgrammeArchiveTaskEvent.objects.count() == 1


def test_deliberate_cancel_then_linked_retry_preserves_old_evidence(request_scope):
    original = request_programme_archive(**request_scope, request_key=uuid4())
    cancel_programme_archive(**request_scope, task_id=original, expected_version=1)
    replacement = request_programme_archive(
        **request_scope, request_key=uuid4(), previous_task_id=original
    )
    assert replacement != original
    old = ProgrammeArchiveTask.objects.get(id=original)
    assert old.state == "cancelled"
    assert ProgrammeArchiveTask.objects.get(id=replacement).previous_task_id == original
    assert ProgrammeArchiveTaskEvent.objects.filter(task_id=original).count() == 2


def test_request_cannot_resurrect_or_rewrite_retry_parent(request_scope):
    key = uuid4()
    original = request_programme_archive(**request_scope, request_key=key)
    with pytest.raises(ProgrammeArchiveConflictError):
        request_programme_archive(
            **request_scope, request_key=key, previous_task_id=uuid4()
        )
    with pytest.raises(ProgrammeArchiveConflictError):
        request_programme_archive(
            **request_scope, request_key=uuid4(), previous_task_id=original
        )
    cancel_programme_archive(**request_scope, task_id=original, expected_version=1)
    assert request_programme_archive(**request_scope, request_key=key) == original
    assert ProgrammeArchiveTask.objects.get(id=original).state == "cancelled"


def test_capacity_does_not_disclose_another_requester_and_stale_cancel_does_not_mutate(
    request_scope,
):
    original = request_programme_archive(**request_scope, request_key=uuid4())
    with pytest.raises(ProgrammeArchiveCapacityError):
        request_programme_archive(**request_scope, request_key=uuid4())
    with pytest.raises(ProgrammeArchiveConflictError):
        cancel_programme_archive(**request_scope, task_id=original, expected_version=2)
    assert ProgrammeArchiveTask.objects.get(id=original).state == "queued"


@pytest.mark.parametrize("scope_change", ["actor_id", "organization_id", "edition_id"])
def test_cancel_is_bound_to_requester_and_exact_independent_scope(
    request_scope, scope_change
):
    original = request_programme_archive(**request_scope, request_key=uuid4())
    scope = request_scope["scope"]
    foreign = EventEditionFactory()
    values = {
        "actor_id": scope.actor_id,
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
    }
    values[scope_change] = (
        AccountFactory().id
        if scope_change == "actor_id"
        else (
            foreign.organization_id if scope_change == "organization_id" else foreign.id
        )
    )
    with pytest.raises(
        (ProgrammeArchiveUnavailableError, ProgrammeAuthorizationDeniedError)
    ):
        cancel_programme_archive(
            **{**request_scope, "scope": ProgrammeArchiveScope(**values)},
            task_id=original,
            expected_version=1,
        )
    assert ProgrammeArchiveTask.objects.get(id=original).state == "queued"


def test_revocation_is_checked_before_replay_or_cancel(request_scope):
    key = uuid4()
    original = request_programme_archive(**request_scope, request_key=key)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        request_programme_archive(scope=request_scope["scope"], request_key=key)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        cancel_programme_archive(
            scope=request_scope["scope"], task_id=original, expected_version=1
        )
    assert ProgrammeArchiveTaskEvent.objects.count() == 1


def test_audit_failure_rolls_back_request_and_cancellation(request_scope, monkeypatch):
    original = request_programme_archive(**request_scope, request_key=uuid4())

    def unavailable(*_, **__):
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(archive_tasks, "audited_mutation", unavailable)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        cancel_programme_archive(**request_scope, task_id=original, expected_version=1)
    assert ProgrammeArchiveTask.objects.get(id=original).version == 1
    foreign = EventEditionFactory()
    with pytest.raises(RuntimeError, match="synthetic audit"):
        request_programme_archive(
            scope=ProgrammeArchiveScope(
                request_scope["scope"].actor_id, foreign.organization_id, foreign.id
            ),
            authorizer=request_scope["authorizer"],
            request_key=uuid4(),
        )
    assert ProgrammeArchiveTask.objects.count() == 1


def test_private_sink_roundtrip_spans_exact_chunks_and_rechecks_every_byte():
    task = create()
    claim(task)
    content = b"x" * (1_048_576 + 17)
    with transaction.atomic(), programme_writer():
        sink = _ArchiveChunkSink(task.id)
        assert sink.write(content[:13]) == 13
        assert sink.write(content[13:]) == len(content) - 13
        sink.finish()
        assert sink.count == 2
        task.source_digest = "a" * 64
        task.artifact_digest = sink.digest.hexdigest()
        task.chunk_root = sink.root.hexdigest()
        task.chunk_count = sink.count
        task.artifact_bytes = sink.size
        archive_tasks._finish(task, "ready", worker=True)
    assert b"".join(_verified_chunks(task)) == content
    task.artifact_digest = "0" * 64
    with pytest.raises(ProgrammeArchiveUnavailableError):
        _verified_chunks(task)
