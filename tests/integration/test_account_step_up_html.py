from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from maru.identity.models import Account, AccountSecurityEvent, AccountSession
from maru.identity.services import session_key_digest

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def platform_actor() -> Account:
    return Account.objects.create_superuser(
        email="step-up.operator@example.invalid",
        password="Synthetic-step-up-password-1!",
        display_name="Synthetic Step-up Operator",
    )


def _assert_private_no_store(response: object) -> None:
    cache_control = response["Cache-Control"]  # type: ignore[index]
    assert "private" in cache_control
    assert "no-store" in cache_control


def _next_from_redirect(response: object) -> str:
    location = response["Location"]  # type: ignore[index]
    return parse_qs(urlsplit(location).query)["next"][0]


def test_step_up_is_authenticated_closed_and_rejects_unsafe_return_urls(
    platform_actor: Account,
) -> None:
    route = reverse("account-step-up")
    anonymous = Client().get(route)
    assert anonymous.status_code == 302
    assert anonymous["Location"].startswith(reverse("staff-login"))

    client = Client()
    client.force_login(platform_actor)
    unsafe = client.get(route, {"next": "https://attacker.example.invalid/collect"})
    assert unsafe.status_code == 200
    assert unsafe.context["form"]["next"].value() == reverse("admin:index")
    _assert_private_no_store(unsafe)

    unknown_get = client.get(route, {"next": reverse("admin:index"), "debug": "1"})
    assert unknown_get.status_code == 400
    forged = client.post(
        route,
        {
            "password": "Synthetic-step-up-password-1!",
            "next": reverse("admin:index"),
            "privileged": "true",
        },
    )
    assert forged.status_code == 400
    assert "Remove unsupported input fields" in forged.content.decode()
    assert not AccountSession.objects.filter(
        account=platform_actor,
        step_up_verified_at__isnull=False,
    ).exists()


def test_step_up_records_current_session_and_never_replays_password(
    platform_actor: Account,
) -> None:
    route = reverse("account-step-up")
    destination = reverse("platform-account-inventory")
    client = Client()
    client.force_login(platform_actor)

    wrong_password = "Synthetic-wrong-password-must-not-render-1!"
    denied = client.post(
        route,
        {"password": wrong_password, "next": destination},
    )
    assert denied.status_code == 400
    assert wrong_password not in denied.content.decode()
    assert not AccountSecurityEvent.objects.filter(
        account=platform_actor,
        event_type=AccountSecurityEvent.EventType.STEP_UP_COMPLETED,
    ).exists()

    completed = client.post(
        route,
        {
            "password": "Synthetic-step-up-password-1!",
            "next": destination,
        },
    )
    assert completed.status_code == 302
    assert completed["Location"] == destination
    _assert_private_no_store(completed)
    session_key = client.session.session_key
    assert session_key
    session = AccountSession.objects.get(
        account=platform_actor,
        session_key_digest=session_key_digest(session_key),
    )
    assert session.step_up_verified_at is not None
    assert AccountSecurityEvent.objects.filter(
        account=platform_actor,
        event_type=AccountSecurityEvent.EventType.STEP_UP_COMPLETED,
    ).exists()


@override_settings(REQUIRE_PRIVILEGED_STEP_UP=True)
def test_invitation_mutation_redirects_before_parsing_then_accepts_input(
    platform_actor: Account,
) -> None:
    invite_route = reverse("platform-account-invite")
    step_up_route = reverse("account-step-up")
    sentinel = "private-body-value-must-not-be-read-before-step-up"
    client = Client()
    client.force_login(platform_actor)

    gated = client.post(invite_route, {sentinel: sentinel})
    assert gated.status_code == 302
    assert gated["Location"].startswith(step_up_route)
    assert _next_from_redirect(gated) == invite_route
    assert sentinel not in gated["Location"]
    _assert_private_no_store(gated)

    completed = client.post(
        step_up_route,
        {
            "password": "Synthetic-step-up-password-1!",
            "next": invite_route,
        },
    )
    assert completed.status_code == 302
    accepted_for_parsing = client.post(invite_route, {sentinel: sentinel})
    assert accepted_for_parsing.status_code == 400
    assert "Remove unsupported input fields" in accepted_for_parsing.content.decode()
