"""Bounded real selected-room grant/revocation for the synthetic P12 journey."""

import json
import os
import subprocess
import sys
from uuid import UUID, uuid4

from tests.rehearsals.programme_change_scenario import change_sources
from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role


def _identifier(value):
    try:
        result = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ProgrammeHttpsError("fixture_delivery_authority_invalid") from None
    if not result.int or str(result) != value:
        raise ProgrammeHttpsError("fixture_delivery_authority_invalid")
    return result


def change_delivery_authority(fixture, sources, *, assignment_id=None):
    """Grant once or revoke that exact grant through the ordinary runtime owner."""
    require_programme_rehearsal_request()
    action = "grant" if assignment_id is None else "revoke"
    if assignment_id is not None:
        if type(assignment_id) is not UUID:
            raise ProgrammeHttpsError("fixture_delivery_authority_invalid")
        _identifier(str(assignment_id))
    fixture.refresh_workers()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_delivery_authority"],
            cwd=ROOT,
            env=fixture._application_environment,
            input=json.dumps(
                {
                    "sources": sources,
                    "action": action,
                    "assignment_id": str(assignment_id) if assignment_id else None,
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
        raise ProgrammeHttpsError("fixture_delivery_authority_failed") from None
    if result.returncode or len(result.stdout) > 256:
        raise ProgrammeHttpsError("fixture_delivery_authority_failed")
    try:
        document = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ProgrammeHttpsError("fixture_delivery_authority_failed") from None
    if (
        type(document) is not dict
        or set(document) != {"action", "assignment_id"}
        or document["action"] != action
    ):
        raise ProgrammeHttpsError("fixture_delivery_authority_failed")
    identifier = _identifier(document["assignment_id"])
    if assignment_id is not None and identifier != assignment_id:
        raise ProgrammeHttpsError("fixture_delivery_authority_failed")
    fixture.verify_excluded_state()
    return identifier


def _change(document):
    require_programme_runtime_environment()
    if (
        type(document) is not dict
        or set(document) != {"sources", "action", "assignment_id"}
        or document["action"] not in {"grant", "revoke"}
        or (document["action"] == "grant" and document["assignment_id"] is not None)
    ):
        raise ProgrammeHttpsError("fixture_delivery_authority_invalid")
    identifier = (
        _identifier(document["assignment_id"])
        if document["action"] == "revoke"
        else None
    )
    setup, _, _, _, planning, physical, _, _ = change_sources(document["sources"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.commands import revoke_role_assignment  # noqa: PLC0415
    from maru.authorization.models import RoleAssignment  # noqa: PLC0415
    from maru.authorization.policy import resolve_resource_target  # noqa: PLC0415
    from maru.authorization.programme_role_scope_choices import (  # noqa: PLC0415
        load_programme_role_scope_choices,
    )
    from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

    controller = setup.controllers[0].authenticate()
    choices = load_programme_role_scope_choices(
        actor=controller,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    matching = [
        row.scope
        for row in choices.choices
        if row.scope.level == ScopeLevel.RESOURCE
        and row.scope.department_id == setup.department_id
        and row.scope.resource_kind == "venue.edition_space"
        and row.scope.resource_binding_id
        == edition_space_binding_id(planning.room_ids[0])
    ]
    if len(matching) != 1:
        raise ProgrammeHttpsError("fixture_delivery_room_unavailable")
    scope = matching[0]
    if identifier is None:
        identifier = approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=physical.reviewer,
            code="run-sheet-delivery",
            level=scope.level,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
            resource_kind=scope.resource_kind,
        )
    else:
        # This test may end only its one purpose-specific synthetic grant. The
        # independent ordinary run-sheet grant and all other people stay intact.
        if not RoleAssignment.objects.filter(
            id=identifier,
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
            principal_id=physical.reviewer.account_id,
            role_bundle__code="programme-run-sheet-delivery",
            role_bundle__version=1,
            revoked_at=None,
        ).exists():
            raise ProgrammeHttpsError("fixture_delivery_assignment_unavailable")
        target = resolve_resource_target(
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
        )
        if target is None:
            raise ProgrammeHttpsError("fixture_delivery_room_unavailable")
        result = revoke_role_assignment(
            actor=controller,
            target=target,
            assignment_id=identifier,
            reason="Synthetic P12 selected-room delivery access ended.",
            correlation_id=uuid4(),
            source_channel="programme_rehearsal",
        )
        if result.id != identifier or result.revoked_at is None:
            raise ProgrammeHttpsError("fixture_delivery_revocation_failed")
    return {"action": document["action"], "assignment_id": str(identifier)}


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            return 2
        result = _change(json.loads(raw))
    except Exception:  # noqa: BLE001 - never expose credentials or private child errors.
        return 2
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
