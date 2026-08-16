from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.identity.admin import AccountAdmin, IdentityChallengeAdmin
from maru.identity.models import Account, IdentityAbuseBucket, IdentityChallenge
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def platform_administrator() -> Account:
    return AccountFactory(
        email="admin-boundary@example.invalid",
        display_name="Synthetic Platform Administrator",
        is_staff=True,
        is_superuser=True,
    )


def test_generic_account_admin_has_no_writer_or_sensitive_domain_surface(
    platform_administrator: Account,
) -> None:
    model_admin = admin.site._registry[Account]

    assert isinstance(model_admin, AccountAdmin)
    assert model_admin.has_add_permission(None) is False  # type: ignore[arg-type]
    assert model_admin.has_change_permission(None) is False  # type: ignore[arg-type]
    assert model_admin.has_delete_permission(None) is False  # type: ignore[arg-type]
    assert model_admin.actions is None
    assert set(model_admin.fields or ()) == {
        "id",
        "email",
        "login_handle",
        "display_name",
        "preferred_language",
        "email_verified_at",
        "date_joined",
        "last_login",
    }
    assert set(model_admin.fields or ()).isdisjoint(
        {
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "account_kind",
            "groups",
            "user_permissions",
            "organizer_relationships",
            "registration_history",
        }
    )
    assert platform_administrator.account_kind == (Account.Kind.PLATFORM_ADMINISTRATOR)


def test_generic_account_admin_rejects_add_change_and_delete_posts(
    platform_administrator: Account,
) -> None:
    target = AccountFactory(
        email="inspection-target@example.invalid",
        login_handle="inspection.target",
        display_name="Inspection Target",
        is_active=True,
        is_staff=False,
    )
    original_password = target.password
    client = Client()
    client.force_login(platform_administrator)

    changelist = client.get(reverse("admin:identity_account_changelist"))
    add_url = reverse("admin:identity_account_add")
    change_url = reverse("admin:identity_account_change", args=(target.id,))
    delete_url = reverse("admin:identity_account_delete", args=(target.id,))
    change_page = client.get(change_url)

    assert changelist.status_code == 200
    assert "Add account" not in changelist.content.decode()
    assert change_page.status_code == 200
    content = change_page.content.decode()
    assert target.email in content
    assert target.password not in content
    for forbidden_name in (
        "password",
        "is_active",
        "is_staff",
        "is_superuser",
        "account_kind",
        "groups",
        "user_permissions",
    ):
        assert f'name="{forbidden_name}"' not in content
    assert "Organizer-managed relationships" not in content
    assert "Registration, ticket, and payment history" not in content

    forged = {
        "email": "changed-by-admin@example.invalid",
        "password": "forged-password",
        "is_active": "",
        "is_staff": "on",
        "is_superuser": "on",
        "account_kind": Account.Kind.PLATFORM_ADMINISTRATOR,
    }
    assert client.get(add_url).status_code == 403
    assert client.post(add_url, forged).status_code == 403
    assert client.post(change_url, forged).status_code == 403
    assert client.get(delete_url).status_code == 403
    assert client.post(delete_url, {"post": "yes"}).status_code == 403

    target.refresh_from_db()
    assert target.email == "inspection-target@example.invalid"
    assert target.password == original_password
    assert target.is_active is True
    assert target.is_staff is False
    assert not Account.objects.filter(email="changed-by-admin@example.invalid").exists()


def test_first_platform_administrator_bootstraps_through_the_manager_contract() -> None:
    account = Account.objects.create_superuser(
        email="first-platform-admin@example.invalid",
        password="Unique synthetic bootstrap password 2032!",
    )

    assert account.account_kind == Account.Kind.PLATFORM_ADMINISTRATOR
    assert account.is_active is True
    assert account.is_staff is True
    assert account.is_superuser is True
    assert account.has_usable_password() is True


def test_generic_challenge_admin_hides_c3_and_legacy_delivery_fields(
    platform_administrator: Account,
) -> None:
    challenge = IdentityChallenge.objects.create(
        account=platform_administrator,
        purpose=IdentityChallenge.Purpose.RECOVER_ACCOUNT,
        token_digest="1" * 64,
        email_snapshot=platform_administrator.email,
        expires_at=timezone.now() + timedelta(hours=1),
        request_fingerprint="2" * 64,
        delivery_status=IdentityChallenge.DeliveryStatus.PERMANENT_FAILED,
        delivery_attempt_count=7,
        delivery_error_code="legacy-field-must-not-render",
    )
    model_admin = admin.site._registry[IdentityChallenge]
    client = Client()
    client.force_login(platform_administrator)

    assert isinstance(model_admin, IdentityChallengeAdmin)
    assert set(model_admin.fields or ()).isdisjoint(
        {
            "token_digest",
            "request_fingerprint",
            "delivery_status",
            "delivery_attempt_count",
            "last_delivery_attempt_at",
            "delivered_at",
            "delivery_error_code",
        }
    )
    changelist = client.get(reverse("admin:identity_identitychallenge_changelist"))
    detail = client.get(
        reverse("admin:identity_identitychallenge_change", args=(challenge.id,))
    )

    assert changelist.status_code == 200
    assert detail.status_code == 200
    combined = changelist.content.decode() + detail.content.decode()
    assert challenge.token_digest not in combined
    assert challenge.request_fingerprint not in combined
    assert challenge.delivery_error_code not in combined
    assert "Delivery status" not in combined
    assert "Delivery attempt count" not in combined
    assert "does not assert delivery state" in detail.content.decode()


def test_acceptance_rejects_a_client_supplied_request_fingerprint() -> None:
    response = Client().post(
        reverse("accept-platform-account-invitation"),
        {
            "raw_token": "A" * 43,
            "new_password": "Synthetic recipient password 2032!",
            "confirm_password": "Synthetic recipient password 2032!",
            "retry_key": str(uuid4()),
            "request_fingerprint": "f" * 64,
        },
    )

    assert response.status_code == 400
    assert "Remove unsupported input fields" in response.content.decode()
    assert "f" * 64 not in response.content.decode()
    assert IdentityAbuseBucket.objects.exists() is False


def test_acceptance_passes_only_the_server_derived_request_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    server_fingerprint = "a" * 64

    def capture_acceptance(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        "maru.identity.invitation_views.accept_platform_account_invitation",
        capture_acceptance,
    )
    monkeypatch.setattr(
        "maru.identity.invitation_views.request_fingerprint",
        lambda _request: server_fingerprint,
    )

    response = Client().post(
        reverse("accept-platform-account-invitation"),
        {
            "raw_token": "A" * 43,
            "new_password": "Synthetic recipient password 2032!",
            "confirm_password": "Synthetic recipient password 2032!",
            "retry_key": str(uuid4()),
        },
    )

    assert response.status_code == 302
    assert captured["request_fingerprint"] == server_fingerprint
    assert "request_fingerprint" not in response.content.decode()
