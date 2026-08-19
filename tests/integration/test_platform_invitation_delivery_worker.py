from __future__ import annotations

import base64
import io
import json
import re
import smtplib
from collections.abc import Callable
from datetime import timedelta
from typing import Final
from unittest.mock import patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import F
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import create_platform_account_invitation
from maru.identity.invitation_crypto import InvitationPrivateKeyring
from maru.identity.invitation_delivery import (
    InvitationDeliveryDependencyError,
    InvitationDeliveryMessage,
    deliver_pending_platform_identity_invitations,
    deliver_platform_identity_invitation,
)
from maru.identity.invitation_delivery_reconciliation import (
    resolve_platform_identity_delivery_for_retry,
)
from maru.identity.invitation_key_config import PRIVATE_KEYRING_ENVIRONMENT
from maru.identity.invitation_readiness import (
    platform_invitation_delivery_heartbeat_is_ready,
    platform_invitation_expiry_heartbeat_is_ready,
)
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformInvitationSchedulerRun,
)
from maru.identity.services import (
    deliver_identity_challenge,
    deliver_pending_identity_challenges,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_KEY_ID: Final = "delivery-integration-key-2026-08"
_PUBLIC_BASE_URL: Final = "https://maru.example.invalid"
_SOURCE_CHANNEL: Final = "integration_test"
_FRAGMENT_PATTERN: Final = re.compile(
    r"https://maru\.example\.invalid/accounts/invitations/accept/"
    r"#code=[A-Za-z0-9_-]{43}"
)


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
        "delivery-digest-key-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {"delivery-digest-key-2026-08": base64.b64encode(b"w" * 32).decode("ascii")}
    )
    settings.MARU_PUBLIC_BASE_URL = _PUBLIC_BASE_URL  # type: ignore[attr-defined]
    return InvitationPrivateKeyring({_KEY_ID: invitation_private_key})


@pytest.fixture
def worker_private_key_environment(
    invitation_private_key: rsa.RSAPrivateKey,
) -> str:
    private_key_pem = invitation_private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return json.dumps(
        {_KEY_ID: base64.b64encode(private_key_pem).decode("ascii")},
        separators=(",", ":"),
        sort_keys=True,
    )


@pytest.fixture
def platform_actor() -> Account:
    return Account.objects.create_superuser(
        email="delivery.operator@example.invalid",
        password="Synthetic-delivery-operator-password-1!",
        display_name="Synthetic Delivery Operator",
    )


