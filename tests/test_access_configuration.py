from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from maru.accounts.access_config import ensure_default_access_configuration
from maru.accounts.models import (
    AccessBenefit,
    AccessGrant,
    AccessRole,
    LabelOverride,
    RoleAssignment,
    RoleDefinition,
    UserConventionProfile,
    UserProfile,
)
from maru.accounts.permissions import label_for, user_benefit_keys
from maru.domain import ExportType, FursuiterStatus, PermissionKey, Role, TicketLevel
from maru.project_import import parse_project_yaml
from maru.projects.importer import import_project_setup
from maru.projects.models import ExportToken, Project


@pytest.mark.django_db
def test_default_access_configuration_contains_roles_benefits_and_labels() -> None:
    ensure_default_access_configuration()

    board = RoleDefinition.objects.get(project=None, key="board")
    assert PermissionKey.PROJECT_SETUP_MANAGE.value in board.permissions
    assert PermissionKey.ACCOUNTS_MANAGE.value not in board.permissions
    assert AccessBenefit.objects.filter(project=None, key="fursuit-lounge").exists()
    assert label_for("menu.forms") == "Forms"


@pytest.mark.django_db
def test_project_role_assignment_can_grant_forms_without_account_admin(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    user = _create_user("forms.lead@gmail.com", [Role.REGISTERED_USER.value])
    role = RoleDefinition.objects.create(
        project=project,
        key="forms-lead",
        name="Forms Lead",
        permissions=[PermissionKey.PROJECT_FORMS_MANAGE.value],
    )
    RoleAssignment.objects.create(project=project, role_definition=role, user=user)

    client.post(reverse("accounts:login"), {"email": user.email})

    response = client.get(reverse("projects:project_form_list", args=[project.slug]))
    assert response.status_code == 200
    assert client.get(reverse("accounts:access_grant_list")).status_code == 403


@pytest.mark.django_db
def test_project_labels_override_sidebar_words(client) -> None:
    call_command("seed_demo")
    project = Project.objects.get(slug="awoostria-2026")
    LabelOverride.objects.create(
        project=project,
        key="menu-forms",
        label="Applications",
    )

    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    response = client.get(reverse("projects:project_form_list", args=[project.slug]))

    assert response.status_code == 200
    assert "Applications" in response.content.decode()


@pytest.mark.django_db
def test_status_benefits_and_role_status_export_do_not_expose_email(client) -> None:
    call_command("seed_demo")
    ensure_default_access_configuration()
    project = Project.objects.get(slug="awoostria-2026")
    user = _create_user("fursuiter.status@gmail.com", [Role.REGISTERED_USER.value])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.display_name = "Public Fursuiter"
    profile.profile_unlocked = True
    profile.show_profile_publicly = True
    profile.save()
    UserConventionProfile.objects.create(
        user=user,
        project=project,
        ticket_level_selected=TicketLevel.SUPER_SPONSOR.value,
        ticket_level_verified=TicketLevel.SUPER_SPONSOR.value,
        fursuit_species="fox",
        fursuiter_status=FursuiterStatus.APPROVED.value,
    )
    token = ExportToken.objects.create(
        project=project,
        name="Role status",
        export_type=ExportType.ROLE_STATUS.value,
    )

    response = client.get(reverse("projects:role_status_export", args=[token.token]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Public Fursuiter" in content
    assert "fursuit-lounge" in user_benefit_keys(user, project)
    assert "fursuiter.status@gmail.com" not in content


@pytest.mark.django_db
def test_yaml_import_can_create_project_access_configuration() -> None:
    user = _create_user("registration.lead@gmail.com", [Role.REGISTERED_USER.value])
    config = parse_project_yaml(
        """
project:
  name: Role Import Con
  slug: role-import-con
  timezone: Europe/Vienna
  opens_at: "2026-07-22T10:00:00+02:00"
  closes_at: "2026-07-25T23:00:00+02:00"
accounts: []
roles:
  - key: registration-lead
    name: Registration Lead
    permissions: [project.registration.manage, project.statuses.manage]
role_assignments:
  - email: registration.lead@gmail.com
    role: registration-lead
benefits:
  - key: vip-line
    label: VIP Line
    target: check_in
status_benefits:
  - status_type: ticket_level
    status_value: Infinity
    benefit: vip-line
labels:
  - key: menu.forms
    label: Applications
hotels: []
event_groups: []
subprojects: []
"""
    )

    result = import_project_setup(config)

    project = result.project
    assert result.role_definitions == 1
    assert result.role_assignments == 1
    assert result.benefits == 1
    assert result.status_benefits == 1
    assert result.labels == 1
    assert RoleAssignment.objects.get(project=project).user == user
    assert label_for("menu.forms", project=project) == "Applications"


def _create_user(email: str, roles: list[str]):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=email,
        defaults={"email": email},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    grant, _ = AccessGrant.objects.update_or_create(
        email=email,
        defaults={"active": True},
    )
    for role in roles:
        AccessRole.objects.get_or_create(grant=grant, role=role)
    return user
