import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_baseline_redirects_to_its_only_authenticated_page() -> None:
    client = APIClient()

    root = client.get("/")
    home = client.get("/admin/")

    assert root.status_code == 302
    assert root["Location"] == "/admin/"
    assert home.status_code == 302
    assert home["Location"] == "/accounts/login/?next=/admin/"


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_baseline_sign_in_is_plain_and_focused() -> None:
    response = APIClient().get("/accounts/login/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sign in" in content
    assert "Email or username" in content
    assert "Use your Maru account to continue." in content
    assert "Convention work" not in content
    assert "Specialist records" not in content
    assert "Quick Start" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_first_administrator_reaches_an_empty_home() -> None:
    password = "Baseline local password 927!"
    administrator = AccountFactory(
        display_name="Maru Administrator",
        is_staff=True,
        is_superuser=True,
    )
    administrator.set_password(password)
    administrator.save(update_fields=("password",))
    client = APIClient()

    response = client.post(
        "/accounts/login/",
        {
            "username": administrator.email,
            "password": password,
            "next": "/admin/",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == "/admin/"
    content = response.content.decode()
    assert 'data-page="empty-admin-home"' in content
    assert "Nothing here yet" in content
    assert "one page" in content
    assert "Maru Administrator" in content
    assert "Convention work" not in content
    assert "Specialist records" not in content
    assert "Recent actions" not in content
    assert "Convention workspace" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_non_staff_account_is_denied_the_empty_admin_home() -> None:
    account = AccountFactory(is_staff=False)
    client = APIClient()
    client.force_login(account)

    response = client.get("/admin/")

    assert response.status_code == 403


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize(
    "path",
    [
        "/admin/workspace/",
        "/admin/identity/account/",
        "/register/",
        "/volunteer/00000000-0000-0000-0000-000000000000/",
        "/guardian-consent/",
        "/accounts/recover-account/",
    ],
)
def test_previous_browser_pages_are_not_mounted(path: str) -> None:
    response = APIClient().get(path)

    assert response.status_code == 404


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_health_and_versioned_api_foundation_remain_mounted() -> None:
    client = APIClient()

    assert client.get("/health/live").status_code == 200
    assert client.get("/api/v1/meta/build").status_code == 200
    assert client.get("/api/v1/public/editions").status_code == 200


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_sign_out_is_an_action_not_an_extra_page() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    get_response = client.get("/accounts/logout/")
    post_response = client.post("/accounts/logout/")

    assert get_response.status_code == 405
    assert post_response.status_code == 302
    assert post_response["Location"] == "/accounts/login/"
