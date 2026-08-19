from __future__ import annotations

import base64
import json
import smtplib
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db.models import F
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.identity.invitation_commands import create_platform_account_invitation
from maru.identity.invitation_crypto import InvitationPrivateKeyring
from maru.identity.invitation_delivery import (
    InvitationDeliveryMessage,
    deliver_platform_identity_invitation,
)
from maru.identity.models import (
    Account,
    AccountSession,
    PlatformAccountInventoryControl,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryReconciliationReceipt,
)
from maru.identity.services import STEP_UP_LIFETIME, session_key_digest
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import PositionAssignment

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_KEY_ID = "page10-reconciliation-html-key"
_PRIVATE_PROVIDER_DIAGNOSTIC = "private-provider-diagnostic-must-not-render"


class _InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "input":
            self.inputs.append({key: value or "" for key, value in attrs})


def _input_value(response: object, *, name: str, element_id: str) -> str:
    parser = _InputParser()
    parser.feed(response.content.decode())  # type: ignore[attr-defined]
    for item in parser.inputs:
        if item.get("name") == name and item.get("id") == element_id:
            return item.get("value", "")
    raise AssertionError(f"Input {name!r} with id {element_id!r} was not rendered.")


@pytest.fixture(autouse=True)
def inventory_control() -> PlatformAccountInventoryControl:
    control, _created = PlatformAccountInventoryControl.objects.get_or_create(
        singleton=True,
        defaults={"aggregate_version": 0},
    )
    return control


@pytest.fixture(scope="module")
def invitation_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65_537, key_size=2_048)


@pytest.fixture
def configured_invitation_crypto(
    settings: object,
    invitation_private_key: rsa.RSAPrivateKey,
) -> InvitationPrivateKeyring:
    public_key_pem = invitation_private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = _KEY_ID  # type: ignore[attr-defined]
    settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
        public_key_pem
    ).decode("ascii")
    settings.MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (  # type: ignore[attr-defined]
        "page10-reconciliation-html-digest"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {
            "page10-reconciliation-html-digest": base64.b64encode(b"u" * 32).decode(
                "ascii"
            )
        }
    )
    settings.MARU_PUBLIC_BASE_URL = "https://maru.example.invalid"  # type: ignore[attr-defined]
    return InvitationPrivateKeyring({_KEY_ID: invitation_private_key})


@pytest.fixture
def platform_actor() -> Account:
    return Account.objects.create_superuser(
        email="reconciliation.browser.operator@example.invalid",
        password="Synthetic-reconciliation-browser-password-1!",
        display_name="Synthetic Reconciliation Browser Operator",
    )


def _uncertain_delivery(
    *,
    actor: Account,
    keyring: InvitationPrivateKeyring,
    local_part: str,
) -> PlatformIdentityDelivery:
    invitation = create_platform_account_invitation(
        actor=actor,
        email=f"{local_part}@example.invalid",
        login_handle=f"{local_part}.handle",
        display_name="Synthetic Reconciliation Recipient",
        preferred_language="en",
        reason="Exercise the protected Page 10 reconciliation adapter.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    ).invitation
    delivery = PlatformIdentityDelivery.objects.get(
        challenge_id=invitation.current_challenge_id
    )

    def uncertain_adapter(_message: InvitationDeliveryMessage) -> str:
        raise smtplib.SMTPServerDisconnected(_PRIVATE_PROVIDER_DIAGNOSTIC)

    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=keyring,
            adapter=uncertain_adapter,
        )
        == PlatformIdentityDelivery.Status.RETRYING
    )
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
    return delivery


def _urls(delivery: PlatformIdentityDelivery) -> tuple[str, str, str]:
    invitation_id = delivery.invitation_id
    detail = reverse(
        "platform-account-invitation-detail",
        kwargs={"invitation_id": invitation_id},
    )
    delivered = reverse(
        "platform-identity-delivery-resolve-delivered",
        kwargs={
            "invitation_id": invitation_id,
            "delivery_id": delivery.id,
        },
    )
    retry = reverse(
        "platform-identity-delivery-resolve-retry",
        kwargs={
            "invitation_id": invitation_id,
            "delivery_id": delivery.id,
        },
    )
    return detail, delivered, retry


def _mark_current_session_step_up(
    client: Client,
    *,
    actor: Account,
    happened_at: datetime | None = None,
) -> None:
    key = client.session.session_key
    assert key is not None
    item = AccountSession.objects.get(
        account=actor,
        session_key_digest=session_key_digest(key),
    )
    item.step_up_verified_at = happened_at or timezone.now()
    item.save(update_fields=("step_up_verified_at", "updated_at"))


