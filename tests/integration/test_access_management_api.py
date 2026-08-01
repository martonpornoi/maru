from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.commands import EXECUTIVE_BOARD_ROLE_CODE
from maru.authorization.models import RoleAssignment
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _grant(account: object, organization: object, capability_code: str) -> None:
    CapabilityGrantFactory(
        principal=account,
        organization=organization,
        capability_code=capability_code,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _client(account: object) -> APIClient:
    client = APIClient()
    client.force_login(account)
    return client


def _workspace_url(edition: object) -> str:
    return reverse(
        "api-edition-access-workspace",
        kwargs={
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
        },
    )


def _assignment_url(edition: object, assignment: object) -> str:
    return reverse(
        "api-edition-access-assignment",
        kwargs={
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
            "assignment_id": assignment.id,
        },
    )


def test_access_workspace_denies_without_leaking_people_or_groups() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )
    hidden_person = AccountFactory(email="hidden-person@example.invalid")
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=hidden_person,
        role_bundle=front_desk,
    )

    response = _client(account).get(_workspace_url(edition))

    assert response.status_code == 403
    assert "hidden-person@example.invalid" not in response.content.decode()
    denial = AuditEvent.objects.get(
        principal_id=account.id,
        operation="authorization.access_workspace.view",
    )
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.event_edition_id == edition.id


def test_access_workspace_is_tenant_scoped_and_uses_human_labels() -> None:
    edition = EventEditionFactory(name="Synthetic Gathering 2031")
    other_edition = EventEditionFactory(
        organization=edition.organization,
        series=edition.series,
    )
    other_tenant_edition = EventEditionFactory()
    manager = AccountFactory()
    _grant(manager, edition.organization, "authorization.manage_roles")
    old_front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Old Front Desk",
        version=1,
        capability_codes=["participation.view_staff_summary"],
    )
    front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        version=2,
        capability_codes=["participation.view_staff_summary"],
    )
    RoleBundleFactory(
        organization=edition.organization,
        code="registration-lead",
        name="Registration Lead",
        capability_codes=["registration.view_service_summary"],
    )
    board = RoleBundleFactory(
        organization=edition.organization,
        code="board-member",
        name="Board Member",
        capability_codes=["events.view_basic"],
    )
    authority_controller = RoleBundleFactory(
        organization=edition.organization,
        code="authority-controller",
        name="Authority Controller",
        capability_codes=["authorization.manage_roles"],
    )
    visible_person = AccountFactory(
        email="desk@example.invalid",
        display_name="Desk Coordinator",
    )
    organization_person = AccountFactory(display_name="Board Coordinator")
    hidden_person = AccountFactory(email="other-edition@example.invalid")
    foreign_person = AccountFactory(email="foreign@example.invalid")
    authority_person = AccountFactory(email="authority@example.invalid")
    foreign_role = RoleBundleFactory(
        organization=other_tenant_edition.organization,
        capability_codes=["events.view_basic"],
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=visible_person,
        role_bundle=front_desk,
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=None,
        principal=organization_person,
        role_bundle=board,
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=other_edition,
        principal=hidden_person,
        role_bundle=old_front_desk,
    )
    RoleAssignmentFactory(
        organization=edition.organization,
        edition=None,
        principal=authority_person,
        role_bundle=authority_controller,
    )
    RoleAssignmentFactory(
        organization=other_tenant_edition.organization,
        edition=other_tenant_edition,
        principal=foreign_person,
        role_bundle=foreign_role,
    )

    response = _client(manager).get(_workspace_url(edition))

    assert response.status_code == 200
    assert response.data["edition_name"] == "Synthetic Gathering 2031"
    assert response.data["can_revoke_assignments"] is False
    assert {group["name"] for group in response.data["groups"]} == {
        "Board",
        "Front Desk",
        "Registration",
    }
    assert {
        assignment["person_email"] for assignment in response.data["assignments"]
    } == {
        "desk@example.invalid",
        organization_person.email,
    }
    assert response.data["assignments"][0]["scope_label"]
    assert "foreign@example.invalid" not in response.content.decode()
    assert "other-edition@example.invalid" not in response.content.decode()
    assert "authority@example.invalid" not in response.content.decode()
    allowed_read = AuditEvent.objects.get(
        principal_id=manager.id,
        operation="authorization.access_workspace.view",
    )
    assert allowed_read.outcome == AuditEvent.Outcome.ALLOW
    assert allowed_read.safe_metadata["target_count"] == 2


def test_access_workspace_assigns_an_exact_existing_person_with_dual_control() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    approver = AccountFactory(email="approver@example.invalid")
    recipient = AccountFactory(
        email="volunteer@example.invalid",
        display_name="Helpful Volunteer",
    )
    _grant(actor, edition.organization, "authorization.manage_roles")
    _grant(approver, edition.organization, "authorization.manage_roles")
    front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )

    response = _client(actor).post(
        _workspace_url(edition),
        {
            "person_email": "VOLUNTEER@example.invalid",
            "group_code": "front-desk",
            "approver_email": approver.email,
            "reason": "Front Desk shift coordination.",
        },
        format="json",
    )

    assert response.status_code == 200
    assignment = RoleAssignment.objects.get(
        principal=recipient,
        role_bundle=front_desk,
        revoked_at__isnull=True,
    )
    assert assignment.edition == edition
    assert assignment.granted_by == actor
    assert assignment.approved_by == approver
    assert response.data["assignments"][0]["person_display_name"] == (
        "Helpful Volunteer"
    )
    assert response.data["assignments"][0]["group_name"] == "Front Desk"


