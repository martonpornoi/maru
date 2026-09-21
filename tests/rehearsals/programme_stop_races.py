"""Actual separate-runtime-connection stop races on independently restored clones."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event
from uuid import uuid4

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_logical_restore import (
    _WORKER,
    _child,
    _require,
    _restored_database,
    _runtime_data_state,
)
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    approve_synthetic_role,
    scenario_from_document,
)

ORDERS = ("stop_first", "candidate_first", "same_key")


def verify_stop_races(fixture):
    """Prove actual lock blocking without weakening writers or touching source state."""
    fixture.refresh_workers()
    for order in ORDERS:
        with _restored_database(fixture) as (runtime, source_state):
            scope = {
                "MARU_DATABASE_URL": runtime.database_url,
                "MARU_PROGRAMME_REHEARSAL_RUN_ID": runtime.run_id,
            }
            _child(
                ["-c", _WORKER],
                fixture._worker_environment | scope,
                timeout=min(180, remaining_lease(fixture.deadline)),
                expected_output="programme-invitation-cycle-verified",
            )
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "tests.rehearsals.programme_stop_races"],
                    cwd=ROOT,
                    env=fixture._application_environment | scope,
                    input=json.dumps(
                        {"setup": asdict(fixture.scenario), "order": order}, default=str
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    check=False,
                    timeout=min(120, remaining_lease(fixture.deadline)),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ProgrammeHttpsError("fixture_stop_race_process_failed") from None
            _require(
                result.returncode == 0
                and result.stdout.strip() == "programme-stop-race-verified",
                "fixture_stop_race_failed_" + order,
            )
            _require(
                _runtime_data_state(fixture.runtime) == source_state,
                "fixture_stop_race_source_changed",
            )
        fixture.verify_excluded_state()


def _contend(first, second):
    from django.db import connection, connections, transaction  # noqa: PLC0415

    retained, attempted = Event(), Event()
    second_backend = []

    def hold_first():
        try:
            with transaction.atomic():
                result = first()
                retained.set()
                _require(attempted.wait(timeout=10), "fixture_stop_race_not_started")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))",
                            [second_backend[0]],
                        )
                        blocked_by_us = cursor.fetchone() == (True,)
                    if blocked_by_us:
                        return result
                    time.sleep(0.05)
                raise ProgrammeHttpsError("fixture_stop_race_did_not_block")
        finally:
            retained.set()
            connections.close_all()

    def run_second():
        try:
            _require(retained.wait(timeout=10), "fixture_stop_race_first_unavailable")
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                second_backend.append(cursor.fetchone()[0])
            attempted.set()
            return second()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.submit(hold_first), pool.submit(run_second)
        return left.result(timeout=45), right.result(timeout=45)


def _verify(document):
    require_programme_runtime_environment()
    _require(
        type(document) is dict
        and set(document) == {"setup", "order"}
        and document["order"] in ORDERS,
        "fixture_stop_race_input_invalid",
    )
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from django.core.exceptions import ValidationError  # noqa: PLC0415

    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.events.models import EventEdition, ProgrammeStopReceipt  # noqa: PLC0415
    from maru.events.programme_stop_commands import stop_programme  # noqa: PLC0415
    from maru.events.programme_stop_composition import (  # noqa: PLC0415
        load_programme_stop_preview,
    )
    from maru.events.programme_stop_inputs import ProgrammeStopInput  # noqa: PLC0415
    from maru.scheduling.authorization import (  # noqa: PLC0415
        SchedulingAuthorizationDeniedError,
    )
    from maru.scheduling.candidate_commands import (  # noqa: PLC0415
        create_scheduling_candidate,
    )
    from maru.scheduling.command_support import SchedulingCommandError  # noqa: PLC0415
    from maru.scheduling.inputs import SchedulingCommandRequest  # noqa: PLC0415
    from maru.scheduling.models import SchedulingCandidate  # noqa: PLC0415

    approve_synthetic_role(
        setup,
        people=setup.controllers,
        recipient=setup.controllers[0],
        code="planner",
        level=ScopeLevel.EDITION,
    )
    actor = setup.controllers[0].authenticate()
    scope = {
        "actor_id": actor.id,
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
    }
    preview = load_programme_stop_preview(**scope, correlation_id=uuid4())
    key = uuid4()

    def stop():
        try:
            return stop_programme(
                **scope,
                details=ProgrammeStopInput(
                    preview.aggregate_version,
                    preview.lifecycle_version,
                    preview.fingerprint,
                    "Synthetic concurrent original stop intent.",
                ),
                idempotency_key=key,
                correlation_id=uuid4(),
            )
        except ValidationError as error:
            _require(
                error.code == "programme_stop_preview_conflict",
                "fixture_stop_race_wrong_conflict",
            )
            return None

    def candidate():
        try:
            return create_scheduling_candidate(
                SchedulingCommandRequest(
                    **scope,
                    idempotency_key=uuid4(),
                    correlation_id=uuid4(),
                    reason="Synthetic competing private draft.",
                    source_channel="test",
                ),
                label="Synthetic concurrent draft",
                expected_control_version=0,
            )
        except (SchedulingCommandError, SchedulingAuthorizationDeniedError):
            return None

    order = document["order"]
    first, second = _contend(
        candidate if order == "candidate_first" else stop,
        candidate if order == "stop_first" else stop,
    )
    source = {"organization_id": setup.organization_id, "edition_id": setup.edition_id}
    _require(first is not None, "fixture_stop_race_first_failed")
    if order == "same_key":
        _require(
            second is not None
            and first.receipt_id == second.receipt_id
            and first.replayed is False
            and second.replayed is True,
            "fixture_stop_race_retry_changed",
        )
    else:
        _require(second is None, "fixture_stop_race_both_accepted")
    _require(
        ProgrammeStopReceipt.objects.filter(**source).count()
        == (order != "candidate_first")
        and SchedulingCandidate.objects.filter(**source).count()
        == (order == "candidate_first")
        and EventEdition.objects.get(pk=setup.edition_id).lifecycle
        == (preview.lifecycle if order == "candidate_first" else "archived"),
        "fixture_stop_race_result_changed",
    )


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 2
        _verify(json.loads(raw))
    except Exception:  # noqa: BLE001 - never echo private child input or connection state.
        return 2
    sys.stdout.write("programme-stop-race-verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
