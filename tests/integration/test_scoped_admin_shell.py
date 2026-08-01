import re
from datetime import timedelta
from uuid import UUID

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.authorization.models import CapabilityGrant
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RepresentationAppointmentFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _client(account: object) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _selector_edition_ids(response: object) -> set[UUID]:
    return {
        UUID(value)
        for value in re.findall(
            r'<option\s+value="([0-9a-f-]{36})"',
            response.content.decode(),
        )
    }


def test_non_staff_board_controller_gets_scoped_shell_not_specialist_admin() -> None:
    controller = AccountFactory(is_staff=False)
    edition = EventEditionFactory(name="Synthetic Board Convention")
    foreign = EventEditionFactory(name="Foreign Board Convention")
    board_role = RoleBundleFactory(
        organization=edition.organization,
        code="executive-board",
        name="Executive Board",
        capability_codes=[
            "organizations.view_basic",
            "organizations.manage_representation",
            "organizations.create_series",
            "events.view_basic",
        ],
    )
    RoleAssignmentFactory(
        principal=controller,
        organization=edition.organization,
        role_bundle=board_role,
    )
    controller.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="identity",
            codename="view_account",
        )
    )
    client = _client(controller)

    home = client.get(reverse("admin:index"))
    workspace = client.get(reverse("management-console"))

    assert home.status_code == 200
    content = home.content.decode()
    assert "Maru Convention Planning" in content
    assert 'href="/admin/workspace/"' in content
    assert "Convention work" in content
    assert _selector_edition_ids(home) == {edition.id}
    assert "Specialist records" not in content
    assert "Platform administration" not in content
    assert f'href="{reverse("baseline-admin-home")}"' not in content
    assert f'href="{reverse("baseline-create-organization")}"' not in content
    organization_record_url = reverse(
        "baseline-organization-record",
        args=[edition.organization.slug],
    )
    representation_url = reverse(
        "organization-representation",
        args=[edition.organization.slug],
    )
    add_series_url = reverse(
        "baseline-create-convention-series",
        args=[edition.organization.slug],
    )
    assert f'href="{organization_record_url}"' in content
    assert f'href="{representation_url}"' in content
    assert f'href="{add_series_url}"' in content
    assert foreign.organization.name not in content
    assert foreign.organization.slug not in content
    assert workspace.status_code == 200
    assert 'data-mode="admin-embedded"' in workspace.content.decode()
    assert not controller.is_staff

    specialist_path = reverse("admin:identity_account_changelist")
    specialist = client.get(specialist_path)
    assert specialist.status_code == 302
    assert specialist["Location"] == f"/admin/login/?next={specialist_path}"

    assert (
        client.get(
            reverse(
                "baseline-organization-record",
                args=[edition.organization.slug],
            )
        ).status_code
        == 200
    )
    assert (
        client.get(
            reverse(
                "organization-representation",
                args=[edition.organization.slug],
            )
        ).status_code
        == 200
    )
    for route_name in (
        "baseline-organization-record",
        "organization-representation",
        "baseline-create-convention-series",
    ):
        assert (
            client.get(
                reverse(route_name, args=[foreign.organization.slug])
            ).status_code
            == 403
        )

    selected = client.post(
        reverse("admin-edition-context"),
        {"edition_id": str(edition.id), "next": reverse("admin:index")},
    )
    assert selected.status_code == 302
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(edition.id)


