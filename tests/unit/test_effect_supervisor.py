import subprocess
from uuid import uuid4

import pytest

from maru.effects.supervisor import (
    ChildOutcome,
    FairTenantScheduler,
    run_effect_child,
)


def test_fair_scheduler_rotates_and_adapts_to_candidate_changes() -> None:
    first, second, third = sorted((uuid4(), uuid4(), uuid4()), key=str)
    scheduler = FairTenantScheduler()

    assert scheduler.select((third, first, second)) == first
    assert scheduler.select((first, second, third)) == second
    assert scheduler.select((first, second, third)) == third
    assert scheduler.select((first, third)) == first
    assert scheduler.select(()) is None


def test_child_runner_classifies_success_failure_and_hard_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    return_code = 0

    def complete(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], return_code)

    monkeypatch.setattr("maru.effects.supervisor.subprocess.run", complete)
    completed = run_effect_child(
        organization_id=uuid4(),
        workload_pool="default",
        lease_seconds=60,
        execution_timeout_seconds=30,
        hard_timeout_seconds=40,
    )
    assert completed.outcome is ChildOutcome.COMPLETED

    return_code = 7
    failed = run_effect_child(
        organization_id=uuid4(),
        workload_pool="default",
        lease_seconds=60,
        execution_timeout_seconds=30,
        hard_timeout_seconds=40,
    )
    assert failed.outcome is ChildOutcome.FAILED
    assert failed.return_code == 7

    def time_out(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["manage.py"], timeout=40)

    monkeypatch.setattr("maru.effects.supervisor.subprocess.run", time_out)
    timed_out = run_effect_child(
        organization_id=uuid4(),
        workload_pool="default",
        lease_seconds=60,
        execution_timeout_seconds=30,
        hard_timeout_seconds=40,
    )
    assert timed_out.outcome is ChildOutcome.TIMED_OUT
    assert timed_out.return_code is None
