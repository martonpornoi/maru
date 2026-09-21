"""Real independently owned objects for non-vacuous P12 mutation denials."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_isolation_scopes import scopes_from_document
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _activate_root,
    _create_person,
    approve_synthetic_role,
    person_from_document,
    scenario_from_document,
)


@dataclass(frozen=True, slots=True)
class IsolatedProgrammeObject:
    """Exact existing object and private synthetic owner, never portable authority."""

    organization_id: UUID
    edition_id: UUID
    item_id: UUID
    owner: SyntheticProgrammePerson = field(repr=False)


def objects_from_document(document, *, setup, scopes):
    """Require two distinct existing-object handles in the expected foreign scopes."""
    if type(document) is not list or len(document) != 2:
        raise ProgrammeHttpsError("fixture_object_reference_invalid")
    result = []
    for row, expected in zip(
        document,
        (
            (scopes.organization_id, scopes.edition_id),
            (setup.organization_id, scopes.sibling_edition_id),
        ),
        strict=True,
    ):
        if type(row) is not dict or set(row) != set(
            IsolatedProgrammeObject.__annotations__
        ):
            raise ProgrammeHttpsError("fixture_object_reference_invalid")
        try:
            identifiers = tuple(
                UUID(row[key]) for key in ("organization_id", "edition_id", "item_id")
            )
            owner = person_from_document(row["owner"])
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ProgrammeHttpsError("fixture_object_reference_invalid") from None
        if (
            identifiers[:2] != expected
            or any(not value.int for value in identifiers)
            or any(
                str(value) != row[key]
                for key, value in zip(
                    ("organization_id", "edition_id", "item_id"),
                    identifiers,
                    strict=True,
                )
            )
        ):
            raise ProgrammeHttpsError("fixture_object_reference_invalid")
        result.append(IsolatedProgrammeObject(*identifiers, owner))
    if (
        len({row.item_id for row in result}) != 2
        or len({row.owner.account_id for row in result}) != 2
    ):
        raise ProgrammeHttpsError("fixture_object_reference_invalid")
    return tuple(result)


def prepare_isolated_objects(fixture, scopes):
    """Complete only the two synthetic control scopes through independent owners."""
    require_programme_rehearsal_request()
    fixture.refresh_workers()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_object_preparation"],
            cwd=ROOT,
            env=fixture._application_environment,
            input=json.dumps(
                {
                    "setup": asdict(fixture.scenario),
                    "scopes": asdict(scopes),
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
        raise ProgrammeHttpsError("fixture_object_preparation_failed") from None
    if result.returncode or len(result.stdout) > 4096:
        raise ProgrammeHttpsError("fixture_object_preparation_failed")
    try:
        document = json.loads(result.stdout)
    except ValueError:
        raise ProgrammeHttpsError("fixture_object_preparation_failed") from None
    objects = objects_from_document(document, setup=fixture.scenario, scopes=scopes)
    fixture.verify_excluded_state()
    return objects


def _create_object(scope, owner, *, controllers):
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.programme.commands import create_organizer_core_item  # noqa: PLC0415
    from maru.programme.creation_queries import (  # noqa: PLC0415
        load_programme_creation_state,
    )
    from maru.programme.workbench_queries import (  # noqa: PLC0415
        ProgrammeWorkbenchRequest,
    )

    approve_synthetic_role(
        scope,
        people=controllers,
        recipient=owner,
        code="content",
        level=ScopeLevel.EDITION,
    )
    request = ProgrammeWorkbenchRequest(
        actor_id=owner.authenticate().id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=uuid4(),
    )
    creation = load_programme_creation_state(request)
    if not creation.writable:
        raise ProgrammeHttpsError("fixture_object_creation_unavailable")
    result = create_organizer_core_item(
        actor_id=request.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        kind="organizer_core",
        internal_title="Private foreign-scope mutation control",
        working_summary=(
            "Synthetic private text, never available to the original edition editor."
        ),
        expected_version=creation.control_version,
        reason="Synthetic P12 owned object for exact mutation isolation.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    return IsolatedProgrammeObject(
        scope.organization_id, scope.edition_id, result.item_id, owner
    )


def _prepare(document):
    environment = require_programme_runtime_environment()
    if (
        type(document) is not dict
        or set(document) != {"setup", "scopes", "administrator_password"}
        or type(document["administrator_password"]) is not str
        or not 32 <= len(document["administrator_password"]) <= 256
    ):
        raise ProgrammeHttpsError("fixture_object_input_invalid")
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    scopes = scopes_from_document(document["scopes"], original=setup)
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from django.contrib.auth import authenticate  # noqa: PLC0415

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
        raise ProgrammeHttpsError("fixture_object_administrator_unavailable")
    foreign = resolve_programme_setup_foundation(
        organization_id=scopes.organization_id, series_id=scopes.series_id
    )
    if foreign is None or foreign.representation_state == "active":
        raise ProgrammeHttpsError("fixture_object_foreign_setup_changed")
    controllers = tuple(
        _create_person(label, run_id=environment.run_id)
        for label in ("foreign-controller-a", "foreign-controller-b")
    )
    _activate_root(
        administrator,
        organization_id=scopes.organization_id,
        representation_id=foreign.representation_id,
        people=controllers,
    )
    return tuple(
        _create_object(
            SimpleNamespace(organization_id=organization, edition_id=edition),
            _create_person(label, run_id=environment.run_id),
            controllers=people,
        )
        for organization, edition, people, label in (
            (scopes.organization_id, scopes.edition_id, controllers, "foreign-content"),
            (
                setup.organization_id,
                scopes.sibling_edition_id,
                setup.controllers,
                "sibling-content",
            ),
        )
    )


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 2
        result = _prepare(json.loads(raw))
    except Exception:  # noqa: BLE001 - never echo synthetic credentials or private errors.
        return 2
    sys.stdout.write(json.dumps([asdict(row) for row in result], default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
