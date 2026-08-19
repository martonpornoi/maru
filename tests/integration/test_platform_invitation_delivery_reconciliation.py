from __future__ import annotations

import base64
import json
import smtplib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from typing import Any, Final
from unittest.mock import patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import (
    InvitationRetryConflictError,
    create_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_crypto import InvitationPrivateKeyring
from maru.identity.invitation_delivery import (
    InvitationDeliveryMessage,
    deliver_pending_platform_identity_invitations,
    deliver_platform_identity_invitation,
)
from maru.identity.invitation_delivery_reconciliation import (
    resolve_platform_identity_delivery_as_delivered,
    resolve_platform_identity_delivery_for_retry,
)
from maru.identity.models import (
    Account,
    PlatformAccountInventoryControl,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformIdentityDeliveryLateOutcome,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_KEY_ID: Final = "reconciliation-integration-key-2026-08"
_SOURCE_CHANNEL: Final = "integration_test"


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
        "reconciliation-digest-key-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {
            "reconciliation-digest-key-2026-08": base64.b64encode(b"r" * 32).decode(
                "ascii"
            )
        }
    )
    settings.MARU_PUBLIC_BASE_URL = "https://maru.example.invalid"  # type: ignore[attr-defined]
    return InvitationPrivateKeyring({_KEY_ID: invitation_private_key})


@pytest.fixture
def platform_actor() -> Account:
    return Account.objects.create_superuser(
        email="reconciliation.operator@example.invalid",
        password="Synthetic-reconciliation-operator-password-1!",
        display_name="Synthetic Reconciliation Operator",
    )


def _new_delivery(*, actor: Account, local_part: str) -> PlatformIdentityDelivery:
    result = create_platform_account_invitation(
        actor=actor,
        email=f"{local_part}@example.invalid",
        login_handle=None,
        display_name="Synthetic Reconciliation Recipient",
        preferred_language="en",
        reason="Exercise reasoned delivery reconciliation.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )
    return PlatformIdentityDelivery.objects.get(
        challenge_id=result.invitation.current_challenge_id
    )


def _set_code_owned_attempt_limit_for_test(
    delivery: PlatformIdentityDelivery,
    *,
    max_attempts: int,
) -> None:
    """Simulate a code-owned policy variant through the test migration owner."""

    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery DISABLE TRIGGER "
            "identity_page10_hardened_delivery_update"
        )
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery DISABLE TRIGGER "
            "identity_page10_hardened_delivery_complete"
        )
        try:
            cursor.execute(
                "UPDATE identity_platformidentitydelivery "
                "SET max_attempts = %s, "
                "aggregate_version = aggregate_version + 1, "
                "updated_at = clock_timestamp() WHERE id = %s",
                [max_attempts, delivery.id],
            )
        finally:
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery ENABLE TRIGGER "
                "identity_page10_hardened_delivery_complete"
            )
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery ENABLE TRIGGER "
                "identity_page10_hardened_delivery_update"
            )
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    delivery.refresh_from_db()


def _make_uncertain(
    delivery: PlatformIdentityDelivery,
    *,
    keyring: InvitationPrivateKeyring,
) -> PlatformIdentityDelivery:
    def uncertain_adapter(_message: InvitationDeliveryMessage) -> str:
        raise smtplib.SMTPServerDisconnected("synthetic uncertain outcome")

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


