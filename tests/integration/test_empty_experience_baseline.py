import pytest
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import PositionAssignment, VolunteerApplication
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
)

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
def test_platform_administrator_reaches_the_platform_home() -> None:
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
    assert 'data-page="platform-administration-home"' in content
    assert "Organizations" in content
    assert 'aria-label="Platform administration"' in content
    assert 'class="baseline-sidebar-context"' not in content
    assert 'href="/admin/organizations/new/"' in content
    assert "+ Add" in content
    assert 'aria-current="page"' in content
    assert "No organizations yet" in content
    assert "Platform access, not participation" in content
    assert "Maru Administrator" in content
    assert "Convention work" not in content
    assert "Specialist records" not in content
    assert "Recent actions" not in content
    assert "Convention workspace" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize("is_staff", [False, True])
def test_non_platform_account_is_denied_the_platform_home(is_staff: bool) -> None:
    account = AccountFactory(is_staff=is_staff)
    client = APIClient()
    client.force_login(account)

    response = client.get("/admin/")

    assert response.status_code == 403


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_platform_home_lists_organizations_without_creating_relationships() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(name="Marucon Organizers", slug="marucon")
    series = ConventionSeriesFactory(organization=organization, name="Marucon")
    EventEditionFactory(
        organization=organization,
        series=series,
        name="Marucon 2031",
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Marucon Organizers" in content
    assert "Marucon 2031" not in content
    assert ">1</td>" in content
    assert OrganizationMembership.objects.filter(account=administrator).count() == 0
    assert Participation.objects.filter(account=administrator).count() == 0
    assert Registration.objects.filter(account=administrator).count() == 0
    assert CapabilityGrant.objects.filter(principal=administrator).count() == 0
    assert RoleAssignment.objects.filter(principal=administrator).count() == 0
    assert VolunteerApplication.objects.filter(account=administrator).count() == 0
    assert PositionAssignment.objects.filter(account=administrator).count() == 0


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_platform_home_has_a_safe_database_failure_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def unavailable_inventory() -> None:
        raise DatabaseError("synthetic unavailable database")

    monkeypatch.setattr(
        "maru.core.views.platform_organization_inventory",
        unavailable_inventory,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/")

    assert response.status_code == 503
    content = response.content.decode()
    assert "Organizations could not be loaded" in content
    assert "no convention data was changed" in content


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
