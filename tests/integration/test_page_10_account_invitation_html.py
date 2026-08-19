from __future__ import annotations

import base64
import json
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client
from django.urls import reverse

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import create_platform_account_invitation
from maru.identity.invitation_crypto import (
    EncryptedInvitationPayload,
    InvitationPrivateKeyring,
    decrypt_invitation_payload,
)
from maru.identity.invitation_delivery_payload import (
    decode_invitation_delivery_payload,
    invitation_delivery_aad,
)
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
)
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import PositionAssignment
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_PASSWORD = "Synthetic-Recipient-Owned-Password-7392!"
_KEY_ID = "page10-html-integration-key"


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


def _input_value(
    response: object,
    *,
    name: str,
    element_id: str | None = None,
) -> str:
    parser = _InputParser()
    parser.feed(response.content.decode())  # type: ignore[attr-defined]
    for item in parser.inputs:
        if item.get("name") == name and (
            element_id is None or item.get("id") == element_id
        ):
            return item.get("value", "")
    raise AssertionError(f"Input {name!r} was not rendered.")


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
) -> rsa.RSAPrivateKey:
    public_key_pem = invitation_private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = _KEY_ID  # type: ignore[attr-defined]
    settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
        public_key_pem
    ).decode("ascii")
    settings.MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (  # type: ignore[attr-defined]
        "page10-html-digest-key"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {"page10-html-digest-key": base64.b64encode(b"h" * 32).decode("ascii")}
    )
    return invitation_private_key


@pytest.fixture
def platform_actor() -> Account:
    return AccountFactory(
        email="page10.platform@example.invalid",
        display_name="Synthetic Platform Operator",
        is_staff=True,
        is_superuser=True,
    )


def _create_invitation(
    *,
    actor: Account,
    local_part: str,
) -> PlatformAccountInvitation:
    return create_platform_account_invitation(
        actor=actor,
        email=f"{local_part}@example.invalid",
        login_handle=f"{local_part}.handle",
        display_name="Synthetic Invited Person",
        preferred_language="en",
        reason="Exercise the governed Page 10 browser adapter.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    ).invitation


def _decrypt_token(
    invitation: PlatformAccountInvitation,
    private_key: rsa.RSAPrivateKey,
) -> str:
    invitation.refresh_from_db()
    challenge = IdentityChallenge.objects.get(id=invitation.current_challenge_id)
    delivery = PlatformIdentityDelivery.objects.get(challenge=challenge)
    assert delivery.encrypted_payload is not None
    assert delivery.wrapped_data_key is not None
    assert delivery.payload_nonce is not None
    envelope = EncryptedInvitationPayload(
        encryption_algorithm=delivery.encryption_algorithm,
        encryption_key_id=delivery.encryption_key_id,
        encrypted_payload=bytes(delivery.encrypted_payload),
        wrapped_data_key=bytes(delivery.wrapped_data_key),
        payload_nonce=bytes(delivery.payload_nonce),
        payload_aad_digest=delivery.payload_aad_digest,
    )
    plaintext = decrypt_invitation_payload(
        envelope=envelope,
        expected_aad=invitation_delivery_aad(
            invitation_id=invitation.id,
            challenge_id=challenge.id,
            invitation_version=challenge.invitation_version or 0,
            email=invitation.account.email,
        ),
        private_keyring=InvitationPrivateKeyring({_KEY_ID: private_key}),
    )
    return decode_invitation_delivery_payload(plaintext).raw_token


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


@pytest.mark.parametrize(
    "path_name",
    ["platform-account-inventory", "platform-account-invite"],
)
def test_platform_account_pages_redirect_anonymous_people_to_sign_in(
    path_name: str,
) -> None:
    path = reverse(path_name)
    response = Client().get(path)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('staff-login')}?next={path}"


def test_non_platform_account_cannot_read_or_submit_account_pages() -> None:
    ordinary = AccountFactory(email="ordinary.page10@example.invalid")
    client = Client()
    client.force_login(ordinary)

    inventory = client.get(reverse("platform-account-inventory"))
    invite_get = client.get(reverse("platform-account-invite"))
    invite_post = client.post(
        reverse("platform-account-invite"),
        {"email": "hidden@example.invalid"},
    )

    assert inventory.status_code == 403
    assert invite_get.status_code == 403
    assert invite_post.status_code == 403
    assert not Account.objects.filter(email="hidden@example.invalid").exists()