def _new_delivery(
    *,
    actor: Account,
    local_part: str,
) -> PlatformIdentityDelivery:
    result = create_platform_account_invitation(
        actor=actor,
        email=f"{local_part}@example.invalid",
        login_handle=None,
        display_name="Synthetic Delivery Recipient",
        preferred_language="en",
        reason="Verify the durable invitation delivery boundary.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )
    invitation = result.invitation
    assert invitation.current_challenge_id is not None
    return PlatformIdentityDelivery.objects.get(
        challenge_id=invitation.current_challenge_id
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


def _assert_safe_fragment_boundary(message: InvitationDeliveryMessage) -> None:
    link_match = _FRAGMENT_PATTERN.search(message.body)
    assert link_match is not None
    link = link_match.group(0)
    assert "?" not in link
    assert "/#code=" in link
    assert "code=" not in link.split("#", maxsplit=1)[0]


def _make_capturing_adapter(
    messages: list[InvitationDeliveryMessage],
    *,
    provider_reference: str = "synthetic-provider-reference-1",
) -> Callable[[InvitationDeliveryMessage], str]:
    def adapter(message: InvitationDeliveryMessage) -> str:
        messages.append(message)
        return provider_reference

    return adapter


def test_success_decrypts_only_at_adapter_boundary_and_erases_payload(
    configured_invitation_crypto: InvitationPrivateKeyring,
    inventory_control: PlatformAccountInventoryControl,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="successful-delivery",
    )
    inventory_control.refresh_from_db()
    version_before_worker = inventory_control.aggregate_version
    messages: list[InvitationDeliveryMessage] = []

    status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=_make_capturing_adapter(messages),
    )

    assert status == PlatformIdentityDelivery.Status.DELIVERED
    assert len(messages) == 1
    _assert_safe_fragment_boundary(messages[0])
    assert messages[0].headers == {
        "X-Maru-Idempotency-Key": str(delivery.provider_idempotency_key)
    }
    assert "does not grant access to any convention" in messages[0].body
    assert repr(messages[0]) == "InvitationDeliveryMessage([redacted])"

    delivery.refresh_from_db()
    assert delivery.attempt_count == 1
    assert delivery.delivered_at is not None
    assert delivery.provider_reference == "synthetic-provider-reference-1"
    assert delivery.encrypted_payload is None
    assert delivery.wrapped_data_key is None
    assert delivery.payload_nonce is None
    assert delivery.payload_aad_digest == ""
    assert delivery.encryption_key_id == ""
    assert delivery.payload_destroyed_at is not None
    assert (
        delivery.payload_destruction_reason
        == PlatformIdentityDelivery.PayloadDestructionReason.DELIVERED
    )
    attempt = delivery.attempts.get()
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED
    assert attempt.provider_reference == "synthetic-provider-reference-1"
    assert attempt.safe_error_code == ""
    assert attempt.next_retry_at is None

    inventory_control.refresh_from_db()
    assert inventory_control.aggregate_version == version_before_worker + 2
    audits = list(
        AuditEvent.objects.filter(
            target_type="identity.platform_identity_delivery",
            target_id=delivery.id,
        ).order_by("occurred_at", "id")
    )
    assert [event.operation for event in audits] == [
        "identity.account_invitation.delivery_claim",
        "identity.account_invitation.delivery_result",
    ]
    assert all(event.principal_kind == "system" for event in audits)
    assert all(event.principal_id is None for event in audits)
    assert all(event.organization_id is None for event in audits)
    assert all(event.event_edition_id is None for event in audits)
    assert all(
        event.safe_metadata == {"contract_version": "page10-invitation-delivery-v1"}
        for event in audits
    )
    assert "example.invalid" not in json.dumps(
        [event.safe_metadata for event in audits],
        sort_keys=True,
    )

    replay_status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=_make_capturing_adapter(messages),
    )
    assert replay_status == PlatformIdentityDelivery.Status.DELIVERED
    assert len(messages) == 1
    assert delivery.attempts.count() == 1
    inventory_control.refresh_from_db()
    assert inventory_control.aggregate_version == version_before_worker + 2


def test_transient_failure_retries_with_the_same_provider_idempotency_key(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="transient-delivery",
    )
    observed_headers: list[dict[str, str]] = []

    def unavailable_adapter(message: InvitationDeliveryMessage) -> str:
        observed_headers.append(message.headers)
        raise ConnectionRefusedError("synthetic pre-connect provider outage")

    first_status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=unavailable_adapter,
    )

    assert first_status == PlatformIdentityDelivery.Status.RETRYING
    delivery.refresh_from_db()
    assert delivery.safe_error_code == "email_provider_unavailable"
    assert delivery.next_retry_at is not None
    assert delivery.payload_destroyed_at is None
    first_attempt = delivery.attempts.get(attempt_number=1)
    assert (
        first_attempt.outcome
        == PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE
    )
    assert first_attempt.safe_error_code == "email_provider_unavailable"
    assert first_attempt.next_retry_at == delivery.next_retry_at

    retry_time = delivery.next_retry_at + timedelta(seconds=1)

    def successful_retry_adapter(message: InvitationDeliveryMessage) -> str:
        observed_headers.append(message.headers)
        return "synthetic-provider-retry"

    with patch(
        "maru.identity.invitation_delivery.timezone.now",
        return_value=retry_time,
    ):
        second_status = deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=successful_retry_adapter,
        )

    assert second_status == PlatformIdentityDelivery.Status.DELIVERED
    delivery.refresh_from_db()
    assert delivery.attempt_count == 2
    assert list(delivery.attempts.values_list("attempt_number", "outcome")) == [
        (1, PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE),
        (2, PlatformIdentityDeliveryAttempt.Outcome.DELIVERED),
    ]
    assert observed_headers == [
        {"X-Maru-Idempotency-Key": str(delivery.provider_idempotency_key)},
        {"X-Maru-Idempotency-Key": str(delivery.provider_idempotency_key)},
    ]


