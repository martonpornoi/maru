"""Committed account serialization in both first-capture orders, including rollback."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest
from django.db import OperationalError, transaction

from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.workforce.models import ShiftCommitment
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_scheduling_release_identity_races import (
    _observe_lock_wait,
    _worker,
)
from tests.integration.test_scheduling_release_person_work_changes import _track

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def work():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    return world, demand


@pytest.mark.parametrize("rollback_tracking", [False, True])
def test_native_claim_waits_for_first_person_tracking_and_recollects(
    work, rollback_tracking
):
    world, demand = work
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            key = _track(world.person)
            future = executor.submit(
                _worker, lambda: shifts._claim(world, demand), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_tracking:
                transaction.set_rollback(True)
        claim = future.result(timeout=12)
    assert ShiftCommitment.objects.get(id=claim.commitment_id).status == "claimed"
    if rollback_tracking:
        assert not SchedulingReleaseDependencyKey.objects.exists()
        assert not SchedulingReleaseDependencyChange.objects.exists()
    else:
        key.refresh_from_db()
        assert key.generation == 2
        assert (
            SchedulingReleaseDependencyChange.objects.get(
                dependency=key
            ).source_audit.target_id
            == claim.commitment_id
        )


@pytest.mark.parametrize("rollback_claim", [False, True])
def test_first_tracking_waits_for_native_claim_then_reads_committed_work(
    work, rollback_claim
):
    world, demand = work
    backends = Queue()

    def capture_and_read():
        key = _track(world.person)
        current = ShiftCommitment.objects.filter(
            account=world.person, status="claimed"
        ).exists()
        return key.id, current

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            shifts._claim(world, demand)
            future = executor.submit(_worker, capture_and_read, backends)
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_claim:
                transaction.set_rollback(True)
        identifier, current = future.result(timeout=12)
    assert current is not rollback_claim
    assert SchedulingReleaseDependencyKey.objects.get(id=identifier).generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_inverted_raw_commitment_writer_fails_without_waiting_on_captured_person(work):
    world, demand = work
    claim = shifts._claim(world, demand)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor, transaction.atomic():
        key = _track(world.person)
        future = executor.submit(
            _worker,
            lambda: ShiftCommitment.objects.filter(id=claim.commitment_id).update(
                status="claimed"
            ),
            backends,
        )
        backends.get(timeout=5)
        with pytest.raises(OperationalError) as failure:
            future.result(timeout=12)
        assert failure.value.__cause__.sqlstate == "55P03"
    key.refresh_from_db()
    assert key.generation == 1
    assert ShiftCommitment.objects.get(id=claim.commitment_id).status == "claimed"