def test_accounts_and_invite_are_both_available_in_platform_navigation(
    platform_actor: Account,
) -> None:
    client = Client()
    client.force_login(platform_actor)

    response = client.get(reverse("platform-account-inventory"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="platform-account-inventory"' in content
    assert content.count(f'href="{reverse("platform-account-inventory")}"') >= 1
    assert f'href="{reverse("platform-account-invite")}"' in content
    assert f'href="{reverse("baseline-admin-home")}"' in content
    assert "<span>Accounts</span>" in content
    assert "<span>Invite account</span>" in content
    assert "<h1>User accounts</h1>" in content
    assert "Invite a user account" in content
    assert "Continue to organization setup" in content
    assert content.index("Current user accounts") < content.index("Search and filter")
    assert "Quick Start" not in content
    assert "a user account is not a convention role" in content.casefold()
    _assert_private_no_store(response)


def test_inventory_is_audited_and_renders_only_the_minimized_projection(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(
        actor=platform_actor,
        local_part="minimized-person",
    )
    challenge = IdentityChallenge.objects.get(invitation=invitation)
    client = Client()
    client.force_login(platform_actor)

    response = client.get(reverse("platform-account-inventory"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Synthetic Invited Person" in content
    assert "minimized-person@example.invalid" in content
    assert "minimized-person.handle" in content
    assert "Pending · version 1" in content
    for forbidden in (
        str(challenge.id),
        challenge.token_digest,
        "provider-secret-reference-must-not-render",
        "encrypted_payload",
        "request_fingerprint",
    ):
        assert forbidden not in content
    read_audit = AuditEvent.objects.get(operation="identity.account_inventory.read")
    assert read_audit.principal_id == platform_actor.id
    assert read_audit.organization_id is None
    assert read_audit.event_edition_id is None
    assert read_audit.safe_metadata["target_count"] >= 2


def test_inventory_rejects_unknown_filters_without_releasing_names(
    platform_actor: Account,
) -> None:
    hidden = AccountFactory(
        email="hidden-filter-result@example.invalid",
        display_name="Hidden Filter Result",
    )
    client = Client()
    client.force_login(platform_actor)

    response = client.get(
        reverse("platform-account-inventory"),
        {"contains": "Hidden Filter Result"},
    )

    assert response.status_code == 400
    content = response.content.decode()
    assert "Remove unsupported input fields" in content
    assert hidden.email not in content
    assert hidden.display_name not in content
    assert not AuditEvent.objects.filter(
        operation="identity.account_inventory.read"
    ).exists()


def test_failed_mandatory_read_audit_releases_no_account_labels(
    platform_actor: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden = AccountFactory(
        email="audit-hidden@example.invalid",
        display_name="Audit Hidden Person",
    )

    def fail_audit(_evidence: object) -> None:
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(
        "maru.identity.invitation_views.append_platform_account_read_audit",
        fail_audit,
    )
    client = Client()
    client.force_login(platform_actor)

    response = client.get(reverse("platform-account-inventory"))

    assert response.status_code == 503
    content = response.content.decode()
    assert hidden.email not in content
    assert hidden.display_name not in content
    assert "No account labels or partial results were released" in content


def test_invite_form_is_closed_and_creates_only_an_inactive_person_account(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    client = Client()
    client.force_login(platform_actor)
    form_page = client.get(reverse("platform-account-invite"))
    form_content = form_page.content.decode()
    assert "<h1>Invite a user account</h1>" in form_content
    assert "must accept this account invitation" in form_content
    retry_key = _input_value(form_page, name="retry_key")

    response = client.post(
        reverse("platform-account-invite"),
        {
            "email": "browser-invitee@example.invalid",
            "login_handle": "browser.invitee",
            "display_name": "Browser Invitee",
            "preferred_language": "en",
            "reason": "Prepare a synthetic recipient for the Page 10 journey.",
            "expected_version": "0",
            "retry_key": retry_key,
        },
    )

    invitation = PlatformAccountInvitation.objects.get(
        account__email="browser-invitee@example.invalid"
    )
    assert response.status_code == 302
    assert response["Location"] == reverse(
        "platform-account-invitation-detail",
        kwargs={"invitation_id": invitation.id},
    )
    detail = client.get(response["Location"])
    detail_content = detail.content.decode()
    assert "Recipient account acceptance" in detail_content
    assert "before their email can be used for an Executive Board appointment" in (
        detail_content
    )
    assert f'href="{reverse("baseline-admin-home")}"' in detail_content
    assert "Choose an organization" in detail_content
    _assert_private_no_store(response)
    account = invitation.account
    assert account.account_kind == Account.Kind.PERSON
    assert not account.is_active
    assert not account.is_staff
    assert not account.is_superuser
    assert account.email_verified_at is None
    assert not account.has_usable_password()
    _assert_no_convention_relationship(account)
    assert AuditEvent.objects.filter(
        operation="identity.account_invitation.create",
        target_id=invitation.id,
    ).exists()

    unknown_response = client.post(
        reverse("platform-account-invite"),
        {
            "email": "forged@example.invalid",
            "preferred_language": "en",
            "reason": "This must remain uncommitted.",
            "expected_version": "0",
            "retry_key": str(uuid4()),
            "organization_id": str(uuid4()),
        },
    )
    assert unknown_response.status_code == 400
    assert not Account.objects.filter(email="forged@example.invalid").exists()


def test_identity_conflict_message_is_non_enumerating(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    AccountFactory(email="occupied@example.invalid", login_handle="occupied")
    client = Client()
    client.force_login(platform_actor)
    form_page = client.get(reverse("platform-account-invite"))

    response = client.post(
        reverse("platform-account-invite"),
        {
            "email": "occupied@example.invalid",
            "login_handle": "free-handle",
            "display_name": "Synthetic Conflict",
            "preferred_language": "en",
            "reason": "Exercise the non-enumerating identity conflict.",
            "expected_version": "0",
            "retry_key": _input_value(form_page, name="retry_key"),
        },
    )

    assert response.status_code == 409
    content = response.content.decode()
    assert "cannot disclose which detail is unavailable" in content
    assert "already exists" not in content.casefold()
    assert Account.objects.filter(email="occupied@example.invalid").count() == 1


def test_detail_reissue_and_revoke_are_post_only_csrf_protected_prg_commands(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(
        actor=platform_actor,
        local_part="lifecycle-person",
    )
    detail_url = reverse(
        "platform-account-invitation-detail",
        kwargs={"invitation_id": invitation.id},
    )
    reissue_url = reverse(
        "platform-account-invitation-reissue",
        kwargs={"invitation_id": invitation.id},
    )
    revoke_url = reverse(
        "platform-account-invitation-revoke",
        kwargs={"invitation_id": invitation.id},
    )
    client = Client()
    client.force_login(platform_actor)

    detail = client.get(detail_url)
    assert detail.status_code == 200
    content = detail.content.decode()
    assert "lifecycle-person@example.invalid" in content
    assert "token_digest" not in content
    assert "wrapped_data_key" not in content
    _assert_private_no_store(detail)
    assert client.get(reissue_url).status_code == 405
    assert client.get(revoke_url).status_code == 405

    reissue_retry = _input_value(
        detail,
        name="retry_key",
        element_id="id_invitation_reissue_retry_key",
    )
    reissue_response = client.post(
        reissue_url,
        {
            "expected_version": "1",
            "retry_key": reissue_retry,
            "reason": "The recipient requested a fresh single-use code.",
        },
    )
    assert reissue_response.status_code == 302
    assert reissue_response["Location"] == detail_url
    invitation.refresh_from_db()
    assert invitation.aggregate_version == 2
    assert invitation.status == PlatformAccountInvitation.Status.PENDING

    refreshed_detail = client.get(detail_url)
    revoke_retry = _input_value(
        refreshed_detail,
        name="retry_key",
        element_id="id_invitation_revoke_retry_key",
    )
    revoke_response = client.post(
        revoke_url,
        {
            "expected_version": "2",
            "retry_key": revoke_retry,
            "reason": "The account invitation is no longer required.",
        },
    )
    assert revoke_response.status_code == 302
    assert revoke_response["Location"] == detail_url
    invitation.refresh_from_db()
    assert invitation.aggregate_version == 3
    assert invitation.status == PlatformAccountInvitation.Status.REVOKED

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(platform_actor)
    csrf_response = csrf_client.post(
        revoke_url,
        {
            "expected_version": "3",
            "retry_key": str(uuid4()),
            "reason": "A forged POST without CSRF must fail.",
        },
    )
    assert csrf_response.status_code == 403


def test_acceptance_uses_a_clean_fragment_contract_and_never_reflects_secrets(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(
        actor=platform_actor,
        local_part="fragment-person",
    )
    raw_token = _decrypt_token(invitation, configured_invitation_crypto)
    accept_url = reverse("accept-platform-account-invitation")
    client = Client()

    page = client.get(accept_url)
    assert page.status_code == 200
    content = page.content.decode()
    assert 'name="raw_token"' in content
    assert "account_invitation_fragment.js" in content
    assert '<meta name="referrer" content="same-origin">' in content
    assert '<meta name="referrer" content="no-referrer">' not in content
    assert raw_token not in content
    _assert_private_no_store(page)
    script = Path(
        "src/maru/identity/static/identity/account_invitation_fragment.js"
    ).read_text(encoding="utf-8")
    assert "window.location.hash" in script
    assert "#code=" in script
    assert "window.history.replaceState" in script
    assert "window.location.search" not in script

    query_response = client.get(accept_url, {"code": raw_token})
    assert query_response.status_code == 400
    assert raw_token not in query_response.content.decode()

    malicious_password = "Reflected-Malicious-Password-1!"
    malicious_response = client.post(
        accept_url,
        {
            "raw_token": raw_token,
            "new_password": malicious_password,
            "confirm_password": "different-password",
            "retry_key": raw_token,
            raw_token: "unknown-field-name",
        },
    )
    malicious_content = malicious_response.content.decode()
    assert malicious_response.status_code == 400
    assert raw_token not in malicious_content
    assert malicious_password not in malicious_content
    assert "Remove unsupported input fields." in malicious_content


def test_recipient_acceptance_activates_login_only_and_redirects_to_sign_in(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(
        actor=platform_actor,
        local_part="acceptance-person",
    )
    raw_token = _decrypt_token(invitation, configured_invitation_crypto)
    accept_url = reverse("accept-platform-account-invitation")
    client = Client(enforce_csrf_checks=True)
    form_page = client.get(accept_url)

    response = client.post(
        accept_url,
        {
            "csrfmiddlewaretoken": _input_value(form_page, name="csrfmiddlewaretoken"),
            "raw_token": raw_token,
            "new_password": _PASSWORD,
            "confirm_password": _PASSWORD,
            "retry_key": _input_value(form_page, name="retry_key"),
        },
        HTTP_ORIGIN="http://testserver",
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("staff-login")
    _assert_private_no_store(response)
    invitation.refresh_from_db()
    account = invitation.account
    account.refresh_from_db()
    assert invitation.status == PlatformAccountInvitation.Status.ACCEPTED
    assert account.is_active
    assert account.email_verified_at is not None
    assert account.check_password(_PASSWORD)
    assert not account.is_staff
    assert not account.is_superuser
    _assert_no_convention_relationship(account)

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_response = csrf_client.post(
        accept_url,
        {
            "raw_token": "x" * 43,
            "new_password": _PASSWORD,
            "confirm_password": _PASSWORD,
            "retry_key": str(UUID(int=1)),
        },
    )
    assert csrf_response.status_code == 403


def test_acceptance_form_validation_does_not_redisplay_code_or_passwords() -> None:
    raw_token = "A" * 43
    password = "Synthetic-Secret-That-Must-Not-Render-1!"

    response = Client().post(
        reverse("accept-platform-account-invitation"),
        {
            "raw_token": raw_token,
            "new_password": password,
            "confirm_password": "Synthetic-Different-Secret-2!",
            "retry_key": str(uuid4()),
        },
    )

    assert response.status_code == 400
    content = response.content.decode()
    assert raw_token not in content
    assert password not in content
    assert "The passwords do not match" in content
    _assert_private_no_store(response)