def test_recipient_rejection_is_a_terminal_provider_failure(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="rejected-delivery",
    )

    def rejected_adapter(_message: InvitationDeliveryMessage) -> str:
        raise smtplib.SMTPRecipientsRefused(
            {"rejected-delivery@example.invalid": (550, b"synthetic rejection")}
        )

    status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=rejected_adapter,
    )

    assert status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    delivery.refresh_from_db()
    assert delivery.safe_error_code == "email_recipient_rejected"
    assert delivery.next_retry_at is None
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.NOT_REQUIRED
    )
    attempt = delivery.attempts.get()
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE
    assert attempt.safe_error_code == "email_recipient_rejected"


@pytest.mark.parametrize(
    "provider_failure",
    [
        smtplib.SMTPServerDisconnected("synthetic uncertain disconnect"),
        OSError("synthetic uncertain socket write"),
    ],
)
def test_ambiguous_provider_failure_is_quarantined_for_reconciliation(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
    provider_failure: BaseException,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="uncertain-delivery",
    )

    def disconnected_adapter(_message: InvitationDeliveryMessage) -> str:
        raise provider_failure

    status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=disconnected_adapter,
    )

    assert status == PlatformIdentityDelivery.Status.RETRYING
    delivery.refresh_from_db()
    assert delivery.safe_error_code == "email_delivery_uncertain"
    assert delivery.next_retry_at is not None
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
    assert delivery.reconciliation_required_at is not None
    attempt = delivery.attempts.get()
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN
    assert attempt.safe_error_code == "email_delivery_uncertain"
    assert attempt.next_retry_at is None


def test_transient_failure_at_attempt_limit_becomes_terminal(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="exhausted-delivery",
    )
    _set_code_owned_attempt_limit_for_test(delivery, max_attempts=1)

    def unavailable_adapter(_message: InvitationDeliveryMessage) -> str:
        raise ConnectionRefusedError("synthetic pre-connect provider outage")

    status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=unavailable_adapter,
    )

    assert status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    delivery.refresh_from_db()
    assert delivery.attempt_count == 1
    assert delivery.safe_error_code == "email_delivery_attempts_exhausted"
    assert delivery.next_retry_at is None
    attempt = delivery.attempts.get()
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE
    assert attempt.safe_error_code == "email_delivery_attempts_exhausted"
    assert attempt.next_retry_at is None


def test_missing_worker_key_is_retryable_without_releasing_ciphertext(
    configured_invitation_crypto: InvitationPrivateKeyring,
    invitation_private_key: rsa.RSAPrivateKey,
    platform_actor: Account,
) -> None:
    del configured_invitation_crypto
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="missing-key-delivery",
    )
    wrong_keyring = InvitationPrivateKeyring(
        {"different-rotation-key": invitation_private_key}
    )
    messages: list[InvitationDeliveryMessage] = []

    with pytest.raises(InvitationDeliveryDependencyError):
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=wrong_keyring,
            adapter=_make_capturing_adapter(messages),
        )

    assert messages == []
    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.PENDING
    assert delivery.attempt_count == 0
    assert delivery.safe_error_code == ""
    assert delivery.payload_destroyed_at is None
    assert delivery.encrypted_payload is not None
    assert delivery.attempts.count() == 0


def test_legacy_delivery_cannot_reconstruct_or_send_an_invitation_token(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    del configured_invitation_crypto
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="legacy-worker-exclusion",
    )
    challenge = delivery.challenge
    assert challenge.purpose == IdentityChallenge.Purpose.ACCOUNT_INVITATION

    with patch("maru.identity.services._dispatch_challenge_email") as dispatch:
        attempted, pending = deliver_pending_identity_challenges(limit=100)

        assert (attempted, pending) == (0, 0)
        with pytest.raises(
            ValueError,
            match="require the dedicated identity worker",
        ):
            deliver_identity_challenge(challenge.id)

    dispatch.assert_not_called()
    challenge.refresh_from_db()
    assert challenge.delivery_attempt_count == 0
    assert challenge.delivery_status == IdentityChallenge.DeliveryStatus.SUPPRESSED


