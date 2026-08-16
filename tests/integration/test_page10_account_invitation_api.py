"""Strict API parity for Page 10 platform account invitations."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import (
    create_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_crypto import (
    EncryptedInvitationPayload,
    InvitationPrivateKeyring,
    decrypt_invitation_payload,
)
from maru.identity.invitation_delivery_payload import (
    INVITATION_TOKEN_LENGTH,
    decode_invitation_delivery_payload,
    invitation_delivery_aad,
)
from maru.identity.invitation_queries import (
    PlatformAccountInventoryLimitExceededError,
)
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformIdentityDelivery,
)
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import PositionAssignment
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_PASSWORD = "Synthetic-Recipient-Owned-Password-9471!"
_KEY_ID = "page10-api-integration-key"
_ACCOUNTS_URL = "/api/v1/platform/accounts"
_CREATE_URL = "/api/v1/platform/account-invitations"
_ACCEPT_URL = "/api/v1/public/account-invitations/accept"


class EchoingPasswordValidator:
    """Adversarial validator proving C4/C2 text never crosses the API."""

    def validate(self, password: str, user: Account | None = None) -> None:
        identity = "" if user is None else user.email
        raise ValidationError(
            f"Rejected password {password} for account {identity}.",
            code="echoing_password_validator",
        )

    def get_help_text(self) -> str:
        return "Use the synthetic adversarial password validator."


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


@pytest.fixture(autouse=True)
def configured_invitation_crypto(
    settings: object,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    public_key_pem = invitation_private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = _KEY_ID  # type: ignore[attr-defined]
    settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
        public_key_pem
    ).decode("ascii")
    settings.MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (  # type: ignore[attr-defined]
        "page10-api-digest-key"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {"page10-api-digest-key": base64.b64encode(b"a" * 32).decode("ascii")}
    )
    settings.REQUIRE_PRIVILEGED_STEP_UP = False  # type: ignore[attr-defined]


@pytest.fixture
def platform_actor() -> Account:
    return AccountFactory(
        email="page10.api.operator@example.invalid",
        display_name="Synthetic API Operator",
        is_staff=True,
        is_superuser=True,
    )


def _client(account: Account | None = None) -> APIClient:
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    return client


def _create_payload(*, local_part: str = "api.invitee", **changes: object):
    payload: dict[str, object] = {
        "email": f"{local_part}@example.invalid",
        "login_handle": f"{local_part}.handle",
        "display_name": "Synthetic Invited Person",
        "preferred_language": "en",
        "reason": "Exercise the governed Page 10 invitation API.",
        "expected_version": 0,
    }
    payload.update(changes)
    return payload


def _accept_payload(raw_token: str, *, password: str = _PASSWORD):
    return {
        "raw_token": raw_token,
        "new_password1": password,
        "new_password2": password,
    }


def _detail_url(invitation_id: UUID) -> str:
    return f"{_CREATE_URL}/{invitation_id}"


def _reissue_url(invitation_id: UUID) -> str:
    return f"{_detail_url(invitation_id)}/reissue"


def _revoke_url(invitation_id: UUID) -> str:
    return f"{_detail_url(invitation_id)}/revoke"


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
        reason="Exercise the governed Page 10 invitation API.",
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
    envelope = EncryptedInvitationPayload(
        encryption_algorithm=delivery.encryption_algorithm,
        encryption_key_id=delivery.encryption_key_id,
        encrypted_payload=bytes(delivery.encrypted_payload or b""),
        wrapped_data_key=bytes(delivery.wrapped_data_key or b""),
        payload_nonce=bytes(delivery.payload_nonce or b""),
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


def _without_request_id(response: object) -> dict[str, object]:
    body = dict(response.json())  # type: ignore[attr-defined]
    body.pop("request_id", None)
    return body


def _assert_no_convention_relationship(account: Account) -> None:
    assert not OrganizationMembership.objects.filter(account=account).exists()
    assert not Participation.objects.filter(account=account).exists()
    assert not Registration.objects.filter(account=account).exists()
    assert not PositionAssignment.objects.filter(account=account).exists()


def test_account_inventory_api_is_bounded_searchable_audited_and_paginated(
    platform_actor: Account,
) -> None:
    first = AccountFactory(
        email="inventory.alpha@example.invalid",
        login_handle="inventory.alpha",
        display_name="Synthetic Inventory Alpha",
    )
    second = AccountFactory(
        email="inventory.beta@example.invalid",
        login_handle="inventory.beta",
        display_name="Synthetic Inventory Beta",
    )
    query = {
        "search": "INVENTORY.",
        "search_mode": "prefix",
        "kind": "person",
        "state": "active",
        "page_size": 1,
    }
    client = _client(platform_actor)

    page_one = client.get(_ACCOUNTS_URL, query)
    assert page_one.status_code == 200
    first_body = page_one.json()
    assert set(first_body) == {"inventory_version", "items", "next_cursor"}
    assert len(first_body["items"]) == 1
    assert first_body["next_cursor"]
    assert set(first_body["items"][0]) == {
        "id",
        "email",
        "login_handle",
        "display_name",
        "kind",
        "active",
        "email_verified",
        "date_joined",
        "invitation",
    }

    page_two = client.get(
        _ACCOUNTS_URL,
        {**query, "cursor": first_body["next_cursor"]},
    )
    assert page_two.status_code == 200
    second_body = page_two.json()
    projected_ids = {
        first_body["items"][0]["id"],
        second_body["items"][0]["id"],
    }
    assert projected_ids == {str(first.id), str(second.id)}
    assert second_body["next_cursor"] is None
    assert "no-store" in page_one.headers["Cache-Control"]
    assert "no-store" in page_two.headers["Cache-Control"]
    assert (
        AuditEvent.objects.filter(
            operation="identity.account_inventory.read",
            source_channel="api",
        ).count()
        == 2
    )


def test_account_inventory_authorization_precedes_query_parsing() -> None:
    ordinary_person = AccountFactory()
    response = _client(ordinary_person).get(
        f"{_ACCOUNTS_URL}?page_size=not-an-integer&password=secret"
    )
    assert response.status_code == 403
    assert response.json()["code"] == "platform_administration_required"
    assert response.json()["detail"] == (
        "Platform account invitations are unavailable."
    )


@pytest.mark.parametrize(
    ("query", "expected_code"),
    [
        ({"unknown": "value"}, "unknown_input_field"),
        ({"search": "x"}, "search_length_invalid"),
        ({"page_size": "101"}, "max_value"),
        ({"page_size": "1.5"}, "invalid"),
    ],
)
def test_account_inventory_rejects_closed_or_out_of_bounds_query_input(
    platform_actor: Account,
    query: dict[str, str],
    expected_code: str,
) -> None:
    response = _client(platform_actor).get(_ACCOUNTS_URL, query)
    assert response.status_code == 400
    assert response.json()["code"] == expected_code
    assert response.headers["Content-Type"].startswith("application/problem+json")


def test_account_inventory_rejects_duplicate_query_parameters(
    platform_actor: Account,
) -> None:
    response = _client(platform_actor).get(
        f"{_ACCOUNTS_URL}?state=active&state=inactive"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "duplicate_query_parameter"


def test_account_inventory_normalizes_whitespace_search_to_blank(
    platform_actor: Account,
) -> None:
    response = _client(platform_actor).get(_ACCOUNTS_URL, {"search": "   "})
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(platform_actor.id)


def test_account_inventory_stale_cursor_and_limit_are_name_free_conflicts(
    platform_actor: Account,
) -> None:
    AccountFactory(email="cursor.first@example.invalid")
    AccountFactory(email="cursor.second@example.invalid")
    client = _client(platform_actor)
    first_page = client.get(_ACCOUNTS_URL, {"page_size": 1})
    assert first_page.status_code == 200
    cursor = first_page.json()["next_cursor"]
    assert cursor
    AccountFactory(email="cursor.movement@example.invalid")

    stale = client.get(_ACCOUNTS_URL, {"page_size": 1, "cursor": cursor})
    assert stale.status_code == 409
    assert stale.json()["code"] == "account_inventory_cursor_stale"

    with patch(
        "maru.identity.invitation_api.load_platform_account_inventory",
        side_effect=PlatformAccountInventoryLimitExceededError(
            "synthetic protected identity must not escape"
        ),
    ):
        limited = client.get(_ACCOUNTS_URL)
    assert limited.status_code == 409
    assert limited.json()["code"] == "account_inventory_limit_exceeded"
    assert "synthetic protected identity" not in limited.content.decode()


def test_account_inventory_audit_failure_releases_no_partial_identity(
    platform_actor: Account,
) -> None:
    protected = AccountFactory(
        email="inventory.audit.private@example.invalid",
        login_handle="inventory-audit-private",
        display_name="Inventory Audit Private",
    )
    with patch(
        "maru.identity.invitation_api.append_platform_account_read_audit",
        side_effect=DatabaseError("synthetic audit outage"),
    ):
        response = _client(platform_actor).get(_ACCOUNTS_URL)
    assert response.status_code == 503
    text = response.content.decode()
    assert protected.email not in text
    assert protected.login_handle not in text
    assert protected.display_name not in text


def test_create_and_replay_return_minimized_resources_without_relationships(
    platform_actor: Account,
) -> None:
    client = _client(platform_actor)
    retry_key = uuid4()
    payload = _create_payload()

    created = client.post(
        _CREATE_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replayed = client.post(
        _CREATE_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert set(created.json()) == {
        "id",
        "status",
        "aggregate_version",
        "expires_at",
        "replayed",
    }
    assert created.json()["replayed"] is False
    assert replayed.json() == {**created.json(), "replayed": True}
    assert "no-store" in created.headers["Cache-Control"]
    assert "no-store" in replayed.headers["Cache-Control"]
    assert PlatformAccountInvitation.objects.count() == 1
    assert PlatformAccountInvitationCommandReceipt.objects.count() == 1

    invitation = PlatformAccountInvitation.objects.select_related("account").get()
    assert invitation.status == PlatformAccountInvitation.Status.PENDING
    assert not invitation.account.is_active
    assert not invitation.account.has_usable_password()
    _assert_no_convention_relationship(invitation.account)
    delivery = PlatformIdentityDelivery.objects.get(invitation=invitation)
    assert delivery.encrypted_payload
    assert "raw_token" not in created.json()
    assert "password" not in created.content.decode().casefold()


def test_platform_authority_precedes_header_and_json_parsing() -> None:
    ordinary_person = AccountFactory()
    client = _client(ordinary_person)
    malformed = client.generic(
        "POST",
        _CREATE_URL,
        data=b'{"email":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    nonexistent = client.generic(
        "POST",
        _reissue_url(uuid4()),
        data=b'{"expected_version":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )

    for response in (malformed, nonexistent):
        assert response.status_code == 403
        assert response.json()["code"] == "platform_administration_required"
        assert response.json()["detail"] == (
            "Platform account invitations are unavailable."
        )
        assert "no-store" in response.headers["Cache-Control"]
    assert not PlatformAccountInvitation.objects.exists()


def test_step_up_precedes_header_and_body_when_required(
    platform_actor: Account,
    settings: object,
) -> None:
    settings.REQUIRE_PRIVILEGED_STEP_UP = True  # type: ignore[attr-defined]
    response = _client(platform_actor).generic(
        "POST",
        _CREATE_URL,
        data=b'{"email":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    assert response.status_code == 403
    assert response.json()["code"] == "step_up_required"


def test_protected_session_api_requires_csrf_and_accepts_its_exact_token(
    platform_actor: Account,
) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(platform_actor)
    denied = client.generic(
        "POST",
        _CREATE_URL,
        data=b'{"email":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"
    assert not PlatformAccountInvitation.objects.exists()

    csrf_token = client.get("/api/v1/public/csrf").json()["csrf_token"]
    accepted = client.post(
        _CREATE_URL,
        data=json.dumps(_create_payload(local_part="csrf-protected")),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert accepted.status_code == 201


@pytest.mark.parametrize(
    ("header", "expected_code"),
    [
        (None, "missing_idempotency_key"),
        (" ", "missing_idempotency_key"),
        ("not-a-uuid", "invalid_idempotency_key"),
        ("A6A8A503-95A9-4F38-8767-1BB24C84B406", "invalid_idempotency_key"),
        ("{" + str(uuid4()) + "}", "invalid_idempotency_key"),
        (" " + str(uuid4()) + " ", "invalid_idempotency_key"),
    ],
)
def test_create_requires_one_canonical_header_before_body(
    platform_actor: Account,
    header: str | None,
    expected_code: str,
) -> None:
    kwargs = {} if header is None else {"HTTP_IDEMPOTENCY_KEY": header}
    response = _client(platform_actor).generic(
        "POST",
        _CREATE_URL,
        data=b'{"email":',
        content_type="application/json",
        **kwargs,
    )
    assert response.status_code == 400
    assert response.json()["code"] == expected_code
    assert "Idempotency-Key" in response.json()["errors"]


@pytest.mark.parametrize(
    "changes",
    [
        {"retry_key": str(uuid4())},
        {"actor_id": str(uuid4())},
        {"is_active": True},
        {"expected_version": "0"},
        {"preferred_language": ""},
        {"email": 42},
    ],
)
def test_create_rejects_unknown_server_owned_and_coerced_fields(
    platform_actor: Account,
    changes: dict[str, object],
) -> None:
    response = _client(platform_actor).post(
        _CREATE_URL,
        _create_payload(local_part=f"invalid-{uuid4().hex}", **changes),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert not PlatformAccountInvitation.objects.exists()


def test_protected_invitation_mutation_accepts_json_only_without_reflection(
    platform_actor: Account,
) -> None:
    protected_email = "wrong-media-private@example.invalid"
    response = _client(platform_actor).generic(
        "POST",
        _CREATE_URL,
        data=(f"email={protected_email}&expected_version=0").encode(),
        content_type="application/x-www-form-urlencoded",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 415
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert protected_email not in response.content.decode()
    assert not PlatformAccountInvitation.objects.exists()


def test_changed_retry_and_identity_conflicts_are_non_disclosing(
    platform_actor: Account,
) -> None:
    client = _client(platform_actor)
    retry_key = uuid4()
    payload = _create_payload(local_part="retry-conflict")
    assert (
        client.post(
            _CREATE_URL,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(retry_key),
        ).status_code
        == 201
    )
    changed_retry = client.post(
        _CREATE_URL,
        {**payload, "reason": "A changed reason must not reuse the key."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )

    AccountFactory(
        email="reserved-email@example.invalid",
        login_handle="reserved.handle",
    )
    email_conflict = client.post(
        _CREATE_URL,
        _create_payload(
            local_part="email-candidate",
            email="RESERVED-EMAIL@example.invalid",
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    handle_conflict = client.post(
        _CREATE_URL,
        _create_payload(
            local_part="handle-candidate",
            login_handle="RESERVED.HANDLE",
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert changed_retry.status_code == 409
    assert changed_retry.json()["code"] == "account_invitation_retry_conflict"
    assert email_conflict.status_code == handle_conflict.status_code == 409
    assert _without_request_id(email_conflict) == _without_request_id(handle_conflict)
    conflict_text = email_conflict.content.decode()
    assert "reserved-email" not in conflict_text
    assert "reserved.handle" not in conflict_text


def test_detail_is_bounded_audited_and_contains_no_bearer_secret(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-detail")
    raw_token = _decrypt_token(invitation, invitation_private_key)

    response = _client(platform_actor).get(_detail_url(invitation.id))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "inventory_version",
        "id",
        "account",
        "status",
        "aggregate_version",
        "expires_at",
        "created_at",
        "last_transition_at",
        "created_by",
        "delivery",
        "transitions",
        "delivery_attempts",
    }
    assert body["account"]["email"] == "api-detail@example.invalid"
    assert body["delivery"]["status"] == "pending"
    assert body["transitions"][0]["source_channel"] == "integration_test"
    assert raw_token not in response.content.decode()
    audit = AuditEvent.objects.filter(
        operation="identity.account_invitation.read"
    ).latest("occurred_at")
    assert audit.source_channel == "api"
    evidence = json.dumps(audit.safe_metadata, sort_keys=True)
    assert raw_token not in evidence
    assert invitation.account.email not in evidence


def test_detail_denial_precedes_lookup_and_audit_failure_releases_no_identity(
    platform_actor: Account,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="audit-fail")
    ordinary = AccountFactory()
    existing_denied = _client(ordinary).get(_detail_url(invitation.id))
    absent_denied = _client(ordinary).get(_detail_url(uuid4()))
    assert existing_denied.status_code == absent_denied.status_code == 403
    assert _without_request_id(existing_denied) == _without_request_id(absent_denied)

    with patch(
        "maru.identity.invitation_api.append_platform_account_read_audit",
        side_effect=DatabaseError("synthetic audit outage"),
    ):
        unavailable = _client(platform_actor).get(_detail_url(invitation.id))
    assert unavailable.status_code == 503
    text = unavailable.content.decode()
    assert invitation.account.email not in text
    assert invitation.account.display_name not in text


def test_detail_rejects_query_input_and_missing_target_is_generic(
    platform_actor: Account,
) -> None:
    invalid = _client(platform_actor).get(f"{_detail_url(uuid4())}?include=account")
    missing = _client(platform_actor).get(_detail_url(uuid4()))
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "unknown_input_field"
    assert missing.status_code == 404
    assert missing.json()["code"] == "account_invitation_not_found"
    assert "Platform account invitations are unavailable" in missing.json()["detail"]


def test_reissue_and_revoke_use_expected_versions_and_header_replay(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-actions")
    old_challenge_id = invitation.current_challenge_id
    old_token = _decrypt_token(invitation, invitation_private_key)
    client = _client(platform_actor)
    reissue_key = uuid4()
    reissue_payload = {
        "expected_version": 1,
        "reason": "Replace the recipient's lost invitation code.",
    }

    reissued = client.post(
        _reissue_url(invitation.id),
        reissue_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(reissue_key),
    )
    replayed = client.post(
        _reissue_url(invitation.id),
        reissue_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(reissue_key),
    )
    assert reissued.status_code == replayed.status_code == 200
    assert reissued.json()["aggregate_version"] == 2
    assert reissued.json()["replayed"] is False
    assert replayed.json()["replayed"] is True
    invitation.refresh_from_db()
    assert invitation.current_challenge_id != old_challenge_id
    old_challenge = IdentityChallenge.objects.get(id=old_challenge_id)
    assert old_challenge.invalidated_at is not None
    old_delivery = PlatformIdentityDelivery.objects.get(challenge=old_challenge)
    assert old_delivery.encrypted_payload is None
    assert old_token not in reissued.content.decode()

    stale = client.post(
        _revoke_url(invitation.id),
        {"expected_version": 1, "reason": "A stale revocation."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "account_invitation_version_conflict"

    revoked = client.post(
        _revoke_url(invitation.id),
        {"expected_version": 2, "reason": "Withdraw the invitation safely."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["aggregate_version"] == 3
    invitation.refresh_from_db()
    assert invitation.current_challenge_id is None


def test_action_rejects_unknown_fields_and_missing_invitation(
    platform_actor: Account,
) -> None:
    client = _client(platform_actor)
    unknown = client.post(
        _reissue_url(uuid4()),
        {
            "expected_version": 1,
            "reason": "Try an undeclared target.",
            "invitation_id": str(uuid4()),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    missing = client.post(
        _reissue_url(uuid4()),
        {"expected_version": 1, "reason": "Try a missing target."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "unknown_input_field"
    assert missing.status_code == 404
    assert missing.json()["code"] == "account_invitation_unavailable"


def test_public_acceptance_is_session_independent_and_recipient_owned(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-accept")
    raw_token = _decrypt_token(invitation, invitation_private_key)
    unrelated_session_account = AccountFactory(email="ambient-session@example.invalid")
    client = Client(enforce_csrf_checks=True)
    client.force_login(unrelated_session_account)
    retry_key = uuid4()
    payload = _accept_payload(raw_token)

    accepted = client.post(
        _ACCEPT_URL,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replayed = client.post(
        _ACCEPT_URL,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )

    assert accepted.status_code == replayed.status_code == 200
    assert accepted.json() == {
        "accepted": True,
        "next": "sign_in",
        "replayed": False,
    }
    assert replayed.json() == {**accepted.json(), "replayed": True}
    invitation.refresh_from_db()
    invitation.account.refresh_from_db()
    assert invitation.status == PlatformAccountInvitation.Status.ACCEPTED
    assert invitation.account.is_active
    assert invitation.account.has_verified_email
    assert invitation.account.check_password(_PASSWORD)
    assert unrelated_session_account.id != invitation.account_id
    _assert_no_convention_relationship(invitation.account)
    response_text = accepted.content.decode()
    assert raw_token not in response_text
    assert _PASSWORD not in response_text

    changed_password = client.post(
        _ACCEPT_URL,
        data=json.dumps(
            _accept_payload(
                raw_token,
                password="Different-Recipient-Owned-Password-2849!",
            )
        ),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    assert changed_password.status_code == 409
    assert changed_password.json()["code"] == "account_invitation_retry_conflict"
    assert "Different-Recipient" not in changed_password.content.decode()


def test_public_acceptance_header_and_secret_validation_never_reflect_c4_input(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-secrets")
    raw_token = _decrypt_token(invitation, invitation_private_key)
    missing_header = _client().generic(
        "POST",
        _ACCEPT_URL,
        data=(f'{{"raw_token":"{raw_token}"').encode(),
        content_type="application/json",
    )
    assert missing_header.status_code == 400
    assert missing_header.json()["code"] == "missing_idempotency_key"
    assert raw_token not in missing_header.content.decode()

    secret_as_key = _client().post(
        _ACCEPT_URL,
        {
            raw_token: "attacker-selected-property",
            "new_password1": _PASSWORD,
            "new_password2": _PASSWORD,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert secret_as_key.status_code == 400
    assert secret_as_key.json()["code"] == "unknown_input_field"
    assert raw_token not in secret_as_key.content.decode()
    assert _PASSWORD not in secret_as_key.content.decode()

    mismatch = _client().post(
        _ACCEPT_URL,
        {
            "raw_token": raw_token,
            "new_password1": _PASSWORD,
            "new_password2": "Mismatched-Password-That-Must-Not-Appear-8821!",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "invitation_password_mismatch"
    mismatch_text = mismatch.content.decode()
    assert raw_token not in mismatch_text
    assert _PASSWORD not in mismatch_text
    assert "Mismatched-Password" not in mismatch_text


def test_password_validator_error_does_not_reflect_password_or_account_identity(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = create_platform_account_invitation(
        actor=platform_actor,
        email="validator-private-identity@example.invalid",
        login_handle="validator-private-handle",
        display_name="Validator Private Display",
        preferred_language="en",
        reason="Exercise safe password validator messages.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    ).invitation
    raw_token = _decrypt_token(invitation, invitation_private_key)
    unsafe_password = "validator-private-identity@example.invalid"
    response = _client().post(
        _ACCEPT_URL,
        _accept_payload(raw_token, password=unsafe_password),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 400
    text = response.content.decode()
    assert raw_token not in text
    assert unsafe_password not in text
    assert invitation.account.email not in text
    assert invitation.account.login_handle not in text
    assert invitation.account.display_name not in text


def test_adversarial_password_validator_cannot_reflect_c4_or_identity(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invitation = create_platform_account_invitation(
        actor=platform_actor,
        email="adversarial-validator-identity@example.invalid",
        login_handle="adversarial-validator-handle",
        display_name="Adversarial Validator Identity",
        preferred_language="en",
        reason="Prove validator output cannot cross the C4 boundary.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    ).invitation
    raw_token = _decrypt_token(invitation, invitation_private_key)
    unsafe_password = "C4-Validator-Secret-Password-7349!"
    caplog.set_level(logging.DEBUG)

    with override_settings(
        AUTH_PASSWORD_VALIDATORS=[{"NAME": f"{__name__}.EchoingPasswordValidator"}]
    ):
        response = _client().post(
            _ACCEPT_URL,
            _accept_payload(raw_token, password=unsafe_password),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invitation_password_invalid"
    assert response.json()["errors"] == {
        "new_password1": ["Choose a password that meets the account password policy."]
    }
    response_text = response.content.decode()
    log_text = caplog.text
    for protected_value in (
        unsafe_password,
        raw_token,
        invitation.account.email,
        invitation.account.login_handle,
        invitation.account.display_name,
    ):
        assert protected_value not in response_text
        assert protected_value not in log_text


def test_public_acceptance_is_non_enumerating_for_random_and_revoked_codes(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-revoked")
    revoked_token = _decrypt_token(invitation, invitation_private_key)
    revoke_platform_account_invitation(
        actor=platform_actor,
        invitation_id=invitation.id,
        expected_version=1,
        reason="Withdraw this synthetic invitation.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    random_token = "A" * INVITATION_TOKEN_LENGTH

    revoked = _client().post(
        _ACCEPT_URL,
        _accept_payload(revoked_token),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    random = _client().post(
        _ACCEPT_URL,
        _accept_payload(random_token),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert revoked.status_code == random.status_code == 400
    assert _without_request_id(revoked) == _without_request_id(random)
    assert revoked.json()["code"] == "account_invitation_challenge_invalid"
    assert revoked_token not in revoked.content.decode()
    assert random_token not in random.content.decode()


def test_public_acceptance_throttles_without_changing_non_enumerating_failures() -> (
    None
):
    client = _client()
    responses = [
        client.post(
            _ACCEPT_URL,
            _accept_payload(chr(65 + index) * INVITATION_TOKEN_LENGTH),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        for index in range(9)
    ]
    assert all(response.status_code == 400 for response in responses[:8])
    assert responses[-1].status_code == 429
    assert responses[-1].json()["code"] == "identity_rate_limited"
    assert set(responses[-1].json()) <= {
        "type",
        "title",
        "status",
        "detail",
        "code",
        "request_id",
    }


def test_public_acceptance_rejects_query_and_non_json_without_secret_reflection(
    platform_actor: Account,
    invitation_private_key: rsa.RSAPrivateKey,
) -> None:
    invitation = _create_invitation(actor=platform_actor, local_part="api-media")
    raw_token = _decrypt_token(invitation, invitation_private_key)
    query = _client().post(
        f"{_ACCEPT_URL}?token=not-a-valid-location",
        _accept_payload(raw_token),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    wrong_media = _client().generic(
        "POST",
        _ACCEPT_URL,
        data=(f"raw_token={raw_token}&new_password1={_PASSWORD}").encode(),
        content_type="application/x-www-form-urlencoded",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert query.status_code == 400
    assert query.json()["code"] == "unknown_input_field"
    assert wrong_media.status_code == 415
    assert wrong_media.headers["Content-Type"].startswith("application/problem+json")
    assert raw_token not in wrong_media.content.decode()
    assert _PASSWORD not in wrong_media.content.decode()


def test_cors_allows_idempotency_header_only_for_exact_approved_origins(
    settings: object,
) -> None:
    allowed_origin = "https://registration.example.invalid"
    settings.MARU_REGISTRATION_CLIENT_ORIGINS = [allowed_origin]  # type: ignore[attr-defined]
    preflight = _client().options(
        _ACCEPT_URL,
        HTTP_ORIGIN=allowed_origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,idempotency-key",
    )
    assert preflight.status_code == 204
    assert preflight.headers["Access-Control-Allow-Origin"] == allowed_origin
    assert "Idempotency-Key" in preflight.headers["Access-Control-Allow-Headers"]
    assert preflight.headers["Access-Control-Allow-Credentials"] == "true"

    allowed = _client().post(
        _ACCEPT_URL,
        _accept_payload("Z" * INVITATION_TOKEN_LENGTH),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_ORIGIN=allowed_origin,
    )
    denied_origin = _client().post(
        _ACCEPT_URL,
        _accept_payload("Y" * INVITATION_TOKEN_LENGTH),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_ORIGIN="https://unapproved.example.invalid",
    )
    denied_preflight = _client().options(
        _ACCEPT_URL,
        HTTP_ORIGIN=f"{allowed_origin}.attacker.invalid",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,idempotency-key",
    )
    assert allowed.headers["Access-Control-Allow-Origin"] == allowed_origin
    assert "Access-Control-Allow-Origin" not in denied_origin.headers
    assert "Access-Control-Allow-Origin" not in denied_preflight.headers


def _request_component(schema: dict[str, Any], operation: dict[str, Any]):
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    reference = request_schema["$ref"]
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]


def _response_component(
    schema: dict[str, Any],
    operation: dict[str, Any],
    status_code: str,
):
    response_schema = operation["responses"][status_code]["content"][
        "application/json"
    ]["schema"]
    reference = response_schema["$ref"]
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]


def test_openapi_declares_all_invitation_routes_as_closed_rfc9457_contracts(
    platform_actor: Account,
) -> None:
    response = _client(platform_actor).get(
        "/api/v1/schema",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert response.status_code == 200
    schema = response.json()
    inventory = schema["paths"][_ACCOUNTS_URL]["get"]
    collection = schema["paths"][_CREATE_URL]["post"]
    detail_path = "/api/v1/platform/account-invitations/{invitation_id}"
    detail = schema["paths"][detail_path]["get"]
    reissue = schema["paths"][f"{detail_path}/reissue"]["post"]
    revoke = schema["paths"][f"{detail_path}/revoke"]["post"]
    acceptance = schema["paths"][_ACCEPT_URL]["post"]

    assert set(inventory["responses"]) == {"200", "400", "403", "409", "503"}
    assert set(collection["responses"]) == {"200", "201", "400", "403", "409", "503"}
    assert set(detail["responses"]) == {"200", "400", "403", "404", "409", "503"}
    for operation in (reissue, revoke):
        assert set(operation["responses"]) == {
            "200",
            "400",
            "403",
            "404",
            "409",
            "503",
        }
    assert set(acceptance["responses"]) == {"200", "400", "409", "429", "503"}

    inventory_parameters = {
        parameter["name"]: parameter for parameter in inventory["parameters"]
    }
    assert set(inventory_parameters) == {
        "search",
        "search_mode",
        "kind",
        "state",
        "cursor",
        "page_size",
    }
    assert inventory_parameters["page_size"]["schema"]["maximum"] == 100
    assert {
        (branch.get("minLength"), branch["maxLength"])
        for branch in inventory_parameters["search"]["schema"]["oneOf"]
    } == {(2, 120), (None, 0)}
    inventory_component = _response_component(schema, inventory, "200")
    assert inventory_component["additionalProperties"] is False
    assert set(inventory_component["properties"]) == {
        "inventory_version",
        "items",
        "next_cursor",
    }

    for operation in (collection, reissue, revoke, acceptance):
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["in"] == "header"
        assert header["required"] is True
        assert header["schema"]["format"] == "uuid"
        assert header["schema"]["pattern"] == (
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        component = _request_component(schema, operation)
        assert component["additionalProperties"] is False
        assert "retry_key" not in component["properties"]

    create_component = _request_component(schema, collection)
    assert not {
        "actor_id",
        "account_kind",
        "is_active",
        "password",
        "challenge_expiry",
        "delivery_status",
        "status",
        "aggregate_version",
    }.intersection(create_component["properties"])
    acceptance_component = _request_component(schema, acceptance)
    assert set(acceptance_component["properties"]) == {
        "raw_token",
        "new_password1",
        "new_password2",
    }
    assert all(
        acceptance_component["properties"][field]["writeOnly"] is True
        for field in ("raw_token", "new_password1", "new_password2")
    )
    assert acceptance.get("security", []) == []
    for operation in (inventory, collection, detail, reissue, revoke):
        assert {} not in operation["security"]
    for operation in (inventory, collection, detail, reissue, revoke, acceptance):
        for status_code, response_contract in operation["responses"].items():
            if status_code.startswith("2"):
                continue
            problem = response_contract["content"]["application/problem+json"]["schema"]
            assert problem["$ref"].endswith("/PlatformAccountInvitationProblem")

    for operation, status_code in (
        (collection, "201"),
        (detail, "200"),
        (reissue, "200"),
        (revoke, "200"),
        (acceptance, "200"),
    ):
        assert (
            _response_component(schema, operation, status_code)["additionalProperties"]
            is False
        )