def test_invitation_only_account_gets_personal_landing_but_no_workspace() -> None:
    invitee = AccountFactory(is_staff=False)
    appointment = RepresentationAppointmentFactory(account=invitee)
    client = _client(invitee)

    home = client.get(reverse("admin:index"))
    invitations = client.get(reverse("my-representation-invitations"))
    workspace = client.get(reverse("management-console"))

    assert home.status_code == 200
    content = home.content.decode()
    assert "Your Maru account" in content
    assert "My governance invitations" in content
    assert "Convention workspace" not in content
    assert 'href="/admin/workspace/"' not in content
    assert invitations.status_code == 200
    assert appointment.representation.organization.name in invitations.content.decode()
    assert workspace.status_code == 403

    selection = client.post(
        reverse("admin-edition-context"),
        {
            "edition_id": str(EventEditionFactory().id),
            "next": reverse("admin:index"),
        },
    )
    assert selection.status_code == 403
    assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_scoped_organization_navigation_gates_each_action_by_capability() -> None:
    account = AccountFactory(is_staff=False)
    view_only = EventEditionFactory(name="View-only Synthetic Convention")
    representation_only = EventEditionFactory(
        name="Governance-only Synthetic Convention"
    )
    view_role = RoleBundleFactory(
        organization=view_only.organization,
        capability_codes=["organizations.view_basic"],
    )
    representation_role = RoleBundleFactory(
        organization=representation_only.organization,
        capability_codes=["organizations.manage_representation"],
    )
    RoleAssignmentFactory(
        principal=account,
        organization=view_only.organization,
        role_bundle=view_role,
    )
    RoleAssignmentFactory(
        principal=account,
        organization=representation_only.organization,
        role_bundle=representation_role,
    )
    client = _client(account)

    home = client.get(reverse("admin:index"))

    assert home.status_code == 200
    content = home.content.decode()
    view_record = reverse(
        "baseline-organization-record",
        args=[view_only.organization.slug],
    )
    view_representation = reverse(
        "organization-representation",
        args=[view_only.organization.slug],
    )
    view_add = reverse(
        "baseline-create-convention-series",
        args=[view_only.organization.slug],
    )
    governance_record = reverse(
        "baseline-organization-record",
        args=[representation_only.organization.slug],
    )
    governance_representation = reverse(
        "organization-representation",
        args=[representation_only.organization.slug],
    )

    assert f'href="{view_record}"' in content
    assert f'href="{view_record}#convention-series-title"' in content
    assert f'href="{view_representation}"' in content
    assert f'href="{view_add}"' not in content
    assert f'href="{governance_record}"' not in content
    assert f'href="{governance_representation}"' in content


def test_revoked_scope_removes_workspace_and_selector_without_staff_promotion() -> None:
    account = AccountFactory(is_staff=False)
    edition = EventEditionFactory()
    grant = CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        edition=edition,
    )
    CapabilityGrant.objects.filter(id=grant.id).update(
        revoked_at=timezone.now(),
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic scoped-shell revocation.",
    )
    client = _client(account)

    home = client.get(reverse("admin:index"))

    assert home.status_code == 200
    content = home.content.decode()
    assert "Your Maru account" in content
    assert "Convention workspace" not in content
    assert client.get(reverse("management-console")).status_code == 403
    assert (
        client.post(
            reverse("admin-edition-context"),
            {"edition_id": str(edition.id), "next": reverse("admin:index")},
        ).status_code
        == 403
    )
    assert not account.is_staff


def test_scoped_non_staff_selector_never_discloses_a_foreign_edition() -> None:
    account = AccountFactory(is_staff=False)
    authorized = EventEditionFactory(name="Authorized Synthetic Convention")
    foreign = EventEditionFactory(name="Foreign Synthetic Convention")
    CapabilityGrantFactory(
        principal=account,
        organization=authorized.organization,
        edition=authorized,
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    client = _client(account)

    home = client.get(reverse("admin:index"))

    assert home.status_code == 200
    assert _selector_edition_ids(home) == {authorized.id}
    denied = client.post(
        reverse("admin-edition-context"),
        {"edition_id": str(foreign.id), "next": reverse("admin:index")},
    )
    assert denied.status_code == 404
    assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_inactive_scoped_account_cannot_enter_the_management_shell() -> None:
    account = AccountFactory(is_staff=False)
    CapabilityGrantFactory(principal=account)
    client = _client(account)
    account.is_active = False
    account.save(update_fields=("is_active",))

    home = client.get(reverse("admin:index"))
    workspace = client.get(reverse("management-console"))

    assert home.status_code == 302
    assert home["Location"] == "/accounts/login/?next=/admin/"
    assert workspace.status_code == 302
    assert workspace["Location"] == "/accounts/login/?next=/admin/workspace/"