def test_expired_processing_lease_is_recovered_with_contiguous_evidence(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="stale-lease-delivery",
    )
    stale_claimed_at = timezone.now()
    stale_lease_token = uuid4()
    stale_lease_expires_at = stale_claimed_at + timedelta(minutes=5)
    PlatformIdentityDelivery.objects.filter(id=delivery.id).update(
        status=PlatformIdentityDelivery.Status.PROCESSING,
        aggregate_version=F("aggregate_version") + 1,
        attempt_count=1,
        claimed_at=stale_claimed_at,
        lease_expires_at=stale_lease_expires_at,
        lease_token=stale_lease_token,
        last_attempt_at=stale_claimed_at,
    )
    messages: list[InvitationDeliveryMessage] = []

    with patch(
        "maru.identity.invitation_delivery.timezone.now",
        return_value=stale_lease_expires_at + timedelta(seconds=1),
    ):
        status = deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=_make_capturing_adapter(messages),
        )

    assert status == PlatformIdentityDelivery.Status.DELIVERED
    assert len(messages) == 1
    delivery.refresh_from_db()
    assert delivery.attempt_count == 2
    attempts = list(delivery.attempts.order_by("attempt_number"))
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert attempts[0].lease_token == stale_lease_token
    assert attempts[0].outcome == PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST
    assert attempts[0].safe_error_code
    assert attempts[1].outcome == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED


def test_expired_processing_lease_at_attempt_limit_becomes_reconcilable_terminal(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="stale-max-delivery",
    )
    _set_code_owned_attempt_limit_for_test(delivery, max_attempts=1)
    stale_claimed_at = timezone.now()
    stale_lease_expires_at = stale_claimed_at + timedelta(minutes=5)
    PlatformIdentityDelivery.objects.filter(id=delivery.id).update(
        status=PlatformIdentityDelivery.Status.PROCESSING,
        aggregate_version=F("aggregate_version") + 1,
        attempt_count=1,
        claimed_at=stale_claimed_at,
        lease_expires_at=stale_lease_expires_at,
        lease_token=uuid4(),
        last_attempt_at=stale_claimed_at,
    )
    messages: list[InvitationDeliveryMessage] = []

    with patch(
        "maru.identity.invitation_delivery.timezone.now",
        return_value=stale_lease_expires_at + timedelta(seconds=1),
    ):
        status = deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=_make_capturing_adapter(messages),
        )

    assert status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    assert messages == []
    delivery.refresh_from_db()
    assert delivery.safe_error_code == "delivery_attempts_exhausted"
    assert delivery.claimed_at is None
    assert delivery.lease_expires_at is None
    assert delivery.lease_token is None
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.REQUIRED
    )
    attempt = delivery.attempts.get(attempt_number=1)
    assert attempt.outcome == PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST

    replay_status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=_make_capturing_adapter(messages),
    )
    assert replay_status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    assert delivery.attempts.count() == 1

    resolved = resolve_platform_identity_delivery_for_retry(
        actor=platform_actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Authorize one bounded retry after reconciling the lost lease.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )
    delivery.refresh_from_db()
    assert resolved.replayed is False
    assert delivery.status == PlatformIdentityDelivery.Status.RETRYING
    assert delivery.max_attempts == 2
    assert delivery.reconciliation_state == (
        PlatformIdentityDelivery.ReconciliationState.RESOLVED
    )