def test_access_workspace_rejects_unknown_people_without_creating_access() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    _grant(actor, edition.organization, "authorization.manage_roles")
    _grant(approver, edition.organization, "authorization.manage_roles")
    RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )

    response = _client(actor).post(
        _workspace_url(edition),
        {
            "person_email": "missing@example.invalid",
            "group_code": "front-desk",
            "approver_email": approver.email,
            "reason": "Attempt to share with an unknown person.",
        },
        format="json",
    )

    assert response.status_code == 400
    assert str(response.data["errors"]["person_email"]) == (
        "No active account matches that exact email address."
    )
    assert not RoleAssignment.objects.filter(
        organization=edition.organization,
        edition=edition,
    ).exists()


def test_generic_access_workspace_hides_and_protects_executive_board() -> None:
    edition = EventEditionFactory()
    board = RoleBundleFactory(
        organization=edition.organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
        name="Executive Board",
        capability_codes=[
            "authorization.manage_roles",
            "authorization.revoke",
        ],
    )
    controllers = (AccountFactory(), AccountFactory())
    for index, controller in enumerate(controllers):
        RoleAssignmentFactory(
            organization=edition.organization,
            edition=None,
            principal=controller,
            role_bundle=board,
            approved_by=controllers[(index + 1) % len(controllers)],
        )
    shareable = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )
    reserved_target = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=AccountFactory(),
        role_bundle=board,
    )
    platform_administrator = AccountFactory(is_staff=True, is_superuser=True)

    for actor, approver in (
        (controllers[0], controllers[1]),
        (
            platform_administrator,
            AccountFactory(is_staff=True, is_superuser=True),
        ),
    ):
        client = _client(actor)
        workspace = client.get(_workspace_url(edition))
        assert workspace.status_code == 200
        assert EXECUTIVE_BOARD_ROLE_CODE not in {
            group["code"] for group in workspace.data["groups"]
        }
        assert EXECUTIVE_BOARD_ROLE_CODE not in {
            assignment["group_code"] for assignment in workspace.data["assignments"]
        }

        recipient = AccountFactory()
        share_response = client.post(
            _workspace_url(edition),
            {
                "person_email": recipient.email,
                "group_code": EXECUTIVE_BOARD_ROLE_CODE,
                "approver_email": approver.email,
                "reason": "Attempt to share reserved Board authority.",
            },
            format="json",
        )
        assert share_response.status_code == 400
        assert not RoleAssignment.objects.filter(
            organization=edition.organization,
            principal=recipient,
        ).exists()

        ordinary_assignment = RoleAssignmentFactory(
            organization=edition.organization,
            edition=edition,
            principal=AccountFactory(),
            role_bundle=shareable,
        )
        replace_with_board = client.patch(
            _assignment_url(edition, ordinary_assignment),
            {
                "group_code": EXECUTIVE_BOARD_ROLE_CODE,
                "approver_email": approver.email,
                "reason": "Attempt to replace ordinary access with Board authority.",
            },
            format="json",
        )
        assert replace_with_board.status_code == 400
        ordinary_assignment.refresh_from_db()
        assert ordinary_assignment.revoked_at is None

        replace_board = client.patch(
            _assignment_url(edition, reserved_target),
            {
                "group_code": "front-desk",
                "approver_email": approver.email,
                "reason": "Attempt to replace reserved Board authority.",
            },
            format="json",
        )
        assert replace_board.status_code == 403
        remove_board = client.delete(
            _assignment_url(edition, reserved_target),
            {"reason": "Attempt to remove reserved Board authority."},
            format="json",
        )
        assert remove_board.status_code == 403
        reserved_target.refresh_from_db()
        assert reserved_target.revoked_at is None


def test_access_replacement_removal_and_tenant_isolation() -> None:
    edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory(display_name="Registration Helper")
    _grant(actor, edition.organization, "authorization.manage_roles")
    _grant(actor, edition.organization, "authorization.revoke")
    _grant(approver, edition.organization, "authorization.manage_roles")
    front_desk = RoleBundleFactory(
        organization=edition.organization,
        code="front-desk",
        name="Front Desk",
        capability_codes=["participation.view_staff_summary"],
    )
    registration = RoleBundleFactory(
        organization=edition.organization,
        code="registration-lead",
        name="Registration Lead",
        capability_codes=["registration.view_service_summary"],
    )
    original = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=recipient,
        role_bundle=front_desk,
    )
    foreign_role = RoleBundleFactory(
        organization=foreign_edition.organization,
        capability_codes=["events.view_basic"],
    )
    foreign_assignment = RoleAssignmentFactory(
        organization=foreign_edition.organization,
        edition=foreign_edition,
        role_bundle=foreign_role,
    )
    client = _client(actor)

    foreign_response = client.delete(
        _assignment_url(edition, foreign_assignment),
        {"reason": "Attempt across tenants."},
        format="json",
    )
    assert foreign_response.status_code == 403
    foreign_assignment.refresh_from_db()
    assert foreign_assignment.revoked_at is None

    replace_response = client.patch(
        _assignment_url(edition, original),
        {
            "group_code": "registration-lead",
            "approver_email": approver.email,
            "reason": "Move this person to Registration.",
        },
        format="json",
    )
    assert replace_response.status_code == 200
    assert replace_response.data["can_revoke_assignments"] is True
    original.refresh_from_db()
    assert original.revoked_at is not None
    replacement = RoleAssignment.objects.get(
        organization=edition.organization,
        edition=edition,
        principal=recipient,
        role_bundle=registration,
        revoked_at__isnull=True,
    )
    assert {
        assignment["group_name"] for assignment in replace_response.data["assignments"]
    } == {"Registration"}

    remove_response = client.delete(
        _assignment_url(edition, replacement),
        {"reason": "Registration work is complete."},
        format="json",
    )
    assert remove_response.status_code == 200
    replacement.refresh_from_db()
    assert replacement.revoked_at is not None
    assert remove_response.data["assignments"] == []
