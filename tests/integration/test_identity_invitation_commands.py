from __future__ import annotations

import base64
import hashlib
import json
import smtplib
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import time_machine
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.test import override_settings

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import (
    INVITATION_LIFETIME,
    AccountInvitationCommandResult,
    InvitationAuthorizationDeniedError,
    InvitationChallengeInvalidError,
    InvitationDependencyUnavailableError,
    InvitationIdentityConflictError,
    InvitationRetryConflictError,
    InvitationStateConflictError,
    accept_platform_account_invitation,
    create_platform_account_invitation,
    expire_platform_account_invitations,
    reissue_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_crypto import (
    EncryptedInvitationPayload,
    InvitationPrivateKeyring,
    decrypt_invitation_payload,
)
from maru.identity.invitation_delivery import (
    InvitationDeliveryMessage,
    deliver_platform_identity_invitation,
)
from maru.identity.invitation_delivery_payload import (
    decode_invitation_delivery_payload,
    invitation_delivery_aad,
)
from maru.identity.invitation_readiness import (
    platform_invitation_digest_key_coverage_is_ready,
)
from maru.identity.models import (
    Account,
    AccountSecurityEvent,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
)
from tests.factories import AccountFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.integration,
]

_SOURCE_CHANNEL = "integration_test"
_PASSWORD = "Thorough-Synthetic-Recipient-Password-7392!"
_ALLOWED_ACCOUNT_RELATION_MODELS = frozenset(
    {
        AccountSecurityEvent,
        IdentityChallenge,
        PlatformAccountInvitation,
        PlatformAccountInvitationCommandReceipt,
        PlatformAccountInvitationTransition,
    }
)


@pytest.fixture(autouse=True)
def inventory_control() -> PlatformAccountInventoryControl:
    control, _ = PlatformAccountInventoryControl.objects.get_or_create(
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
    settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = (  # type: ignore[attr-defined]
        "integration-key-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
        public_key_pem
    ).decode("ascii")
    settings.MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (  # type: ignore[attr-defined]
        "integration-digest-key-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {"integration-digest-key-2026-08": base64.b64encode(b"d" * 32).decode("ascii")}
    )
    return invitation_private_key


@pytest.fixture
def platform_actor() -> Account:
    return AccountFactory(
        email="platform.operator@example.invalid",
        display_name="Synthetic Platform Operator",
        is_staff=True,
        is_superuser=True,
    )


def _create(
    *,
    actor: Account,
    email: str,
    retry_key: UUID | None = None,
    correlation_id: UUID | None = None,
    reason: str = "Prepare a synthetic recipient identity.",
    login_handle: str | None = None,
    display_name: str | None = "Synthetic Invitee",
    request_id: UUID | None = None,
) -> AccountInvitationCommandResult:
    return create_platform_account_invitation(
        actor=actor,
        email=email,
        login_handle=login_handle,
        display_name=display_name,
        preferred_language="en",
        reason=reason,
        expected_version=0,
        retry_key=retry_key or uuid4(),
        correlation_id=correlation_id or uuid4(),
        request_id=request_id,
        source_channel=_SOURCE_CHANNEL,
    )


def _decrypt_current_token(
    invitation: PlatformAccountInvitation,
    private_key: rsa.RSAPrivateKey,
) -> tuple[str, IdentityChallenge, PlatformIdentityDelivery]:
    invitation.refresh_from_db()
    assert invitation.current_challenge_id is not None
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
    aad = invitation_delivery_aad(
        invitation_id=invitation.id,
        challenge_id=challenge.id,
        invitation_version=challenge.invitation_version or 0,
        email=invitation.account.email,
    )
    plaintext = decrypt_invitation_payload(
        envelope=envelope,
        expected_aad=aad,
        private_keyring=InvitationPrivateKeyring(
            {delivery.encryption_key_id: private_key}
        ),
    )
    return decode_invitation_delivery_payload(plaintext).raw_token, challenge, delivery


def _accept(
    *,
    raw_token: str,
    retry_key: UUID | None = None,
    correlation_id: UUID | None = None,
    request_fingerprint: str | None = None,
    new_password: str = _PASSWORD,
):
    return accept_platform_account_invitation(
        raw_token=raw_token,
        new_password=new_password,
        retry_key=retry_key or uuid4(),
        correlation_id=correlation_id or uuid4(),
        request_fingerprint=request_fingerprint
        or hashlib.sha256(uuid4().bytes).hexdigest(),
        source_channel=_SOURCE_CHANNEL,
    )


def _invitation_evidence_counts(
    invitation: PlatformAccountInvitation,
) -> tuple[int, ...]:
    return (
        IdentityChallenge.objects.filter(invitation=invitation).count(),
        PlatformIdentityDelivery.objects.filter(invitation=invitation).count(),
        PlatformAccountInvitationTransition.objects.filter(
            invitation=invitation
        ).count(),
        PlatformAccountInvitationCommandReceipt.objects.filter(
            invitation=invitation
        ).count(),
        AccountSecurityEvent.objects.filter(account=invitation.account).count(),
        AuditEvent.objects.filter(
            target_type="identity.platform_account_invitation",
            target_id=invitation.id,
        ).count(),
        PlatformAccountInventoryControl.objects.get(singleton=True).aggregate_version,
    )


def _assert_no_non_invitation_account_relationships(account: Account) -> None:
    for model in apps.get_models():
        if model in _ALLOWED_ACCOUNT_RELATION_MODELS:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, (models.ForeignKey, models.OneToOneField)):
                continue
            if field.remote_field.model is not Account:
                continue
            assert not model._base_manager.filter(
                **{field.attname: account.id}
            ).exists(), f"unexpected relationship: {model._meta.label}.{field.name}"