def _assert_no_convention_relationship(account: Account) -> None:
    assert not OrganizationMembership.objects.filter(account=account).exists()
    assert not Participation.objects.filter(account=account).exists()
    assert not Registration.objects.filter(account=account).exists()
    assert not PositionAssignment.objects.filter(account=account).exists()


def _assert_private_no_store(response: object) -> None:
    directives = {
        directive.strip().casefold()
        for directive in response["Cache-Control"].split(",")  # type: ignore[index]
    }
    assert {"private", "no-store"}.issubset(directives)


def test_reconciliation_routes_deny_by_default_before_using_submitted_values(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-denied",
    )
    _detail_url, delivered_url, _retry_url = _urls(delivery)
    submitted = {
        "expected_version": str(delivery.aggregate_version),
        "retry_key": str(uuid4()),
        "provider_reference": "provider-ref-denied",
        "reason": "This body must not cross the authorization boundary.",
    }

    anonymous = Client().post(delivered_url, submitted)
    assert anonymous.status_code == 302
    assert anonymous["Location"].startswith(reverse("staff-login"))

    ordinary = Account.objects.create_user(
        email="ordinary.reconciliation.browser@example.invalid",
        password="Synthetic-ordinary-browser-password-1!",
    )
    ordinary_client = Client()
    ordinary_client.force_login(ordinary)
    denied = ordinary_client.post(delivered_url, submitted)

    assert denied.status_code == 403
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
    assert not PlatformIdentityDeliveryReconciliationReceipt.objects.filter(
        delivery=delivery
    ).exists()


@pytest.mark.parametrize("expired", [False, True])
def test_reconciliation_requires_recent_step_up_before_parsing_body(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
    expired: bool,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part=f"reconcile-step-up-{expired}",
    )
    detail_url, _delivered_url, retry_url = _urls(delivery)
    client = Client()
    client.force_login(platform_actor)
    detail = client.get(detail_url)
    assert detail.status_code == 200
    if expired:
        _mark_current_session_step_up(
            client,
            actor=platform_actor,
            happened_at=timezone.now() - STEP_UP_LIFETIME - timedelta(seconds=1),
        )
    response = client.post(
        retry_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": str(uuid4()),
            "reason": "Provider acceptance was ruled out.",
            _PRIVATE_PROVIDER_DIAGNOSTIC: "must-not-be-parsed-or-reflected",
        },
    )

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account-step-up"))
    assert parse_qs(urlsplit(response["Location"]).query)["next"] == [
        reverse(
            "platform-account-invitation-detail",
            kwargs={"invitation_id": delivery.invitation_id},
        )
    ]
    assert _PRIVATE_PROVIDER_DIAGNOSTIC not in response["Location"]
    _assert_private_no_store(response)
    assert not PlatformIdentityDeliveryReconciliationReceipt.objects.filter(
        delivery=delivery
    ).exists()


def test_reconciliation_forms_are_post_only_csrf_protected_and_minimized(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-contract",
    )
    detail_url, delivered_url, retry_url = _urls(delivery)
    client = Client()
    client.force_login(platform_actor)
    detail = client.get(detail_url)

    assert detail.status_code == 200
    content = detail.content.decode()
    assert f"<dd>{delivery.aggregate_version}</dd>" in content
    assert "Confirm provider delivery" in content
    assert "Schedule controlled retry" in content
    assert _PRIVATE_PROVIDER_DIAGNOSTIC not in content
    assert "encrypted_payload" not in content
    assert "wrapped_data_key" not in content
    assert "synthetic-provider-private-value" not in content
    assert client.get(delivered_url).status_code == 405
    assert client.get(retry_url).status_code == 405
    _assert_private_no_store(detail)

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(platform_actor)
    csrf_client.get(detail_url)
    _mark_current_session_step_up(csrf_client, actor=platform_actor)
    csrf_denied = csrf_client.post(
        retry_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": str(uuid4()),
            "reason": "A CSRF-less command must fail.",
        },
    )
    assert csrf_denied.status_code == 403


