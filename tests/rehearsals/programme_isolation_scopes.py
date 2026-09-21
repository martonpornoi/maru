"""Create genuine foreign and sibling foundations for integrated scope denial."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import scenario_from_document


@dataclass(frozen=True, slots=True)
class IsolationScopes:
    """Actual independently created native scopes, not authority or private content."""

    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    department_id: UUID
    sibling_edition_id: UUID
    sibling_department_id: UUID


def scopes_from_document(document, *, original):
    """Reject partial, aliased or original identities before constructing URLs."""
    if type(document) is not dict or set(document) != set(
        IsolationScopes.__annotations__
    ):
        raise ProgrammeHttpsError("fixture_isolation_scope_invalid")
    try:
        values = tuple(UUID(document[key]) for key in IsolationScopes.__annotations__)
    except (TypeError, ValueError, AttributeError):
        raise ProgrammeHttpsError("fixture_isolation_scope_invalid") from None
    if (
        any(
            str(value) != document[key] or not value.int
            for key, value in zip(IsolationScopes.__annotations__, values, strict=True)
        )
        or len(set(values)) != len(values)
        or set(values)
        & {
            original.organization_id,
            original.series_id,
            original.edition_id,
            original.department_id,
        }
    ):
        raise ProgrammeHttpsError("fixture_isolation_scope_invalid")
    return IsolationScopes(*values)


def prepare_isolation_scopes(fixture):
    """Use actual platform setup only to create distinct native scope targets."""
    fixture.refresh_workers()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_isolation_scopes"],
            cwd=ROOT,
            env=fixture._application_environment,
            input=json.dumps(
                {
                    "setup": asdict(fixture.scenario),
                    "administrator_password": fixture.material.administrator_password,
                },
                default=str,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=min(180, remaining_lease(fixture.deadline)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProgrammeHttpsError("fixture_isolation_setup_failed") from None
    if result.returncode or len(result.stdout) > 2048:
        raise ProgrammeHttpsError("fixture_isolation_setup_failed")
    try:
        scopes = scopes_from_document(
            json.loads(result.stdout), original=fixture.scenario
        )
    except ValueError:
        raise ProgrammeHttpsError("fixture_isolation_setup_failed") from None
    fixture.verify_excluded_state()
    return scopes


def _prepare(document):
    environment = require_programme_runtime_environment()
    if (
        type(document) is not dict
        or set(document) != {"setup", "administrator_password"}
        or type(document["administrator_password"]) is not str
        or not 32 <= len(document["administrator_password"]) <= 256
    ):
        raise ProgrammeHttpsError("fixture_isolation_input_invalid")
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from django.contrib.auth import authenticate  # noqa: PLC0415

    from maru.events.programme_setup import setup_programme_foundation  # noqa: PLC0415
    from maru.events.programme_setup_inputs import ProgrammeSetupInput  # noqa: PLC0415
    from maru.organizations.programme_setup_references import (  # noqa: PLC0415
        resolve_programme_setup_foundation,
    )

    administrator = authenticate(
        username=f"programme-platform-{environment.run_id}@example.invalid",
        password=document["administrator_password"],
    )
    if (
        administrator is None
        or not administrator.is_active
        or not administrator.is_platform_administrator
    ):
        raise ProgrammeHttpsError("fixture_isolation_administrator_unavailable")
    original = resolve_programme_setup_foundation(
        organization_id=setup.organization_id, series_id=setup.series_id
    )
    if original is None or original.representation_state != "active":
        raise ProgrammeHttpsError("fixture_isolation_foundation_unavailable")
    today = datetime.now(ZoneInfo("Europe/Budapest")).date()
    common = {
        "department_name": "Synthetic isolated Programme department",
        "starts_on": today + timedelta(days=30),
        "ends_on": today + timedelta(days=32),
        "time_zone": "Europe/Budapest",
        "reason": "Synthetic native scope-denial targets; no real convention.",
    }
    sibling = setup_programme_foundation(
        actor=administrator,
        details=ProgrammeSetupInput(
            **common,
            mode="existing_series",
            edition_name="Synthetic sibling isolation edition",
            organization_id=setup.organization_id,
            series_id=setup.series_id,
            foundation_fingerprint=original.fingerprint,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    foreign = setup_programme_foundation(
        actor=administrator,
        details=ProgrammeSetupInput(
            **common,
            mode="new_foundation",
            organization_name="Synthetic foreign isolation organizer",
            series_name="Synthetic foreign isolation series",
            edition_name="Synthetic foreign isolation edition",
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    # Deliberately incomplete foreign accountability is real retained setup state.
    # It supplies no roles and must not admit an unrelated original controller.
    return IsolationScopes(
        foreign.organization_id,
        foreign.series_id,
        foreign.edition_id,
        foreign.department_id,
        sibling.edition_id,
        sibling.department_id,
    )


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 2
        result = _prepare(json.loads(raw))
    except Exception:  # noqa: BLE001 - no credentials or source details leave a failed child.
        return 2
    sys.stdout.write(json.dumps(asdict(result), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
