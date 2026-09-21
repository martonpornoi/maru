"""Populated accountable stop under the genuine restricted runtime identity."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from uuid import uuid4

import psycopg

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    approve_synthetic_role,
    scenario_from_document,
)

_PHASES = (
    "startup",
    "preview",
    "missing_withdrawal",
    "grant",
    "stale_preview",
    "rollback",
    "stop",
    "retry",
    "retained_history",
)
_phase = "startup"


def _require(condition, code="fixture_stop_evidence_changed"):
    if not condition:
        raise ProgrammeHttpsError(code)


def _verify_rollback(arguments, source, before_pointer, preview, before_withdrawals):
    from django.db import transaction  # noqa: PLC0415

    from maru.events.models import EventEdition, ProgrammeStopReceipt  # noqa: PLC0415
    from maru.events.programme_stop_commands import stop_programme  # noqa: PLC0415
    from maru.scheduling.models import (  # noqa: PLC0415
        SchedulingReleasePointer,
        SchedulingReleaseWithdrawal,
    )

    class _RollbackProbeError(Exception):
        pass

    def abort():
        raise _RollbackProbeError

    try:
        with transaction.atomic():
            stop_programme(**arguments, correlation_id=uuid4())
            _require(
                EventEdition.objects.get(pk=source["edition_id"]).lifecycle
                == "archived"
            )
            _require(
                SchedulingReleasePointer.objects.get(**source).active_release_id is None
            )
            abort()
    except _RollbackProbeError:
        pass
    pointer = SchedulingReleasePointer.objects.get(**source)
    _require(
        (pointer.active_release_id, pointer.version)
        == (before_pointer.active_release_id, before_pointer.version)
        and not ProgrammeStopReceipt.objects.filter(**source).exists()
        and EventEdition.objects.get(pk=source["edition_id"]).lifecycle
        == preview.lifecycle
        and SchedulingReleaseWithdrawal.objects.filter(**source).count()
        == before_withdrawals
    )
    return pointer


def _confirmable_preview(setup, scope, source):
    global _phase  # noqa: PLW0603 - closed private child diagnostic.
    from django.core.exceptions import ValidationError  # noqa: PLC0415

    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.services import AuthorizationDenied  # noqa: PLC0415
    from maru.events.models import ProgrammeStopReceipt  # noqa: PLC0415
    from maru.events.programme_stop_commands import stop_programme  # noqa: PLC0415
    from maru.events.programme_stop_composition import (  # noqa: PLC0415
        load_programme_stop_preview,
    )
    from maru.events.programme_stop_inputs import ProgrammeStopInput  # noqa: PLC0415

    _phase = "preview"
    preview = load_programme_stop_preview(**scope, correlation_id=uuid4())
    _require(not preview.scheduling.withdrawal_authorized)

    def intent(projection):
        return ProgrammeStopInput(
            projection.aggregate_version,
            projection.lifecycle_version,
            projection.fingerprint,
            "Stop the synthetic Programme adoption; preserve its accountable history.",
        )

    original = intent(preview)
    _phase = "missing_withdrawal"
    try:
        stop_programme(
            **scope, details=original, idempotency_key=uuid4(), correlation_id=uuid4()
        )
    except AuthorizationDenied:
        pass
    else:
        raise ProgrammeHttpsError("fixture_stop_missing_withdrawal_was_admitted")
    _require(not ProgrammeStopReceipt.objects.filter(**source).exists())
    _phase = "grant"
    approve_synthetic_role(
        setup,
        people=setup.controllers,
        recipient=setup.controllers[0],
        code="publisher",
        level=ScopeLevel.EDITION,
    )
    _phase = "stale_preview"
    try:
        stop_programme(
            **scope, details=original, idempotency_key=uuid4(), correlation_id=uuid4()
        )
    except ValidationError as failure:
        _require(failure.code == "programme_stop_preview_conflict")
    else:
        raise ProgrammeHttpsError("fixture_stop_stale_preview_was_admitted")
    preview = load_programme_stop_preview(**scope, correlation_id=uuid4())
    _require(preview.scheduling.withdrawal_authorized)
    return preview, intent(preview)


def prepare_stop_scenario(document):
    """Prove independent withdrawal, rollback, immutable history and actual retry."""
    global _phase  # noqa: PLW0603 - private child emits only this closed diagnostic code.
    require_programme_runtime_environment()
    _require(set(document) == {"setup"})
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.events.models import ProgrammeStopReceipt  # noqa: PLC0415
    from maru.events.programme_stop_commands import stop_programme  # noqa: PLC0415
    from maru.scheduling.models import (  # noqa: PLC0415
        SchedulingReleaseArtifact,
        SchedulingReleasePointer,
        SchedulingReleaseWithdrawal,
    )

    actor = setup.controllers[0].authenticate()
    scope = {
        "actor_id": actor.id,
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
    }
    source = {"organization_id": setup.organization_id, "edition_id": setup.edition_id}
    before_pointer = SchedulingReleasePointer.objects.get(**source)
    _require(before_pointer.active_release_id is not None)
    before_artifacts = tuple(
        SchedulingReleaseArtifact.objects.filter(**source)
        .order_by("id")
        .values_list("id", "payload")
    )
    before_withdrawals = SchedulingReleaseWithdrawal.objects.filter(**source).count()
    preview, details = _confirmable_preview(setup, scope, source)
    arguments = {**scope, "details": details, "idempotency_key": uuid4()}

    _phase = "rollback"
    pointer = _verify_rollback(
        arguments, source, before_pointer, preview, before_withdrawals
    )
    _phase = "stop"
    result = stop_programme(**arguments, correlation_id=uuid4())
    _phase = "retry"
    retry = stop_programme(**arguments, correlation_id=uuid4())
    _require(retry == replace(result, replayed=True))
    _phase = "retained_history"
    pointer.refresh_from_db()
    receipt = ProgrammeStopReceipt.objects.get(pk=result.receipt_id)
    _require(
        pointer.active_release_id is None
        and pointer.version == before_pointer.version + 1
        and SchedulingReleaseWithdrawal.objects.filter(**source).count()
        == before_withdrawals + 1
        and receipt.impact_document["withdrawal"] is not None
        and tuple(
            SchedulingReleaseArtifact.objects.filter(**source)
            .order_by("id")
            .values_list("id", "payload")
        )
        == before_artifacts
    )
    return {"state": "archived", "replayed": True, "receipt_id": str(result.receipt_id)}


def verify_stop_runtime(fixture):
    """Use the unchanged finite lease and independently read committed native state."""
    _require(fixture.scenario is not None and fixture._application_environment)
    fixture.refresh_workers()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_stop_scenario"],
            cwd=ROOT,
            env=fixture._application_environment,
            input=json.dumps({"setup": asdict(fixture.scenario)}, default=str),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=min(180, remaining_lease(fixture.deadline)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        _require(len(result.stdout) <= 4096)
        outcome = json.loads(result.stdout)
        if result.returncode != 0:
            stage = outcome.get("failure") if type(outcome) is dict else None
            _require(stage in _PHASES, "fixture_stop_process_failed")
            raise ProgrammeHttpsError("fixture_stop_failed_at_" + stage)
        _require(set(outcome) == {"state", "replayed", "receipt_id"})
        _require(outcome["state"] == "archived" and outcome["replayed"] is True)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ProgrammeHttpsError("fixture_stop_process_failed") from None
    with psycopg.connect(fixture.runtime.database_url, connect_timeout=5) as connection:
        _require(
            connection.execute("SELECT session_user, current_user").fetchone()
            == ("maru_runtime", "maru_runtime")
        )
        row = connection.execute(
            "SELECT e.lifecycle, e.aggregate_version, e.lifecycle_version, "
            "r.expected_aggregate_version, r.expected_lifecycle_version "
            "FROM public.events_eventedition e "
            "JOIN public.events_programmestopreceipt r ON r.edition_id = e.id "
            "WHERE r.id = %s AND r.organization_id = %s AND r.edition_id = %s",
            (
                outcome["receipt_id"],
                fixture.scenario.organization_id,
                fixture.scenario.edition_id,
            ),
        ).fetchone()
        _require(
            row is not None
            and row[0] == "archived"
            and row[1] == row[3] + 1
            and row[2] == row[4] + 1
        )
    return outcome


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 2
        result = prepare_stop_scenario(json.loads(raw))
    except Exception:  # noqa: BLE001 - no credentials or private source in child diagnostics.
        sys.stdout.write(json.dumps({"failure": _phase}))
        return 2
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