def test_platform_operator_can_confirm_delivery_without_convention_relationship(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-delivered-html",
    )
    detail_url, delivered_url, _retry_url = _urls(delivery)
    client = Client()
    client.force_login(platform_actor)
    detail = client.get(detail_url)
    _mark_current_session_step_up(client, actor=platform_actor)
    retry_key = _input_value(
        detail,
        name="retry_key",
        element_id="id_delivery_delivered_retry_key",
    )
    response = client.post(
        delivered_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": retry_key,
            "provider_reference": "synthetic-provider-confirmation-html-1",
            "reason": "Confirmed acceptance in the synthetic provider console.",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == detail_url
    _assert_private_no_store(response)
    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.DELIVERED
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.provider_reference == "synthetic-provider-confirmation-html-1"
    rendered = client.get(detail_url).content.decode()
    assert "synthetic-provider-confirmation-html-1" not in rendered
    _assert_no_convention_relationship(platform_actor)
    _assert_no_convention_relationship(delivery.invitation.account)


def test_platform_operator_can_schedule_one_controlled_retry(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-retry-html",
    )
    detail_url, _delivered_url, retry_url = _urls(delivery)
    client = Client()
    client.force_login(platform_actor)
    detail = client.get(detail_url)
    _mark_current_session_step_up(client, actor=platform_actor)
    retry_key = _input_value(
        detail,
        name="retry_key",
        element_id="id_delivery_retry_retry_key",
    )
    response = client.post(
        retry_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": retry_key,
            "reason": "Confirmed that the provider did not accept this message.",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == detail_url
    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.RETRYING
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.next_retry_at is not None
    _assert_no_convention_relationship(platform_actor)
    _assert_no_convention_relationship(delivery.invitation.account)


def test_reconciliation_rejects_stale_version_and_replays_same_request(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    stale_delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-stale-html",
    )
    stale_version = stale_delivery.aggregate_version
    stale_detail_url, _delivered_url, stale_retry_url = _urls(stale_delivery)
    stale_client = Client()
    stale_client.force_login(platform_actor)
    stale_client.get(stale_detail_url)
    _mark_current_session_step_up(stale_client, actor=platform_actor)
    PlatformIdentityDelivery.objects.filter(id=stale_delivery.id).update(
        aggregate_version=F("aggregate_version") + 1
    )
    stale_response = stale_client.post(
        stale_retry_url,
        {
            "expected_version": str(stale_version),
            "retry_key": str(uuid4()),
            "reason": "This stale reconciliation must not be accepted.",
        },
    )
    assert stale_response.status_code == 409
    assert "The delivery changed after this form was opened" in (
        stale_response.content.decode()
    )
    assert not PlatformIdentityDeliveryReconciliationReceipt.objects.filter(
        delivery=stale_delivery
    ).exists()

    replay_delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-replay-html",
    )
    replay_detail_url, replay_delivered_url, _retry_url = _urls(replay_delivery)
    replay_client = Client()
    replay_client.force_login(platform_actor)
    replay_client.get(replay_detail_url)
    _mark_current_session_step_up(replay_client, actor=platform_actor)
    retry_key = uuid4()
    body = {
        "expected_version": str(replay_delivery.aggregate_version),
        "retry_key": str(retry_key),
        "provider_reference": "synthetic-provider-replay-html",
        "reason": "Confirm the same provider result idempotently.",
    }
    first = replay_client.post(replay_delivered_url, body)
    replay = replay_client.post(replay_delivered_url, body)

    assert first.status_code == 302
    assert replay.status_code == 302
    assert (
        PlatformIdentityDeliveryReconciliationReceipt.objects.filter(
            delivery=replay_delivery,
            retry_key=retry_key,
        ).count()
        == 1
    )


def test_reconciliation_forms_reject_malformed_and_unknown_fields(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _uncertain_delivery(
        actor=platform_actor,
        keyring=configured_invitation_crypto,
        local_part="reconcile-invalid-html",
    )
    detail_url, delivered_url, retry_url = _urls(delivery)
    client = Client()
    client.force_login(platform_actor)
    client.get(detail_url)
    _mark_current_session_step_up(client, actor=platform_actor)

    malformed = client.post(
        retry_url,
        {
            "expected_version": f"+{delivery.aggregate_version}",
            "retry_key": str(uuid4()),
            "reason": "A non-canonical version must fail.",
        },
    )
    unknown = client.post(
        retry_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": str(uuid4()),
            "reason": "Client-owned delivery state must fail.",
            "reconciliation_state": "resolved",
        },
    )
    submitted_provider_reference = "provider-reference-must-not-redisplay"
    invalid_delivered = client.post(
        delivered_url,
        {
            "expected_version": str(delivery.aggregate_version),
            "retry_key": str(uuid4()),
            "provider_reference": submitted_provider_reference,
            "reason": "",
        },
    )

    assert malformed.status_code == 400
    assert "base-10 digits only" in malformed.content.decode()
    assert unknown.status_code == 400
    assert "Remove unsupported input fields" in unknown.content.decode()
    assert invalid_delivered.status_code == 400
    assert submitted_provider_reference not in invalid_delivered.content.decode()
    assert not PlatformIdentityDeliveryReconciliationReceipt.objects.filter(
        delivery=delivery
    ).exists()
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
