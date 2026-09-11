from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction

from maru.identity.models import Account
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from tests.integration import (
    test_scheduling_release_identity_changes as identity_changes,
)
from tests.integration.test_scheduling_release_identity_changes import (
    _deactivate,
    _track,
)

people = identity_changes.people
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _worker(operation, backend_ids):
    close_old_connections()
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute("SELECT pg_backend_pid()")
            backend_ids.put(cursor.fetchone()[0])
            return operation()
    finally:
        connection.close()


def _observe_lock_wait(backend_id):
    deadline = monotonic() + 5
    delay = Event()
    with connection.cursor() as cursor:
        while monotonic() < deadline:
            cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [backend_id])
            if cursor.fetchone()[0] > 0:
                return
            delay.wait(0.02)
    pytest.fail("The competing native transaction did not reach a real lock wait.")


@pytest.mark.parametrize("rollback_tracking", [False, True])
def test_native_deactivation_waits_for_first_tracking_then_recollects(
    people, rollback_tracking
):
    backend_ids = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            key = _track(people[1])
            future = executor.submit(_worker, lambda: _deactivate(people), backend_ids)
            _observe_lock_wait(backend_ids.get(timeout=5))
            assert not future.done()
            if rollback_tracking:
                transaction.set_rollback(True)
        result = future.result(timeout=12)
    people[1].refresh_from_db()
    assert not result.account.is_active
    assert not people[1].is_active
    if rollback_tracking:
        assert not SchedulingReleaseDependencyKey.objects.exists()
        assert not SchedulingReleaseDependencyChange.objects.exists()
    else:
        key.refresh_from_db()
        change = SchedulingReleaseDependencyChange.objects.get(dependency=key)
        assert key.generation == change.generation == 2
        assert change.source_audit.target_id == people[1].id


def test_raw_writer_waiting_for_first_tracking_cannot_miss_new_key(people):
    backend_ids = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            key = _track(people[1])
            future = executor.submit(
                _worker,
                lambda: Account.objects.filter(pk=people[1].id).update(is_active=False),
                backend_ids,
            )
            _observe_lock_wait(backend_ids.get(timeout=5))
        with pytest.raises(IntegrityError, match="native release invalidation"):
            future.result(timeout=12)
    key.refresh_from_db()
    people[1].refresh_from_db()
    assert key.generation == 1
    assert people[1].is_active
    assert not SchedulingReleaseDependencyChange.objects.exists()


@pytest.mark.parametrize("rollback_deactivation", [False, True])
def test_first_tracking_waits_for_native_source_then_reads_committed_state(
    people, rollback_deactivation
):
    # Tracking authenticates identity, not publication eligibility: the later
    # publisher must reject the freshly observed inactive account after locking.
    backend_ids = Queue()

    def track_and_read():
        key = _track(people[1])
        return key.id, Account.objects.get(pk=people[1].id).is_active

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            _deactivate(people)
            future = executor.submit(_worker, track_and_read, backend_ids)
            _observe_lock_wait(backend_ids.get(timeout=5))
            assert not future.done()
            if rollback_deactivation:
                transaction.set_rollback(True)
        key_id, active = future.result(timeout=12)
    assert active is rollback_deactivation
    assert SchedulingReleaseDependencyKey.objects.get(pk=key_id).generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_untracked_eligibility_mutation_rejects_unsupported_snapshot(people, isolation):
    def change_under_snapshot():
        with connection.cursor() as cursor:
            if isolation == "REPEATABLE READ":
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            else:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        Account.objects.filter(pk=people[1].id).update(is_active=False)

    with (
        pytest.raises(IntegrityError, match="require READ COMMITTED"),
        transaction.atomic(),
    ):
        change_under_snapshot()
    people[1].refresh_from_db()
    assert people[1].is_active
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_first_tracking_rejects_unsupported_snapshot(people):
    def track_under_snapshot():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _track(people[1])

    with (
        pytest.raises(IntegrityError, match="requires READ COMMITTED"),
        transaction.atomic(),
    ):
        track_under_snapshot()
    assert not SchedulingReleaseDependencyKey.objects.exists()