def test_stale_lease_on_elapsed_invitation_settles_without_sending(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="stale-expired-delivery",
    )
    after_deadline = delivery.invitation.expires_at + timedelta(seconds=1)
    stale_claimed_at = after_deadline - timedelta(minutes=10)
    PlatformIdentityDelivery.objects.filter(id=delivery.id).update(
        status=PlatformIdentityDelivery.Status.PROCESSING,
        aggregate_version=F("aggregate_version") + 1,
        attempt_count=1,
        claimed_at=stale_claimed_at,
        lease_expires_at=stale_claimed_at + timedelta(minutes=5),
        lease_token=uuid4(),
        last_attempt_at=stale_claimed_at,
    )
    monkeypatch.setattr(
        "maru.identity.invitation_delivery.timezone.now",
        lambda: after_deadline,
    )
    messages: list[InvitationDeliveryMessage] = []

    status = deliver_platform_identity_invitation(
        delivery.id,
        private_keyring=configured_invitation_crypto,
        adapter=_make_capturing_adapter(messages),
    )

    assert status == PlatformIdentityDelivery.Status.PERMANENT_FAILED
    assert messages == []
    delivery.refresh_from_db()
    assert delivery.safe_error_code == "invitation_not_deliverable"
    assert delivery.claimed_at is None
    assert delivery.lease_token is None
    assert delivery.attempts.get().outcome == (
        PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST
    )


def test_management_command_delivers_with_worker_only_keyring(
    configured_invitation_crypto: InvitationPrivateKeyring,
    worker_private_key_environment: str,
    platform_actor: Account,
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    del configured_invitation_crypto
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"  # type: ignore[attr-defined]
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="command-delivery",
    )
    monkeypatch.setenv(
        PRIVATE_KEYRING_ENVIRONMENT,
        worker_private_key_environment,
    )
    output = io.StringIO()

    call_command(
        "platform_invitation_delivery",
        delivery_limit=10,
        stdout=output,
    )

    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.DELIVERED
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["command-delivery@example.invalid"]
    assert mail.outbox[0].extra_headers == {
        "X-Maru-Idempotency-Key": str(delivery.provider_idempotency_key)
    }
    assert _FRAGMENT_PATTERN.search(str(mail.outbox[0].body)) is not None
    assert (
        "Platform invitation delivery processed: 1 delivery "
        "attempts completed, 0 selected deliveries remain pending." in output.getvalue()
    )
    heartbeat = PlatformInvitationSchedulerRun.objects.get(
        kind=PlatformInvitationSchedulerRun.Kind.DELIVERY
    )
    assert heartbeat.generation == (
        PlatformInvitationSchedulerRun.Generation.DELIVERY_V1
    )
    assert heartbeat.processed_count == 1
    assert heartbeat.remaining_count == 0
    assert heartbeat.private_key_coverage_complete
    assert platform_invitation_delivery_heartbeat_is_ready()


def test_missing_retired_envelope_key_does_not_starve_healthy_batch(
    settings: object,
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    del configured_invitation_crypto
    old_private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    new_private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)

    def configure_public_key(key_id: str, private_key: rsa.RSAPrivateKey) -> None:
        public_key_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = key_id  # type: ignore[attr-defined]
        settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
            public_key_pem
        ).decode("ascii")

    configure_public_key("retired-envelope-key", old_private_key)
    unavailable = _new_delivery(
        actor=platform_actor,
        local_part="retired-envelope",
    )
    configure_public_key("healthy-envelope-key", new_private_key)
    healthy = _new_delivery(
        actor=platform_actor,
        local_part="healthy-envelope",
    )

    attempted, pending = deliver_pending_platform_identity_invitations(
        limit=10,
        private_keyring=InvitationPrivateKeyring(
            {"healthy-envelope-key": new_private_key}
        ),
        adapter=lambda _message: "synthetic:healthy-envelope",
    )

    unavailable.refresh_from_db()
    healthy.refresh_from_db()
    assert attempted == 1
    assert pending == 1
    assert unavailable.status == PlatformIdentityDelivery.Status.PENDING
    assert healthy.status == PlatformIdentityDelivery.Status.DELIVERED
    with (
        patch(
            "maru.identity.management.commands.platform_invitation_delivery."
            "worker_invitation_private_keyring",
            return_value=InvitationPrivateKeyring(
                {"healthy-envelope-key": new_private_key}
            ),
        ),
        pytest.raises(CommandError, match="key coverage is incomplete"),
    ):
        call_command("platform_invitation_delivery", delivery_limit=10)
    assert not PlatformInvitationSchedulerRun.objects.filter(
        kind=PlatformInvitationSchedulerRun.Kind.DELIVERY
    ).exists()


