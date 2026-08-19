import pytest
from django.test import Client
from django.urls import resolve, reverse

from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_platform_workflow_routes_do_not_shadow_specialist_records() -> None:
    assert reverse("baseline-admin-home") == "/admin/platform/organizations/"
    assert (
        reverse("baseline-create-organization") == "/admin/platform/organizations/new/"
    )
    assert (
        reverse("admin:organizations_organization_changelist")
        == "/admin/organizations/organization/"
    )
    assert resolve("/admin/platform/organizations/").url_name == "baseline-admin-home"
    assert (
        resolve("/admin/organizations/organization/").url_name
        == "organizations_organization_changelist"
    )


def test_platform_administrator_can_reach_the_step_by_step_workflow() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(administrator)

    response = client.get(reverse("baseline-admin-home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="platform-administration-home"' in content
    assert 'href="/admin/"' in content
    assert 'href="/admin/workspace/"' in content
    assert "Convention work" in content


def test_admin_home_exposes_searchable_platform_navigation_destinations() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(administrator)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count('id="nav-sidebar"') == 1
    assert content.count('id="nav-filter"') == 1
    assert "<h2>Platform</h2>" in content
    assert (
        'data-navigation-search="organizations find and continue setting up' in content
    )
    assert "organizers conventions tenants foundation platform" in content
    assert 'data-navigation-search="add organization create a new organizer' in content
    assert "new organizer convention tenant actions" in content
    assert 'value="platform.organizations"' in content
    assert 'data-navigation-kind="action"' in content
    assert 'href="/admin/platform/organizations/"' in content
    assert 'href="/admin/platform/organizations/new/"' in content
    assert "<span>Organizations</span>" in content
    assert "<span>Add organization</span>" in content
    assert 'class="maru-platform-navigation"' not in content
    assert 'class="baseline-sidebar-row"' not in content


def test_platform_workflow_uses_one_admin_shell_and_breadcrumb_trail() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(administrator)

    response = client.get(reverse("baseline-create-organization"))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count('class="maru-admin-brand"') == 1
    assert 'id="nav-sidebar"' in content
    assert 'class="breadcrumbs"' in content
    assert "Administration home" in content
    assert "Create organization" in content
    assert "core/baseline.css" in content
    assert 'class="baseline-header"' not in content
    assert '<aside class="baseline-sidebar">' not in content
    assert 'data-page="create-organization"' in content


def test_platform_navigation_flattens_the_exact_edition_context() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(name="Synthetic Maru Organizers")
    series = ConventionSeriesFactory(
        organization=organization,
        name="Synthetic Marucon",
    )
    edition = EventEditionFactory(
        organization=organization,
        series=series,
        name="Synthetic Marucon 2031",
    )
    client = Client()
    client.force_login(administrator)

    response = client.get(
        reverse(
            "baseline-event-edition-record",
            kwargs={
                "organization_slug": organization.slug,
                "series_slug": series.slug,
                "edition_slug": edition.slug,
            },
        )
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count('id="nav-filter"') == 1
    assert 'class="maru-platform-navigation"' not in content
    assert 'class="baseline-sidebar-row"' not in content
    assert "Synthetic Maru Organizers" in content
    assert "Synthetic Marucon" in content
    assert "Synthetic Marucon 2031" in content
    assert "Organization record" in content
    assert "Series record" in content
    assert "<span>Edition overview</span>" in content
    assert f'value="organization.{organization.id}.record"' in content
    assert f'value="series.{series.id}.record"' in content
    assert f'value="edition.{edition.id}.overview"' in content
    assert (
        f'href="/admin/platform/organizations/{organization.slug}/series/'
        f'{series.slug}/editions/{edition.slug}/"' in content
    )
    assert 'aria-current="page"' in content


def test_platform_workflow_renders_a_redirect_message_once() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(administrator)

    response = client.post(
        reverse("baseline-create-organization"),
        {"name": "Unified Shell Test Organizers"},
        follow=True,
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count("Unified Shell Test Organizers was created as a draft.") == 1
    assert content.count('class="baseline-messages"') == 1


def test_platform_navigation_is_hidden_from_ordinary_accounts() -> None:
    account = AccountFactory()
    client = Client()
    client.force_login(account)

    admin_response = client.get(reverse("admin:index"))
    platform_response = client.get(reverse("baseline-admin-home"))

    assert admin_response.status_code == 200
    admin_content = admin_response.content.decode()
    assert "Platform administration" not in admin_content
    assert admin_content.count('id="nav-filter"') == 1
    assert 'type="search"' in admin_content
    assert "Find a page" in admin_content
    assert platform_response.status_code == 403


def test_scoped_nonstaff_account_can_log_out_from_the_unified_admin_shell() -> None:
    account = AccountFactory()
    client = Client()
    client.force_login(account)

    response = client.post(reverse("admin:logout"))

    assert response.status_code == 302
    assert response.url == reverse("staff-login")
    assert "_auth_user_id" not in client.session
    admin_response = client.get(reverse("admin:index"))
    assert admin_response.status_code == 302
    assert admin_response.url.startswith(f"{reverse('staff-login')}?next=")


def test_scoped_nonstaff_account_can_use_admin_password_change_pages() -> None:
    account = AccountFactory()
    account.set_password("Initial-password-2026!")
    account.save(update_fields=["password"])
    client = Client()
    client.force_login(account)

    form_response = client.get(reverse("admin:password_change"))

    assert form_response.status_code == 200
    assert "Password change" in form_response.content.decode()

    change_response = client.post(
        reverse("admin:password_change"),
        {
            "old_password": "Initial-password-2026!",
            "new_password1": "Replacement-password-2026!",
            "new_password2": "Replacement-password-2026!",
        },
    )

    assert change_response.status_code == 302
    assert change_response.url == reverse("admin:password_change_done")
    assert "_auth_user_id" in client.session
    done_response = client.get(reverse("admin:password_change_done"))
    assert done_response.status_code == 200
    account.refresh_from_db()
    assert account.check_password("Replacement-password-2026!")
