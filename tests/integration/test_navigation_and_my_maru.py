from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.authorization.models import CapabilityGrant
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.identity.models import NavigationPin
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _client(account: object) -> Client:
    client = Client()
    client.force_login(account)
    return client


def test_default_login_enters_the_focused_my_maru_surface() -> None:
    password = "Safe local password 746!"
    account = AccountFactory()
    account.set_password(password)
    account.save(update_fields=("password",))
    client = Client()

    response = client.post(
        reverse("staff-login"),
        {"username": account.email, "password": password},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("my-maru-home")
    home = client.get(response["Location"])
    content = home.content.decode()
    assert home.status_code == 200
    assert "Registration &amp; tickets" in content
    assert "Shop &amp; orders" in content
    assert "My schedule" in content
    assert "Equipment offers" in content
    assert "Governance invitations" in content
    assert "Organizer tools appear only" in content
    assert 'aria-label="My Maru"' in content
    assert content.count('id="nav-sidebar"') == 1
    assert content.count('id="nav-filter"') == 1
    assert 'placeholder="Search tasks and records..."' in content
    assert "Start here" in content
    assert "More from Maru" in content
    assert content.count('value="my.registrations"') == 1
    assert content.count('value="my.catalog"') == 1
    assert content.count('value="my.schedule"') == 1
    assert content.count('value="my.equipment_offers"') == 1
    assert "Administration</strong>" not in content
    assert "Catalog commerce" not in content


def test_admin_navigation_is_task_first_searchable_and_keeps_explicit_context() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Synthetic Navigation Convention")
    client = _client(administrator)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Find a task or record" in content
    assert "Selected edition" not in content
    assert 'class="maru-admin-nav-section"' not in content
    assert (
        content.count(f'data-navigation-code="edition.{edition.id}.registration"') == 1
    )
    assert content.count(f'data-navigation-code="edition.{edition.id}.catalog"') == 1
    assert "Registration desk" in content
    assert content.count('data-navigation-code="work.workforce"') == 1
    assert f"{reverse('management-console')}?view=workforce" in content
    assert 'data-navigation-group="personal"' not in content
    assert "Customize navigation" in content
    assert edition.organization.name in content
    assert edition.series.name in content
    assert edition.name in content
    assert 'class="maru-edition-context-trail"' in content
    assert 'data-navigation-search="' in content


def test_navigation_pins_move_one_live_destination_without_duplicating_it() -> None:
    account = AccountFactory()
    client = _client(account)

    pinned = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.registrations",
            "action": "pin",
            "next": reverse("my-maru-home"),
        },
    )

    assert pinned.status_code == 302
    assert pinned["Location"] == reverse("my-maru-home")
    assert NavigationPin.objects.filter(
        account=account,
        destination_code="my.registrations",
    ).exists()
    content = client.get(reverse("my-maru-home")).content.decode()
    assert "Pinned" in content
    assert content.count('value="my.registrations"') == 1
    assert 'aria-label="Unpin Registration &amp; tickets"' in content

    unpinned = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.registrations",
            "action": "unpin",
            "next": "https://example.invalid/not-maru",
        },
    )
    assert unpinned.status_code == 302
    assert unpinned["Location"] == reverse("my-maru-home")
    assert not NavigationPin.objects.filter(account=account).exists()


def test_my_schedule_is_always_resolved_searchable_and_pinnable() -> None:
    account = AccountFactory()
    client = _client(account)

    index = client.get(reverse("my-maru-schedule-index"))

    assert index.status_code == 200
    content = index.content.decode()
    assert content.count('value="my.schedule"') == 1
    assert (
        'data-navigation-search="my schedule see your published convention' in content
    )
    assert "programme calendar events agenda personal" in content

    pinned = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.schedule",
            "action": "pin",
            "next": reverse("my-maru-schedule-index"),
        },
    )

    assert pinned.status_code == 302
    assert pinned["Location"] == reverse("my-maru-schedule-index")
    assert NavigationPin.objects.filter(
        account=account,
        destination_code="my.schedule",
    ).exists()
    pinned_content = client.get(reverse("my-maru-schedule-index")).content.decode()
    assert pinned_content.count('value="my.schedule"') == 1
    assert 'aria-label="Unpin My schedule"' in pinned_content


def test_equipment_offers_is_always_resolved_searchable_and_pinnable() -> None:
    account = AccountFactory()
    client = _client(account)

    index = client.get(reverse("my-logistics-offer-index"))

    assert index.status_code == 200
    content = index.content.decode()
    assert content.count('value="my.equipment_offers"') == 1
    assert 'data-navigation-search="equipment offers offer equipment' in content
    assert "assets inventory loan gear personal" in content

    pinned = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.equipment_offers",
            "action": "pin",
            "next": reverse("my-logistics-offer-index"),
        },
    )

    assert pinned.status_code == 302
    assert pinned["Location"] == reverse("my-logistics-offer-index")
    assert NavigationPin.objects.filter(
        account=account,
        destination_code="my.equipment_offers",
    ).exists()
    pinned_content = client.get(reverse("my-logistics-offer-index")).content.decode()
    assert pinned_content.count('value="my.equipment_offers"') == 1
    assert 'aria-label="Unpin Equipment offers"' in pinned_content


def test_logistics_navigation_requires_the_exact_edition_capability() -> None:
    account = AccountFactory(is_staff=True)
    edition = EventEditionFactory(name="Synthetic Logistics Navigation")
    client = _client(account)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()

    without_grant = client.get(reverse("admin:index"))
    assert without_grant.status_code == 200
    assert f"edition.{edition.id}.logistics" not in without_grant.content.decode()

    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code="logistics.view_workspace",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()
    with_grant = client.get(reverse("admin:index"))

    assert with_grant.status_code == 200
    content = with_grant.content.decode()
    assert content.count(f'value="edition.{edition.id}.logistics"') == 1
    assert content.count(">Logistics<") == 1


def test_revoked_destination_disappears_while_its_preference_remains_private() -> None:
    account = AccountFactory()
    edition = EventEditionFactory(name="Synthetic Revoked Navigation")
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code="workforce.view_structure",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    destination_code = f"edition.{edition.id}.structure"
    NavigationPin.objects.create(
        account=account,
        destination_code=destination_code,
    )
    client = _client(account)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()

    before = client.get(reverse("admin:index"))
    assert destination_code in before.content.decode()

    CapabilityGrant.objects.filter(id=grant.id).update(
        revoked_at=timezone.now(),
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic navigation revocation.",
    )
    after = client.get(reverse("admin:index"))

    assert after.status_code == 200
    assert destination_code not in after.content.decode()
    assert NavigationPin.objects.filter(
        account=account,
        destination_code=destination_code,
    ).exists()
    assert ADMIN_EDITION_SESSION_KEY not in client.session


def test_pin_endpoint_rejects_unknown_namespaces_and_extra_inputs() -> None:
    account = AccountFactory()
    client = _client(account)

    unknown = client.post(
        reverse("update-navigation-pin"),
        {"destination_code": "unknown.page", "action": "pin"},
    )
    extra = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.home",
            "action": "pin",
            "unexpected": "value",
        },
    )

    assert unknown.status_code == 404
    assert extra.status_code == 404
    assert not NavigationPin.objects.filter(account=account).exists()