@pytest.mark.parametrize("delivery_limit", [0, 1_001, True])
def test_management_command_rejects_invalid_delivery_limit(
    delivery_limit: object,
) -> None:
    with pytest.raises(CommandError):
        call_command(
            "platform_invitation_delivery",
            delivery_limit=delivery_limit,
        )


@pytest.mark.parametrize("expiry_limit", [0, 1_001, True])
def test_expiry_command_rejects_invalid_limit(expiry_limit: object) -> None:
    with pytest.raises(CommandError):
        call_command("expire_platform_account_invitations", limit=expiry_limit)


def test_key_independent_expiry_command_expires_and_destroys_payload(
    configured_invitation_crypto: InvitationPrivateKeyring,
    worker_private_key_environment: str,
    platform_actor: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del configured_invitation_crypto
    delivery = _new_delivery(
        actor=platform_actor,
        local_part="expired-before-delivery",
    )
    invitation = delivery.invitation
    after_deadline = invitation.expires_at + timedelta(seconds=1)
    monkeypatch.setattr(
        "maru.identity.invitation_commands.timezone.now",
        lambda: after_deadline,
    )
    del worker_private_key_environment
    monkeypatch.delenv(PRIVATE_KEYRING_ENVIRONMENT, raising=False)
    output = io.StringIO()

    call_command(
        "expire_platform_account_invitations",
        limit=10,
        stdout=output,
    )

    invitation.refresh_from_db()
    delivery.refresh_from_db()
    assert invitation.status == PlatformAccountInvitation.Status.EXPIRED
    assert invitation.current_challenge_id is None
    assert invitation.expired_at == after_deadline
    assert (
        invitation.transitions.get(
            operation=PlatformAccountInvitationTransition.Operation.EXPIRED
        ).actor_id
        is None
    )
    assert delivery.status == PlatformIdentityDelivery.Status.CANCELLED
    assert delivery.attempt_count == 0
    assert delivery.payload_destroyed_at == after_deadline
    assert delivery.payload_destruction_reason == (
        PlatformIdentityDelivery.PayloadDestructionReason.EXPIRED
    )
    assert delivery.attempts.count() == 0
    assert "Platform invitation expiry processed: 1 expired." in output.getvalue()
    heartbeat = PlatformInvitationSchedulerRun.objects.get(
        kind=PlatformInvitationSchedulerRun.Kind.EXPIRY
    )
    assert heartbeat.generation == PlatformInvitationSchedulerRun.Generation.EXPIRY_V1
    assert heartbeat.processed_count == 1
    assert heartbeat.remaining_count == 0
    assert not heartbeat.private_key_coverage_complete
    monkeypatch.undo()
    assert platform_invitation_expiry_heartbeat_is_ready()


def test_scheduler_readiness_rejects_old_global_delivery_and_expiry_backlogs(
    configured_invitation_crypto: InvitationPrivateKeyring,
    platform_actor: Account,
) -> None:
    del configured_invitation_crypto
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.clock_timestamp()")
        observed_at = cursor.fetchone()[0]
    with patch(
        "django.utils.timezone.now",
        return_value=observed_at - timedelta(days=10),
    ):
        _new_delivery(actor=platform_actor, local_part="old-global-backlog")
    with connection.cursor() as cursor:
        for kind, generation, key_coverage in (
            ("delivery", "delivery-v1", True),
            ("expiry", "expiry-v1", False),
        ):
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
                )
                INSERT INTO identity_platforminvitationschedulerrun (
                    id, created_at, updated_at, kind, generation, ran_at,
                    processed_count, remaining_count,
                    private_key_coverage_complete, policy_digest,
                    inspected_count, blocked_count, held_count,
                    retention_cursor_transition_at,
                    retention_cursor_invitation_id
                )
                SELECT %s, recorded_at, recorded_at, %s, %s, recorded_at,
                       0, 1, %s, '', 0, 0, 0, NULL, NULL
                  FROM evidence
                RETURNING ran_at
                """,
                [uuid4(), kind, generation, key_coverage],
            )
            observed_at = cursor.fetchone()[0]

    assert not platform_invitation_delivery_heartbeat_is_ready()
    assert not platform_invitation_expiry_heartbeat_is_ready()
