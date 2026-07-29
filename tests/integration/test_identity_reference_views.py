import pytest
from django.test import Client

from maru.identity.services import bootstrap_account, request_account_recovery

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

PASSWORD = "A-reference-client-password-482!"


def test_reference_identity_verification_and_recovery_views() -> None:
    account, verification = bootstrap_account(
        email="reference-identity@example.invalid",
        display_name="Reference Identity",
        password=PASSWORD,
        fingerprint="1" * 64,
    )
    assert account is not None
    assert verification.raw_token
    client = Client()

    page = client.get(
        "/accounts/verify-email/",
        {"token": verification.raw_token},
    )
    assert page.status_code == 200
    invalid = client.post(
        "/accounts/verify-email/",
        {"token": "invalid-token"},
    )
    assert invalid.status_code == 200
    assert b"invalid or has expired" in invalid.content
    verified = client.post(
        "/accounts/verify-email/",
        {"token": verification.raw_token},
    )
    assert verified.status_code == 302
    assert verified.url == "/register/"

    recovery = request_account_recovery(
        email=account.email,
        fingerprint="2" * 64,
    )
    assert recovery.raw_token
    recovery_page = client.get(
        "/accounts/recover-account/",
        {"token": recovery.raw_token},
    )
    assert recovery_page.status_code == 200
    mismatch = client.post(
        "/accounts/recover-account/",
        {
            "token": recovery.raw_token,
            "new_password": f"{PASSWORD}-new",
            "confirm_password": "different",
        },
    )
    assert mismatch.status_code == 200
    assert b"passwords do not match" in mismatch.content
    recovered = client.post(
        "/accounts/recover-account/",
        {
            "token": recovery.raw_token,
            "new_password": f"{PASSWORD}-new",
            "confirm_password": f"{PASSWORD}-new",
        },
    )
    assert recovered.status_code == 302
    assert recovered.url == "/register/"