def test_operator_resolves_uncertain_delivery_as_delivered_idempotently(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _make_uncertain(
        _new_delivery(actor=platform_actor, local_part="resolve-delivered"),
        keyring=configured_invitation_crypto,
    )
    version = delivery.aggregate_version
    retry_key = uuid4()
    correlation_id = uuid4()

    resolved = resolve_platform_identity_delivery_as_delivered(
        actor=platform_actor,
        delivery_id=delivery.id,
        expected_version=version,
        provider_reference="synthetic-provider-confirmation-1",
        reason="Confirmed the accepted message in the synthetic provider console.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )

    delivery.refresh_from_db()
    assert resolved.replayed is False
    assert delivery.aggregate_version == version + 1
    assert delivery.status == PlatformIdentityDelivery.Status.DELIVERED
    assert delivery.provider_reference == "synthetic-provider-confirmation-1"
    assert delivery.payload_destroyed_at is not None
    assert delivery.encrypted_payload is None
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.reconciliation_code == "operator_confirmed_delivered"
    assert resolved.receipt.reason.startswith("Confirmed the accepted message")
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.operation == "identity.account_invitation.delivery_reconcile"
    assert audit.principal_id == platform_actor.id
    assert "provider" not in str(audit.safe_metadata)

    replay = resolve_platform_identity_delivery_as_delivered(
        actor=platform_actor,
        delivery_id=delivery.id,
        expected_version=version,
        provider_reference="synthetic-provider-confirmation-1",
        reason="Confirmed the accepted message in the synthetic provider console.",
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=_SOURCE_CHANNEL,
    )
    assert replay.replayed is True
    assert replay.receipt.id == resolved.receipt.id
    assert delivery.reconciliation_receipts.count() == 1
    with pytest.raises(InvitationRetryConflictError):
        resolve_platform_identity_delivery_as_delivered(
            actor=platform_actor,
            delivery_id=delivery.id,
            expected_version=version,
            provider_reference="changed-provider-reference",
            reason="Changed reconciliation evidence is not an idempotent replay.",
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=_SOURCE_CHANNEL,
        )


def test_operator_resolves_uncertain_delivery_for_one_bounded_retry(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(actor=platform_actor, local_part="resolve-retry")
    _set_code_owned_attempt_limit_for_test(delivery, max_attempts=1)
    delivery = _make_uncertain(delivery, keyring=configured_invitation_crypto)
    version = delivery.aggregate_version

    resolved = resolve_platform_identity_delivery_for_retry(
        actor=platform_actor,
        delivery_id=delivery.id,
        expected_version=version,
        reason="Confirmed no accepted message exists before a controlled retry.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )

    delivery.refresh_from_db()
    assert resolved.replayed is False
    assert delivery.aggregate_version == version + 1
    assert delivery.max_attempts == 2
    assert delivery.status == PlatformIdentityDelivery.Status.RETRYING
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.reconciliation_code == "operator_confirmed_retry"
    observed_headers: list[dict[str, str]] = []

    def delivered_adapter(message: InvitationDeliveryMessage) -> str:
        observed_headers.append(message.headers)
        return "synthetic-provider-retry-confirmation"

    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=delivered_adapter,
        )
        == PlatformIdentityDelivery.Status.DELIVERED
    )
    delivery.refresh_from_db()
    assert delivery.attempt_count == 2
    assert observed_headers == [
        {"X-Maru-Idempotency-Key": str(delivery.provider_idempotency_key)}
    ]


def test_operator_retry_can_return_to_required_after_a_second_uncertain_result(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(actor=platform_actor, local_part="retry-uncertain-again")
    delivery = _make_uncertain(delivery, keyring=configured_invitation_crypto)
    first_required_at = delivery.reconciliation_required_at
    assert first_required_at is not None

    resolve_platform_identity_delivery_for_retry(
        actor=platform_actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Provider confirmed that the first attempt was not accepted.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )
    assert delivery.reconciled_at is not None
    assert delivery.reconciliation_code == "operator_confirmed_retry"

    def uncertain_again(_message: InvitationDeliveryMessage) -> str:
        raise smtplib.SMTPServerDisconnected("synthetic second uncertainty")

    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=uncertain_again,
        )
        == PlatformIdentityDelivery.Status.RETRYING
    )
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
    assert delivery.reconciliation_required_at is not None
    assert delivery.reconciliation_required_at >= first_required_at
    assert delivery.reconciled_at is None
    assert delivery.reconciliation_code == ""
    assert delivery.reconciliation_receipts.count() == 1


@pytest.mark.django_db(transaction=True)
def test_revocation_preserves_paused_provider_result_as_late_evidence(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(actor=platform_actor, local_part="paused-revocation")
    invitation = delivery.invitation
    entered_adapter = Event()
    release_adapter = Event()

    def paused_adapter(_message: InvitationDeliveryMessage) -> str:
        entered_adapter.set()
        assert release_adapter.wait(timeout=15)
        return "synthetic-late-provider-confirmation"

    def deliver_while_paused() -> str:
        close_old_connections()
        try:
            return deliver_platform_identity_invitation(
                delivery.id,
                private_keyring=configured_invitation_crypto,
                adapter=paused_adapter,
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        provider_call = executor.submit(deliver_while_paused)
        assert entered_adapter.wait(timeout=15)
        delivery.refresh_from_db()
        assert delivery.status == PlatformIdentityDelivery.Status.PROCESSING
        lease_token = delivery.lease_token
        assert lease_token is not None

        revoke_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=invitation.aggregate_version,
            reason="Withdraw the invitation while provider delivery is in flight.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=_SOURCE_CHANNEL,
        )
        delivery.refresh_from_db()
        assert delivery.status == PlatformIdentityDelivery.Status.PROCESSING
        assert delivery.lease_token == lease_token
        assert delivery.cancellation_requested_at is not None
        assert delivery.payload_destroyed_at is not None

        assert delivery.lease_expires_at is not None
        recovery_time = delivery.lease_expires_at + timedelta(seconds=1)
        with patch(
            "maru.identity.invitation_delivery.timezone.now",
            return_value=recovery_time,
        ):
            assert (
                deliver_platform_identity_invitation(
                    delivery.id,
                    private_keyring=configured_invitation_crypto,
                    adapter=lambda _message: pytest.fail(
                        "cancelled delivery was resent"
                    ),
                )
                == PlatformIdentityDelivery.Status.CANCELLED
            )
            release_adapter.set()
            assert provider_call.result(timeout=15) == (
                PlatformIdentityDelivery.Status.CANCELLED
            )

    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.CANCELLED
    assert delivery.safe_error_code == "invitation_revoked"
    assert delivery.cancelled_at is not None
    attempt = delivery.attempts.get(attempt_number=1)
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST
    late = delivery.late_outcomes.get(attempt_number=1)
    assert late.lease_token == lease_token
    assert late.outcome == PlatformIdentityDeliveryLateOutcome.Outcome.DELIVERED
    assert late.classification == (
        PlatformIdentityDeliveryLateOutcome.Classification.LIFECYCLE_CANCELLED
    )
    assert late.provider_reference == "synthetic-late-provider-confirmation"
    assert delivery.reconciliation_state != (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )


@pytest.mark.django_db(transaction=True)
def test_corrupt_envelope_is_quarantined_without_starving_later_delivery(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    corrupt = _new_delivery(actor=platform_actor, local_part="corrupt-envelope")
    healthy = _new_delivery(actor=platform_actor, local_part="healthy-after-corrupt")
    ciphertext = bytes(corrupt.encrypted_payload or b"")
    assert ciphertext
    replacement = b"A" if ciphertext[:1] != b"A" else b"B"
    tampered = replacement + ciphertext[1:]
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery "
            "DISABLE TRIGGER identity_page10_delivery_write"
        )
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery "
            "DISABLE TRIGGER identity_page10_hardened_delivery_update"
        )
        try:
            cursor.execute(
                "UPDATE identity_platformidentitydelivery "
                "SET encrypted_payload = %s, aggregate_version = aggregate_version + 1 "
                "WHERE id = %s",
                [tampered, corrupt.id],
            )
        finally:
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery "
                "ENABLE TRIGGER identity_page10_hardened_delivery_update"
            )
            cursor.execute(
                "ALTER TABLE identity_platformidentitydelivery "
                "ENABLE TRIGGER identity_page10_delivery_write"
            )
    provider_references: list[str] = []

    def adapter(_message: InvitationDeliveryMessage) -> str:
        reference = f"synthetic-provider-{len(provider_references) + 1}"
        provider_references.append(reference)
        return reference

    attempted, pending = deliver_pending_platform_identity_invitations(
        limit=10,
        private_keyring=configured_invitation_crypto,
        adapter=adapter,
    )

    assert (attempted, pending) == (2, 0)
    corrupt.refresh_from_db()
    healthy.refresh_from_db()
    assert corrupt.status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    assert corrupt.safe_error_code == "invitation_encrypted_payload_invalid"
    assert healthy.status == PlatformIdentityDelivery.Status.DELIVERED
    assert provider_references == ["synthetic-provider-1"]


