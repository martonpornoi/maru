"""Restore a genuinely stopped owned adoption and recheck retained authority."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from uuid import uuid4

from tests.rehearsals.programme_https import remaining_lease
from tests.rehearsals.programme_logical_restore import (
    _WORKER,
    ProgrammeLogicalRestoreError,
    _child,
    _require,
    _restored_database,
    _runtime_data_state,
)
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import scenario_from_document


def verify_stopped_logical_restore(fixture):
    """Restore only a new owned clone; preserve and compare the stopped source."""
    fixture.refresh_workers()
    fixture.verify_excluded_state()
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
                [sys.executable, "-m", "tests.rehearsals.programme_stopped_restore"],
                cwd=ROOT,
                env=fixture._application_environment | scope,
                input=json.dumps({"setup": asdict(fixture.scenario)}, default=str),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=min(180, remaining_lease(fixture.deadline)),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ProgrammeLogicalRestoreError(
                "stopped_restore_child_unavailable"
            ) from None
        _require(
            result.returncode == 0
            and result.stdout.strip() == "programme-stopped-restore-verified",
            "stopped_restore_scenario_failed",
        )
        _require(
            _runtime_data_state(fixture.runtime) == source_state,
            "stopped_restore_source_changed",
        )
    fixture.verify_excluded_state()


def _verify(document):
    require_programme_runtime_environment()
    _require(
        type(document) is dict and set(document) == {"setup"},
        "stopped_restore_input_invalid",
    )
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from django.core.exceptions import ValidationError  # noqa: PLC0415

    from maru.events.models import EventEdition, ProgrammeStopReceipt  # noqa: PLC0415
    from maru.events.programme_stop_commands import stop_programme  # noqa: PLC0415
    from maru.events.programme_stop_inputs import ProgrammeStopInput  # noqa: PLC0415
    from maru.events.programme_stop_receipt_queries import (  # noqa: PLC0415
        load_programme_stop_receipt,
    )
    from maru.events.services import transition_edition  # noqa: PLC0415
    from maru.scheduling.models import (  # noqa: PLC0415
        SchedulingReleaseArtifact,
        SchedulingReleasePointer,
    )

    actor = setup.controllers[0].authenticate()
    scope = {
        "actor_id": actor.id,
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
    }
    receipt = ProgrammeStopReceipt.objects.get(**scope)
    # Observe restored immutable values; do not construct new preview or authority.
    detail = load_programme_stop_receipt(
        **scope, receipt_id=receipt.id, correlation_id=uuid4()
    )
    _require(detail.receipt_id == receipt.id, "stopped_restore_receipt_changed")
    artifacts = tuple(
        SchedulingReleaseArtifact.objects.filter(
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
        )
        .order_by("id")
        .values_list("id", "payload")
    )
    retried = stop_programme(
        **scope,
        details=ProgrammeStopInput(
            receipt.expected_aggregate_version,
            receipt.expected_lifecycle_version,
            receipt.preview_fingerprint,
            receipt.reason,
        ),
        idempotency_key=receipt.idempotency_key,
        correlation_id=uuid4(),
    )
    _require(
        retried.receipt_id == receipt.id and retried.replayed,
        "stopped_restore_retry_changed",
    )
    try:
        transition_edition(
            actor=actor,
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            to_state="preparing",
            reason="Synthetic attempt cannot reopen stopped adoption.",
            correlation_id=uuid4(),
        )
    except ValidationError:
        pass
    else:
        raise ProgrammeLogicalRestoreError("stopped_restore_reopened")
    _require(
        EventEdition.objects.get(pk=setup.edition_id).lifecycle == "archived"
        and not SchedulingReleasePointer.objects.filter(
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            active_release_id__isnull=False,
        ).exists()
        and artifacts
        == tuple(
            SchedulingReleaseArtifact.objects.filter(
                organization_id=setup.organization_id,
                edition_id=setup.edition_id,
            )
            .order_by("id")
            .values_list("id", "payload")
        ),
        "stopped_restore_history_changed",
    )


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 2
        _verify(json.loads(raw))
    except Exception:  # noqa: BLE001 - final private child boundary never echoes input/secrets.
        return 2
    sys.stdout.write("programme-stopped-restore-verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