def _assert_raw_token_absent_from_persistence(
    raw_token: str,
    invitation: PlatformAccountInvitation,
) -> None:
    persisted_values = [
        list(Account.objects.filter(id=invitation.account_id).values()),
        list(PlatformAccountInvitation.objects.filter(id=invitation.id).values()),
        list(IdentityChallenge.objects.filter(invitation=invitation).values()),
        list(PlatformIdentityDelivery.objects.filter(invitation=invitation).values()),
        list(
            PlatformAccountInvitationTransition.objects.filter(
                invitation=invitation
            ).values()
        ),
        list(
            PlatformAccountInvitationCommandReceipt.objects.filter(
                invitation=invitation
            ).values()
        ),
        list(AccountSecurityEvent.objects.filter(account=invitation.account).values()),
        list(
            AuditEvent.objects.filter(
                target_type="identity.platform_account_invitation",
                target_id=invitation.id,
            ).values()
        ),
    ]
    serialized = json.dumps(persisted_values, default=str, sort_keys=True)
    assert raw_token not in serialized


def _assert_generic_invalid_token(raw_token: str, *, fingerprint_label: str) -> str:
    fingerprint = hashlib.sha256(fingerprint_label.encode()).hexdigest()
    with pytest.raises(InvitationChallengeInvalidError) as captured:
        _accept(raw_token=raw_token, request_fingerprint=fingerprint)
    assert captured.value.reason_code == "account_invitation_challenge_invalid"
    assert raw_token not in repr(captured.value)
    return str(captured.value)


def _global_mutation_counts() -> tuple[int, ...]:
    return (
        Account.objects.count(),
        PlatformAccountInvitation.objects.count(),
        IdentityChallenge.objects.count(),
        PlatformIdentityDelivery.objects.count(),
        PlatformAccountInvitationTransition.objects.count(),
        PlatformAccountInvitationCommandReceipt.objects.count(),
        AccountSecurityEvent.objects.count(),
        AuditEvent.objects.count(),
        PlatformAccountInventoryControl.objects.get(singleton=True).aggregate_version,
    )


