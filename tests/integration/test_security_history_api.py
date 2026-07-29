import pytest
from django.test import Client
from rest_framework.test import APIClient

from maru.identity.models import AccountSecurityEvent
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_login_and_logout_appear_only_in_the_subject_security_history() -> None:
    account = AccountFactory(
        email="security-subject@example.invalid",
        password="synthetic-password",
    )
    other = AccountFactory()
    browser = Client()

    assert browser.login(
        email=account.email,
        password="synthetic-password",
    )
    browser.logout()

    assert list(
        AccountSecurityEvent.objects.filter(account=account).values_list(
            "event_type",
            flat=True,
        )
    ) == [
        AccountSecurityEvent.EventType.SIGN_OUT,
        AccountSecurityEvent.EventType.SIGN_IN,
    ]
    client = APIClient()
    client.force_authenticate(account)
    response = client.get("/api/v1/me/security-history")
    assert response.status_code == 200
    assert [item["event_type"] for item in response.json()] == [
        "sign_out",
        "sign_in",
    ]
    serialized = str(response.json())
    assert account.email not in serialized
    assert "password" not in serialized

    other_client = APIClient()
    other_client.force_authenticate(other)
    assert other_client.get("/api/v1/me/security-history").json() == []