def test_database_rejects_delivery_version_skips_and_forged_reconciliation(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    del configured_invitation_crypto
    delivery = _new_delivery(actor=platform_actor, local_part="raw-reconciliation")
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version WHERE id = %s",
            [delivery.id],
        )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 2 WHERE id = %s",
            [delivery.id],
        )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1 WHERE id = %s",
            [delivery.id],
        )
    delivery.refresh_from_db()
    assert delivery.aggregate_version == 1
    ordinary_actor = Account.objects.create_user(
        email="ordinary.reconciliation@example.invalid",
        password="Synthetic-ordinary-reconciliation-password-1!",
    )

    def insert_receipt(
        *,
        actor_id: Any,
        inventory_control_id: Any = True,
        delivery_id: Any = delivery.id,
        expected_version: int = 1,
        result_version: int = 2,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO "
                "identity_platformidentitydeliveryreconciliationreceipt "
                "(id, created_at, updated_at, operation, reason, retry_key, "
                "request_digest, expected_version, result_version, correlation_id, "
                "source_channel, actor_id, delivery_id, inventory_control_id) "
                "VALUES (%s, clock_timestamp(), clock_timestamp(), %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    uuid4(),
                    "resolve_retry",
                    "Synthetic raw reconciliation must be rejected.",
                    uuid4(),
                    "a" * 64,
                    expected_version,
                    result_version,
                    uuid4(),
                    _SOURCE_CHANNEL,
                    actor_id,
                    delivery_id,
                    inventory_control_id,
                ],
            )

    invalid_receipts = (
        {"actor_id": ordinary_actor.id},
        {"actor_id": platform_actor.id, "inventory_control_id": False},
        {
            "actor_id": platform_actor.id,
            "expected_version": 1,
            "result_version": 3,
        },
        {"actor_id": platform_actor.id, "delivery_id": uuid4()},
    )
    for invalid in invalid_receipts:
        with pytest.raises(DatabaseError), transaction.atomic():
            insert_receipt(**invalid)