def test_create_commits_atomic_minimized_nonparticipating_identity_state(  # noqa: PLR0915
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    inventory_version_before = PlatformAccountInventoryControl.objects.get(
        singleton=True
    ).aggregate_version
    retry_key = uuid4()
    correlation_id = uuid4()
    request_id = uuid4()
    result = _create(
        actor=platform_actor,
        email="  NEW.PERSON@EXAMPLE.INVALID ",
        login_handle="SyntheticPerson",
        display_name="  Synthetic   Person  ",
        retry_key=retry_key,
        correlation_id=correlation_id,
        request_id=request_id,
    )
    invitation = result.invitation
    account = Account.objects.get(id=invitation.account_id)
    invitation.refresh_from_db()
    raw_token, challenge, delivery = _decrypt_current_token(
        invitation,
        configured_invitation_crypto,
    )

    assert result.replayed is False
    assert account.email == "new.person@example.invalid"
    assert account.login_handle == "SyntheticPerson"
    assert account.display_name == "Synthetic Person"
    assert account.account_kind == Account.Kind.PERSON
    assert account.is_active is False
    assert account.is_staff is False
    assert account.is_superuser is False
    assert account.email_verified_at is None
    assert account.has_usable_password() is False
    assert invitation.status == PlatformAccountInvitation.Status.PENDING
    assert invitation.aggregate_version == 1
    assert invitation.created_by_id == platform_actor.id
    assert invitation.expires_at - invitation.last_transition_at == INVITATION_LIFETIME
    assert challenge.expires_at == invitation.expires_at
    assert challenge.token_digest != raw_token
    assert len(challenge.token_digest) == 64
    assert delivery.status == PlatformIdentityDelivery.Status.PENDING
    assert delivery.payload_destroyed_at is None
    assert (
        PlatformAccountInventoryControl.objects.get(singleton=True).aggregate_version
        == inventory_version_before + 2
    )

    transition = invitation.transitions.get()
    assert transition.operation == PlatformAccountInvitationTransition.Operation.CREATED
    assert transition.version == 1
    assert transition.actor_id == platform_actor.id
    assert transition.reason == "Prepare a synthetic recipient identity."
    assert transition.correlation_id == correlation_id
    receipt = invitation.command_receipts.get()
    assert receipt == result.receipt
    assert receipt.operation == PlatformAccountInvitationCommandReceipt.Operation.CREATE
    assert receipt.actor_id == platform_actor.id
    assert receipt.retry_key == retry_key
    assert receipt.expected_version == 0
    assert receipt.result_version == 1
    assert len(receipt.request_digest) == 64
    security_event = account.security_events.get()
    assert (
        security_event.event_type
        == AccountSecurityEvent.EventType.ACCOUNT_INVITATION_CREATED
    )
    assert security_event.detail_code == "platform_account_invitation_created"
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.principal_id == platform_actor.id
    assert audit.organization_id is None
    assert audit.event_edition_id is None
    assert audit.capability_code == "identity.manage_account_invitations"
    assert audit.operation == "identity.account_invitation.create"
    assert audit.target_id == invitation.id
    assert audit.request_id == request_id
    assert audit.changed_fields == ["account", "invitation", "challenge", "delivery"]
    assert audit.safe_metadata == {"contract_version": "page10-invitations-v1"}
    assert len(audit.idempotency_key_hash) == 64
    minimized_audit = repr(audit.__dict__)
    for private_value in (
        raw_token,
        account.email,
        account.login_handle,
        account.display_name,
        transition.reason,
    ):
        assert private_value not in minimized_audit

    _assert_raw_token_absent_from_persistence(raw_token, invitation)
    _assert_no_non_invitation_account_relationships(account)


def test_create_replays_once_and_changed_retry_conflicts_without_new_evidence(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    retry_key = uuid4()
    correlation_id = uuid4()
    first = _create(
        actor=platform_actor,
        email="replay@example.invalid",
        retry_key=retry_key,
        correlation_id=correlation_id,
    )
    raw_token, _, _ = _decrypt_current_token(
        first.invitation,
        configured_invitation_crypto,
    )
    before_replay = _invitation_evidence_counts(first.invitation)

    replay = _create(
        actor=platform_actor,
        email="replay@example.invalid",
        retry_key=retry_key,
        correlation_id=correlation_id,
    )

    assert replay.replayed is True
    assert replay.invitation.id == first.invitation.id
    assert replay.receipt.id == first.receipt.id
    assert _invitation_evidence_counts(first.invitation) == before_replay
    with pytest.raises(InvitationRetryConflictError):
        _create(
            actor=platform_actor,
            email="replay@example.invalid",
            reason="Changed input must not reuse the retry key.",
            retry_key=retry_key,
            correlation_id=correlation_id,
        )
    assert _invitation_evidence_counts(first.invitation) == before_replay
    _assert_raw_token_absent_from_persistence(raw_token, first.invitation)


def test_create_existing_email_or_handle_has_one_non_disclosing_conflict(
    platform_actor: Account,
) -> None:
    existing = AccountFactory(
        email="reserved.person@example.invalid",
        login_handle="ReservedHandle",
    )
    initial_counts = _global_mutation_counts()
    errors: list[InvitationIdentityConflictError] = []

    for email, login_handle in (
        ("RESERVED.PERSON@EXAMPLE.INVALID", None),
        ("different.person@example.invalid", "reservedhandle"),
    ):
        with pytest.raises(InvitationIdentityConflictError) as captured:
            _create(
                actor=platform_actor,
                email=email,
                login_handle=login_handle,
            )
        errors.append(captured.value)

    assert {error.reason_code for error in errors} == {
        "account_invitation_identity_unavailable"
    }
    assert len({str(error) for error in errors}) == 1
    for private_value in (existing.email, existing.login_handle):
        assert all(
            private_value.casefold() not in repr(error).casefold() for error in errors
        )
    assert _global_mutation_counts() == initial_counts


def test_create_maps_validation_time_identity_race_to_generic_conflict(
    platform_actor: Account,
) -> None:
    initial_counts = _global_mutation_counts()

    with (
        patch.object(
            Account,
            "full_clean",
            side_effect=ValidationError("synthetic private uniqueness detail"),
        ),
        pytest.raises(InvitationIdentityConflictError) as captured,
    ):
        _create(
            actor=platform_actor,
            email="raced.identity@example.invalid",
            login_handle="RacedIdentity",
        )

    assert str(captured.value) == "The account invitation could not be changed."
    assert "uniqueness" not in repr(captured.value)
    assert _global_mutation_counts() == initial_counts


def test_create_denies_inactive_platform_and_active_person_before_input_parsing() -> (
    None
):
    inactive_platform = AccountFactory(
        email="inactive.platform@example.invalid",
        is_staff=True,
        is_superuser=True,
        is_active=False,
    )
    active_person = AccountFactory(email="ordinary.person@example.invalid")
    initial_counts = _global_mutation_counts()

    for actor in (inactive_platform, active_person):
        with pytest.raises(InvitationAuthorizationDeniedError):
            _create(actor=actor, email="not a valid email")

    assert _global_mutation_counts() == initial_counts


def test_missing_crypto_and_audit_failure_roll_back_every_create_write(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    initial_counts = _global_mutation_counts()
    with (
        override_settings(
            MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="",
            MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64="",
        ),
        pytest.raises(InvitationDependencyUnavailableError),
    ):
        _create(actor=platform_actor, email="missing.crypto@example.invalid")
    assert _global_mutation_counts() == initial_counts

    with (
        override_settings(
            MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID="",
            MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON="",
        ),
        pytest.raises(InvitationDependencyUnavailableError),
    ):
        _create(actor=platform_actor, email="missing.digest@example.invalid")
    assert _global_mutation_counts() == initial_counts

    with (
        patch(
            "maru.identity.invitation_commands.append_audit",
            side_effect=RuntimeError("private synthetic audit failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic audit failure"),
    ):
        _create(actor=platform_actor, email="audit.rollback@example.invalid")
    assert _global_mutation_counts() == initial_counts


def test_digest_key_rotation_accepts_fallback_and_new_issues_use_active_key(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    old_key_id = "integration-digest-key-2026-08"
    new_key_id = "integration-digest-key-2026-09"
    old_key = base64.b64encode(b"d" * 32).decode("ascii")
    new_key = base64.b64encode(b"n" * 32).decode("ascii")

    fallback_invitation = _create(
        actor=platform_actor,
        email="digest.fallback@example.invalid",
    ).invitation
    old_token, old_challenge, _delivery = _decrypt_current_token(
        fallback_invitation,
        configured_invitation_crypto,
    )
    assert old_challenge.token_digest_key_id == old_key_id
    assert platform_invitation_digest_key_coverage_is_ready()

    with override_settings(
        MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID=new_key_id,
        MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=json.dumps({new_key_id: new_key}),
    ):
        assert not platform_invitation_digest_key_coverage_is_ready()

    with override_settings(
        MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID=new_key_id,
        MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=json.dumps(
            {new_key_id: new_key, old_key_id: old_key}
        ),
    ):
        assert platform_invitation_digest_key_coverage_is_ready()
        accepted = _accept(raw_token=old_token)
        assert accepted.invitation.status == PlatformAccountInvitation.Status.ACCEPTED

        reissued_invitation = _create(
            actor=platform_actor,
            email="digest.reissue@example.invalid",
        ).invitation
        reissued_invitation.refresh_from_db()
        assert reissued_invitation.current_challenge is not None
        assert reissued_invitation.current_challenge.token_digest_key_id == new_key_id


def test_removed_digest_key_fails_closed_without_consuming_challenge(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invitation = _create(
        actor=platform_actor,
        email="digest.removed@example.invalid",
    ).invitation
    raw_token, challenge, _delivery = _decrypt_current_token(
        invitation,
        configured_invitation_crypto,
    )
    new_key_id = "integration-digest-key-2026-09"
    with (
        override_settings(
            MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID=new_key_id,
            MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=json.dumps(
                {
                    new_key_id: base64.b64encode(b"n" * 32).decode("ascii"),
                }
            ),
        ),
        pytest.raises(InvitationChallengeInvalidError),
    ):
        _accept(raw_token=raw_token)

    challenge.refresh_from_db()
    invitation.refresh_from_db()
    assert challenge.consumed_at is None
    assert invitation.status == PlatformAccountInvitation.Status.PENDING


def test_reissue_invalidates_and_destroys_old_secret_then_replays_once(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(actor=platform_actor, email="reissue@example.invalid")
    old_token, old_challenge, old_delivery = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )
    retry_key = uuid4()
    correlation_id = uuid4()
    reissued = reissue_platform_account_invitation(
        actor=platform_actor,
        invitation_id=created.invitation.id,
        expected_version=1,
        reason="Replace the undelivered synthetic invitation.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )
    invitation = reissued.invitation
    invitation.refresh_from_db()
    new_token, new_challenge, _ = _decrypt_current_token(
        invitation,
        configured_invitation_crypto,
    )
    old_challenge.refresh_from_db()
    old_delivery.refresh_from_db()

    assert reissued.replayed is False
    assert invitation.aggregate_version == 2
    assert invitation.status == PlatformAccountInvitation.Status.PENDING
    assert new_challenge.id != old_challenge.id
    assert new_token != old_token
    assert old_challenge.invalidated_at is not None
    assert old_challenge.invalidation_reason == "superseded_by_reissue"
    assert old_delivery.payload_destroyed_at is not None
    assert (
        old_delivery.payload_destruction_reason
        == PlatformIdentityDelivery.PayloadDestructionReason.SUPERSEDED
    )
    assert old_delivery.encrypted_payload is None
    assert old_delivery.wrapped_data_key is None
    assert old_delivery.payload_nonce is None
    assert old_delivery.encryption_key_id == ""
    assert old_delivery.payload_aad_digest == ""
    assert reissued.receipt.expected_version == 1
    assert reissued.receipt.result_version == 2
    assert invitation.transitions.get(version=2).operation == (
        PlatformAccountInvitationTransition.Operation.REISSUED
    )
    before_replay = _invitation_evidence_counts(invitation)

    replay = reissue_platform_account_invitation(
        actor=platform_actor,
        invitation_id=invitation.id,
        expected_version=1,
        reason="Replace the undelivered synthetic invitation.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )
    assert replay.replayed is True
    assert replay.receipt.id == reissued.receipt.id
    assert _invitation_evidence_counts(invitation) == before_replay
    with pytest.raises(InvitationRetryConflictError):
        reissue_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=1,
            reason="Changed reissue input.",
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=_SOURCE_CHANNEL,
        )
    assert (
        _assert_generic_invalid_token(
            old_token,
            fingerprint_label="superseded-reissue-token",
        )
        == "The invitation code is invalid or has expired."
    )
    _assert_raw_token_absent_from_persistence(old_token, invitation)
    _assert_raw_token_absent_from_persistence(new_token, invitation)


def test_revoke_is_terminal_destroys_secret_and_replays_without_new_evidence(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(actor=platform_actor, email="revoke@example.invalid")
    raw_token, challenge, delivery = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )
    retry_key = uuid4()
    correlation_id = uuid4()
    revoked = revoke_platform_account_invitation(
        actor=platform_actor,
        invitation_id=created.invitation.id,
        expected_version=1,
        reason="Withdraw the synthetic invitation.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )
    invitation = revoked.invitation
    invitation.refresh_from_db()
    challenge.refresh_from_db()
    delivery.refresh_from_db()

    assert invitation.status == PlatformAccountInvitation.Status.REVOKED
    assert invitation.aggregate_version == 2
    assert invitation.current_challenge_id is None
    assert invitation.revoked_at is not None
    assert challenge.invalidated_at is not None
    assert challenge.invalidation_reason == "invitation_revoked"
    assert (
        delivery.payload_destruction_reason
        == PlatformIdentityDelivery.PayloadDestructionReason.REVOKED
    )
    assert delivery.encrypted_payload is None
    before_replay = _invitation_evidence_counts(invitation)
    replay = revoke_platform_account_invitation(
        actor=platform_actor,
        invitation_id=invitation.id,
        expected_version=1,
        reason="Withdraw the synthetic invitation.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )
    assert replay.replayed is True
    assert _invitation_evidence_counts(invitation) == before_replay

    with pytest.raises(InvitationStateConflictError):
        revoke_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=2,
            reason="A terminal invitation cannot be revoked twice.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=_SOURCE_CHANNEL,
        )
    with pytest.raises(InvitationStateConflictError):
        reissue_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=2,
            reason="A revoked invitation cannot be reissued.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=_SOURCE_CHANNEL,
        )
    assert (
        _assert_generic_invalid_token(
            raw_token,
            fingerprint_label="revoked-token",
        )
        == "The invitation code is invalid or has expired."
    )
    _assert_raw_token_absent_from_persistence(raw_token, invitation)
    _assert_no_non_invitation_account_relationships(invitation.account)


def test_acceptance_chooses_password_verifies_consumes_and_replays_once(  # noqa: PLR0915
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(actor=platform_actor, email="accepted@example.invalid")
    raw_token, challenge, delivery = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )
    retry_key = uuid4()
    correlation_id = uuid4()
    fingerprint = hashlib.sha256(b"accepted-recipient-request").hexdigest()
    accepted = _accept(
        raw_token=raw_token,
        retry_key=retry_key,
        correlation_id=correlation_id,
        request_fingerprint=fingerprint,
    )
    account = accepted.account
    invitation = accepted.invitation
    account.refresh_from_db()
    invitation.refresh_from_db()
    challenge.refresh_from_db()
    delivery.refresh_from_db()

    assert accepted.replayed is False
    assert account.is_active is True
    assert account.email_verified_at is not None
    assert account.check_password(_PASSWORD)
    assert account.account_kind == Account.Kind.PERSON
    assert account.is_staff is False
    assert account.is_superuser is False
    assert invitation.status == PlatformAccountInvitation.Status.ACCEPTED
    assert invitation.aggregate_version == 2
    assert invitation.current_challenge_id is None
    assert invitation.accepted_at == account.email_verified_at
    assert challenge.consumed_at == invitation.accepted_at
    assert challenge.invalidated_at is None
    assert challenge.attempt_count == 1
    assert delivery.payload_destroyed_at is not None
    assert delivery.encrypted_payload is None
    assert accepted.receipt.actor_id == account.id
    assert accepted.receipt.operation == (
        PlatformAccountInvitationCommandReceipt.Operation.ACCEPT
    )
    assert accepted.receipt.expected_version == 1
    assert accepted.receipt.result_version == 2
    accepted_transition = invitation.transitions.get(version=2)
    assert accepted_transition.operation == (
        PlatformAccountInvitationTransition.Operation.ACCEPTED
    )
    assert accepted_transition.actor_id == account.id
    security_types = set(account.security_events.values_list("event_type", flat=True))
    assert security_types == {
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_CREATED,
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_ACCEPTED,
    }
    acceptance_audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert acceptance_audit.principal_id == account.id
    assert acceptance_audit.capability_code == "identity.accept_account_invitation"
    assert acceptance_audit.operation == "identity.account_invitation.accept"
    assert acceptance_audit.organization_id is None
    assert acceptance_audit.event_edition_id is None
    assert raw_token not in repr(acceptance_audit.__dict__)
    assert _PASSWORD not in repr(acceptance_audit.__dict__)
    before_replay = _invitation_evidence_counts(invitation)

    replay = _accept(
        raw_token=raw_token,
        retry_key=retry_key,
        correlation_id=correlation_id,
        request_fingerprint=fingerprint,
    )
    assert replay.replayed is True
    assert replay.receipt.id == accepted.receipt.id
    assert _invitation_evidence_counts(invitation) == before_replay
    with pytest.raises(InvitationRetryConflictError):
        _accept(
            raw_token=raw_token,
            new_password="Changed-Synthetic-Recipient-Password-9317!",
            retry_key=retry_key,
            correlation_id=correlation_id,
            request_fingerprint=fingerprint,
        )
    account.refresh_from_db()
    assert account.check_password(_PASSWORD)
    assert _invitation_evidence_counts(invitation) == before_replay
    _assert_raw_token_absent_from_persistence(raw_token, invitation)
    _assert_no_non_invitation_account_relationships(account)


def test_acceptance_resolves_uncertain_delivery_without_rewriting_outcome(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(
        actor=platform_actor,
        email="accepted-after-uncertain@example.invalid",
    )
    raw_token, _challenge, delivery = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )

    def uncertain_adapter(_message: InvitationDeliveryMessage) -> str:
        raise smtplib.SMTPServerDisconnected("synthetic uncertain outcome")

    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=InvitationPrivateKeyring(
                {"integration-key-2026-08": configured_invitation_crypto}
            ),
            adapter=uncertain_adapter,
        )
        == PlatformIdentityDelivery.Status.RETRYING
    )
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )

    _accept(
        raw_token=raw_token,
        request_fingerprint=hashlib.sha256(
            b"acceptance-resolves-uncertain-delivery"
        ).hexdigest(),
    )

    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.CANCELLED
    assert delivery.payload_destroyed_at is not None
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.reconciliation_code == "invitation_consumed"
    attempt = delivery.attempts.get()
    assert attempt.outcome == "uncertain"


@pytest.mark.django_db(transaction=True)
def test_accepted_invitation_remains_valid_historical_evidence_after_deactivation(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(
        actor=platform_actor,
        email="accepted-then-deactivated@example.invalid",
    )
    raw_token, _challenge, _delivery = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )
    accepted = _accept(
        raw_token=raw_token,
        request_fingerprint=hashlib.sha256(
            b"accepted-then-legitimately-deactivated"
        ).hexdigest(),
    )

    accepted.account.is_active = False
    accepted.account.save(update_fields=("is_active",))
    accepted.invitation.refresh_from_db()
    accepted.invitation.full_clean()

    assert accepted.invitation.status == PlatformAccountInvitation.Status.ACCEPTED
    assert accepted.account.is_active is False


def test_invalid_expired_revoked_and_superseded_tokens_are_indistinguishable(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    invalid_token = "A" * 43

    expired = _create(actor=platform_actor, email="token.expired@example.invalid")
    expired_token, _, _ = _decrypt_current_token(
        expired.invitation,
        configured_invitation_crypto,
    )

    revoked = _create(actor=platform_actor, email="token.revoked@example.invalid")
    revoked_token, _, _ = _decrypt_current_token(
        revoked.invitation,
        configured_invitation_crypto,
    )
    revoke_platform_account_invitation(
        actor=platform_actor,
        invitation_id=revoked.invitation.id,
        expected_version=1,
        reason="Create a revoked-token failure state.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )

    superseded = _create(
        actor=platform_actor,
        email="token.superseded@example.invalid",
    )
    superseded_token, _, _ = _decrypt_current_token(
        superseded.invitation,
        configured_invitation_crypto,
    )
    reissue_platform_account_invitation(
        actor=platform_actor,
        invitation_id=superseded.invitation.id,
        expected_version=1,
        reason="Create a superseded-token failure state.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )

    messages = {
        _assert_generic_invalid_token(token, fingerprint_label=label)
        for token, label in (
            (invalid_token, "unknown-token"),
            (revoked_token, "revoked-token-state"),
            (superseded_token, "superseded-token-state"),
        )
    }
    after_expiry = expired.invitation.expires_at + timedelta(seconds=1)
    with time_machine.travel(after_expiry, tick=False):
        messages.add(
            _assert_generic_invalid_token(
                expired_token,
                fingerprint_label="expired-token",
            )
        )
    assert messages == {"The invitation code is invalid or has expired."}


def test_acceptance_token_rate_limit_cannot_be_bypassed_by_rotating_fingerprint(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(
        actor=platform_actor,
        email="token-rate-limit@example.invalid",
    )
    raw_token, _, _ = _decrypt_current_token(
        created.invitation,
        configured_invitation_crypto,
    )
    evidence_before = _invitation_evidence_counts(created.invitation)

    for attempt in range(8):
        with pytest.raises(ValidationError):
            _accept(
                raw_token=raw_token,
                new_password="x",
                request_fingerprint=hashlib.sha256(
                    f"rotated-fingerprint-{attempt}".encode()
                ).hexdigest(),
            )

    with pytest.raises(ValidationError) as captured:
        _accept(
            raw_token=raw_token,
            request_fingerprint=hashlib.sha256(
                b"rotated-fingerprint-final"
            ).hexdigest(),
        )

    assert captured.value.code == "identity_rate_limited"
    assert _invitation_evidence_counts(created.invitation) == evidence_before


def test_expiry_transition_is_bounded_terminal_minimized_and_idempotent(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(actor=platform_actor, email="expiry@example.invalid")
    invitation = created.invitation
    raw_token, challenge, delivery = _decrypt_current_token(
        invitation,
        configured_invitation_crypto,
    )
    correlation_id = uuid4()
    inventory_version_before_expiry = PlatformAccountInventoryControl.objects.get(
        singleton=True
    ).aggregate_version

    after_expiry = invitation.expires_at + timedelta(seconds=1)
    with time_machine.travel(after_expiry, tick=False):
        assert (
            expire_platform_account_invitations(
                correlation_id=correlation_id,
                limit=1,
                source_channel="scheduler",
            )
            == 1
        )
    invitation.refresh_from_db()
    challenge.refresh_from_db()
    delivery.refresh_from_db()
    assert invitation.status == PlatformAccountInvitation.Status.EXPIRED
    assert invitation.aggregate_version == 2
    assert invitation.current_challenge_id is None
    assert invitation.expired_at is not None
    assert challenge.invalidated_at is not None
    assert challenge.invalidation_reason == "invitation_expired"
    assert delivery.payload_destroyed_at is not None
    assert (
        delivery.payload_destruction_reason
        == PlatformIdentityDelivery.PayloadDestructionReason.EXPIRED
    )
    assert delivery.encrypted_payload is None
    assert invitation.command_receipts.count() == 1
    expiry_transition = invitation.transitions.get(version=2)
    assert expiry_transition.operation == (
        PlatformAccountInvitationTransition.Operation.EXPIRED
    )
    assert expiry_transition.actor_id is None
    assert expiry_transition.source_channel == "scheduler"
    assert set(
        invitation.account.security_events.values_list("event_type", flat=True)
    ) == {
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_CREATED,
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_EXPIRED,
    }
    expiry_audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert expiry_audit.principal_kind == "system"
    assert expiry_audit.principal_id is None
    assert expiry_audit.operation == "identity.account_invitation.expire"
    assert expiry_audit.idempotency_key_hash == ""
    assert expiry_audit.organization_id is None
    assert expiry_audit.event_edition_id is None
    assert (
        PlatformAccountInventoryControl.objects.get(singleton=True).aggregate_version
        == inventory_version_before_expiry + 1
    )
    assert (
        expire_platform_account_invitations(
            correlation_id=uuid4(),
            source_channel="scheduler",
        )
        == 0
    )
    assert (
        _assert_generic_invalid_token(
            raw_token,
            fingerprint_label="expired-transition-token",
        )
        == "The invitation code is invalid or has expired."
    )
    _assert_raw_token_absent_from_persistence(raw_token, invitation)
    _assert_no_non_invitation_account_relationships(invitation.account)


def test_expired_invitation_reissues_but_cannot_be_revoked(
    platform_actor: Account,
    configured_invitation_crypto: rsa.RSAPrivateKey,
) -> None:
    created = _create(
        actor=platform_actor,
        email="expired-state-machine@example.invalid",
    )
    invitation = created.invitation
    with time_machine.travel(
        invitation.expires_at + timedelta(seconds=1),
        tick=False,
    ):
        assert (
            expire_platform_account_invitations(
                correlation_id=uuid4(),
                source_channel="scheduler",
            )
            == 1
        )
    invitation.refresh_from_db()
    evidence_before_revoke = _invitation_evidence_counts(invitation)

    with time_machine.travel(
        invitation.expires_at + timedelta(seconds=2),
        tick=False,
    ):
        with pytest.raises(InvitationStateConflictError):
            revoke_platform_account_invitation(
                actor=platform_actor,
                invitation_id=invitation.id,
                expected_version=2,
                reason="An expired invitation is already terminal.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel=_SOURCE_CHANNEL,
            )

        assert _invitation_evidence_counts(invitation) == evidence_before_revoke
        reissued = reissue_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=2,
            reason="Issue a fresh challenge after expiry.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=_SOURCE_CHANNEL,
        )
    invitation.refresh_from_db()
    assert reissued.invitation.id == invitation.id
    assert invitation.status == PlatformAccountInvitation.Status.PENDING
    assert invitation.aggregate_version == 3
    assert invitation.expired_at is None
    assert invitation.current_challenge_id is not None
    _decrypt_current_token(invitation, configured_invitation_crypto)
