"""Withdraw actual restored planner authority through ordinary owner commands."""

from uuid import uuid4

from tests.rehearsals.programme_release_preparation import _manifest, _require


def verify_restored_authority_revocation(setup, planning):
    """Prove restored credentials cannot bypass newly revoked exact assignments."""
    from maru.authorization.commands import revoke_role_assignment  # noqa: PLC0415
    from maru.authorization.models import RoleAssignment  # noqa: PLC0415
    from maru.authorization.policy import resolve_edition_target  # noqa: PLC0415
    from maru.scheduling.authorization import (  # noqa: PLC0415
        SchedulingAuthorizationDeniedError,
    )

    planner = planning.planner.authenticate()
    controller = setup.controllers[0].authenticate()
    target = resolve_edition_target(
        organization_id=setup.organization_id, edition_id=setup.edition_id
    )
    # Only this synthetic person's exact edition assignments. Organization,
    # Department/resource assignments and every other person remain untouched.
    assignments = tuple(
        RoleAssignment.objects.filter(
            organization_id=setup.organization_id,
            edition_id=setup.edition_id,
            principal_id=planner.id,
            department_id=None,
            resource_binding_id=None,
            revoked_at=None,
        )
        .order_by("id")
        .values_list("id", flat=True)[:17]
    )
    _require(4 <= len(assignments) <= 16, "restore_authority_inventory_invalid")
    for assignment_id in assignments:
        result = revoke_role_assignment(
            actor=controller,
            target=target,
            assignment_id=assignment_id,
            reason="Synthetic restored planner authority ended.",
            correlation_id=uuid4(),
            source_channel="programme_rehearsal",
        )
        _require(result.revoked_at is not None, "restore_authority_not_revoked")
    # Authenticate again with the same real credentials: successful identity is
    # not current source authority, even for retained historical release bytes.
    try:
        _manifest(setup, planning.planner)
    except SchedulingAuthorizationDeniedError:
        return
    raise RuntimeError("restore_revoked_authority_disclosed_release")
