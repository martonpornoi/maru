import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tests.factories import AccountFactory, CapabilityGrantFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.mark.parametrize("path", ["/staff/", "/manage/", "/admin/records/"])
def test_standalone_console_routes_are_removed(path: str) -> None:
    response = APIClient().get(path)

    assert response.status_code == 404


def test_admin_is_the_preferred_authenticated_route() -> None:
    anonymous = APIClient().get("/admin/")
    assert anonymous.status_code == 302
    assert anonymous["Location"] == "/accounts/login/?next=/admin/"

    account = AccountFactory()
    client = APIClient()
    client.force_login(account)
    response = client.get("/admin/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your Maru account" in content
    assert "My governance invitations" in content
    assert "Convention work" not in content
    assert "Specialist records" not in content
    assert "/static/staff-console/app.js" not in content


def test_workflows_are_embedded_under_the_original_admin_shell() -> None:
    anonymous = APIClient().get(reverse("management-console"))
    assert anonymous.status_code == 302
    assert anonymous["Location"] == ("/accounts/login/?next=/admin/workspace/")

    account = AccountFactory()
    CapabilityGrantFactory(principal=account)
    client = APIClient()
    client.force_login(account)
    response = client.get(reverse("management-console"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-mode="admin-embedded"' in content
    assert "/static/staff-console/app.css" in content
    assert "/static/staff-console/app.js" in content
    assert "csrf-token" in content
    assert "Convention work" in content
    assert "Workforce" in content
    assert f"{reverse('management-console')}?view=workforce" in content
    assert "maru-embedded-page-access-template" not in content
    assert '<details class="maru-access-summary' not in content
    assert response.context["maru_shell_access_rendered_by_page"] is True
    assert content.count('aria-label="Administration"') == 1
    assert 'aria-label="Management Console"' not in content


def test_local_login_explains_why_and_how_to_use_it() -> None:
    response = APIClient().get(reverse("staff-login"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Use this page to open the convention workspaces" in content
    assert "For example:" in content


def test_active_account_without_scope_gets_a_personal_admin_landing() -> None:
    account = AccountFactory()
    client = APIClient()
    client.force_login(account)

    response = client.get("/admin/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your Maru account" in content
    assert "Convention work" not in content
    assert "This account has no active convention-management authority" in content
    assert "My governance invitations" in content


def test_specialist_record_pages_keep_the_django_staff_boundary() -> None:
    account = AccountFactory(is_staff=False)
    client = APIClient()
    client.force_login(account)

    path = reverse("admin:identity_account_changelist")
    response = client.get(path)

    assert response.status_code == 302
    assert response["Location"] == f"/admin/login/?next={path}"


def test_bootstrap_admin_without_a_workspace_can_open_admin_workspace() -> None:
    administrator = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get(reverse("management-console"))

    assert response.status_code == 200
    assert b"/static/staff-console/app.js" in response.content


def test_ordinary_staff_with_a_workspace_can_open_admin_workspace() -> None:
    staff_account = AccountFactory(
        is_staff=True,
    )
    CapabilityGrantFactory(principal=staff_account)
    client = APIClient()
    client.force_login(staff_account)

    response = client.get(reverse("management-console"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "/static/staff-console/app.js" in content
    assert 'id="maru-admin-context-form"' in content
    assert '<input type="hidden" name="edition_id"' in content
    assert f'action="{reverse("admin-edition-context")}"' in content


def test_local_login_lands_workspace_less_admin_in_admin_workspace() -> None:
    password = "Safe local password 927!"
    administrator = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    administrator.set_password(password)
    administrator.save(update_fields=("password",))
    client = APIClient()

    response = client.post(
        reverse("staff-login"),
        {
            "username": administrator.email,
            "password": password,
            "next": "/admin/",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == "/admin/"
    assert "Convention work" in response.content.decode()


def test_local_login_accepts_non_admin_platform_account() -> None:
    password = "Safe local password 927!"
    account = AccountFactory()
    account.set_password(password)
    account.save(update_fields=("password",))
    client = APIClient()

    response = client.post(
        reverse("staff-login"),
        {
            "username": account.email,
            "password": password,
            "next": "/admin/",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == "/admin/"
    assert client.session["_auth_user_id"] == str(account.id)
