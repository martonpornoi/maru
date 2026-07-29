import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tests.factories import AccountFactory, ParticipationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_staff_console_redirects_anonymous_users_to_local_login() -> None:
    response = APIClient().get("/staff/")

    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/?next=/staff/"


def test_local_login_explains_why_and_how_to_use_it() -> None:
    response = APIClient().get(reverse("staff-login"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Use this page to open the convention workspaces" in content
    assert "For example:" in content


def test_any_active_platform_account_can_open_staff_console() -> None:
    account = AccountFactory()
    client = APIClient()
    client.force_login(account)

    response = client.get("/staff/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "/static/staff-console/app.css" in content
    assert "/static/staff-console/app.js" in content
    assert "csrf-token" in content


def test_bootstrap_admin_without_a_workspace_lands_in_admin() -> None:
    administrator = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/staff/")

    assert response.status_code == 302
    assert response["Location"] == reverse("admin:index")


def test_bootstrap_admin_with_a_workspace_can_open_staff_console() -> None:
    administrator = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    ParticipationFactory(account=administrator)
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/staff/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "/static/staff-console/app.js" in content
    assert 'id="maru-admin-context-form"' in content
    assert f'action="{reverse("admin-edition-context")}"' in content


def test_local_login_lands_workspace_less_admin_in_bootstrap_admin() -> None:
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
            "next": "/staff/",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == reverse("admin:index")
    assert "Bootstrap administration" in response.content.decode()


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
            "next": "/staff/",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == "/staff/"
    assert client.session["_auth_user_id"] == str(account.id)
