from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_commands import revoke_platform_account_invitation
from maru.identity.invitation_delivery_reconciliation import (
    resolve_platform_identity_delivery_for_retry,
)
from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryReconciliationReceipt,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _encoded(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _platform_actor(*, label: str = "") -> Account:
    return Account.objects.create_superuser(
        email=f"db-hardening{label}-operator@example.invalid",
        password="Synthetic-db-hardening-operator-password-1!",
    )


def _reserved_person(*, label: str = "") -> Account:
    account = Account(
        email=f"db-hardening{label}-person@example.invalid",
        account_kind=Account.Kind.PERSON,
        is_active=False,
        is_staff=False,
        is_superuser=False,
        email_verified_at=None,
    )
    account.set_unusable_password()
    account.full_clean()
    account.save()
    return account


def _pending_graph(
    *,
    include_command_receipt: bool = True,
    max_attempts: int = 8,
    label: str = "",
) -> tuple[
    Account,
    PlatformAccountInvitation,
    IdentityChallenge,
    PlatformIdentityDelivery,
]:
    control, _created = PlatformAccountInventoryControl.objects.get_or_create(
        singleton=True,
        defaults={"aggregate_version": 0},
    )
    actor = _platform_actor(label=label)
    subject = _reserved_person(label=label)
    occurred_at = timezone.now()
    with transaction.atomic():
        invitation = PlatformAccountInvitation.objects.create(
            account=subject,
            created_by=actor,
            expires_at=occurred_at + timedelta(days=7),
            last_transition_at=occurred_at,
        )
        challenge = IdentityChallenge.objects.create(
            account=subject,
            purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
            token_digest=hashlib.sha256(f"token{label}".encode()).hexdigest(),
            token_digest_key_id="db-hardening-digest-v1",
            email_snapshot=subject.email,
            expires_at=invitation.expires_at,
            request_fingerprint="2" * 64,
            invitation=invitation,
            invitation_version=1,
            delivery_status=IdentityChallenge.DeliveryStatus.SUPPRESSED,
        )
        delivery = PlatformIdentityDelivery.objects.create(
            invitation=invitation,
            challenge=challenge,
            encryption_algorithm="aes-256-gcm+rsa-oaep-sha256-v1",
            encryption_key_id="db-hardening-envelope-v1",
            encrypted_payload=_encoded(b"p" * 17),
            wrapped_data_key=_encoded(b"k" * 256),
            payload_nonce=b"n" * 12,
            payload_aad_digest="3" * 64,
            max_attempts=max_attempts,
        )
        invitation.current_challenge = challenge
        invitation.save(update_fields=("current_challenge", "updated_at"))
        correlation_id = uuid4()
        PlatformAccountInvitationTransition.objects.create(
            invitation=invitation,
            version=1,
            operation=PlatformAccountInvitationTransition.Operation.CREATED,
            actor=actor,
            occurred_at=occurred_at,
            reason="Create synthetic database-hardening evidence.",
            correlation_id=correlation_id,
            source_channel="integration_test",
        )
        if include_command_receipt:
            PlatformAccountInvitationCommandReceipt.objects.create(
                inventory_control=control,
                invitation=invitation,
                actor=actor,
                operation=PlatformAccountInvitationCommandReceipt.Operation.CREATE,
                retry_key=uuid4(),
                request_digest="4" * 64,
                expected_version=0,
                result_version=1,
                correlation_id=correlation_id,
                source_channel="integration_test",
            )
    return actor, invitation, challenge, delivery


def _claim_raw(
    delivery: PlatformIdentityDelivery,
) -> tuple[UUID, datetime, datetime]:
    delivery.refresh_from_db()
    claimed_at = max(timezone.now(), delivery.created_at)
    lease_expires_at = claimed_at + timedelta(minutes=5)
    lease_token = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET status = 'processing', "
            "aggregate_version = aggregate_version + 1, "
            "attempt_count = attempt_count + 1, claimed_at = %s, "
            "lease_expires_at = %s, lease_token = %s, "
            "last_attempt_at = %s, next_retry_at = NULL, "
            "safe_error_code = '', updated_at = %s WHERE id = %s",
            [
                claimed_at,
                lease_expires_at,
                lease_token,
                claimed_at,
                claimed_at,
                delivery.id,
            ],
        )
    delivery.refresh_from_db()
    return lease_token, claimed_at, lease_expires_at


def _settle_lost_lease_raw(
    delivery: PlatformIdentityDelivery,
    *,
    lease_token: UUID,
    started_at: datetime,
    lease_expires_at: datetime,
) -> datetime:
    finished_at = lease_expires_at + timedelta(seconds=1)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'lease_lost', '', "
            "'delivery_lease_expired', NULL, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                delivery.attempt_count,
                lease_token,
                started_at,
                finished_at,
                delivery.id,
            ],
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET status = 'retrying', aggregate_version = aggregate_version + 1, "
            "claimed_at = NULL, lease_expires_at = NULL, lease_token = NULL, "
            "available_at = %s, next_retry_at = %s, "
            "safe_error_code = 'delivery_lease_expired', updated_at = %s "
            "WHERE id = %s",
            [finished_at, finished_at, finished_at, delivery.id],
        )
    delivery.refresh_from_db()
    return finished_at


def _settle_uncertain_raw(
    delivery: PlatformIdentityDelivery,
    *,
    lease_token: UUID,
    started_at: datetime,
) -> datetime:
    finished_at = max(timezone.now(), started_at)
    retry_at = finished_at + timedelta(minutes=1)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'uncertain', '', "
            "'email_delivery_uncertain', NULL, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                delivery.attempt_count,
                lease_token,
                started_at,
                finished_at,
                delivery.id,
            ],
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET status = 'retrying', aggregate_version = aggregate_version + 1, "
            "claimed_at = NULL, lease_expires_at = NULL, lease_token = NULL, "
            "available_at = %s, next_retry_at = %s, "
            "safe_error_code = 'email_delivery_uncertain', "
            "reconciliation_state = 'required', "
            "reconciliation_required_at = %s, updated_at = %s WHERE id = %s",
            [retry_at, retry_at, finished_at, finished_at, delivery.id],
        )
    delivery.refresh_from_db()
    return finished_at


def _append_reconciliation_audit(
    *,
    actor_id: UUID,
    delivery_id: UUID,
    operation: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="identity.reconcile_account_invitation_delivery",
            operation="identity.account_invitation.delivery_reconcile",
            target_type="identity.platform_identity_delivery",
            target_id=delivery_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=operation,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=("delivery", "reconciliation", "receipt"),
            safe_metadata={
                "contract_version": ("page10-invitation-delivery-reconciliation-v1")
            },
            retention_class="identity-restricted",
            idempotency_key_hash=hashlib.sha256(retry_key.bytes).hexdigest(),
        ),
        occurred_at=occurred_at,
    )


def test_raw_deferred_fk_child_first_parent_later_is_rejected() -> None:
    actor = _platform_actor()
    missing_invitation_id = uuid4()
    occurred_at = timezone.now()

    with (
        pytest.raises(DatabaseError, match="transition parent is unavailable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO identity_platformaccountinvitationtransition "
            "(id, created_at, updated_at, version, operation, occurred_at, "
            "reason, correlation_id, source_channel, actor_id, invitation_id) "
            "VALUES (%s, %s, %s, 1, 'created', %s, %s, %s, "
            "'integration_test', %s, %s)",
            [
                uuid4(),
                occurred_at,
                occurred_at,
                occurred_at,
                "A deferred foreign key must not bypass parent validation.",
                uuid4(),
                actor.id,
                missing_invitation_id,
            ],
        )


def test_nonexpiry_transition_requires_exact_command_receipt() -> None:
    with pytest.raises(
        DatabaseError,
        match="non-expiry invitation transition lacks exact command receipt",
    ):
        _pending_graph(include_command_receipt=False)


def test_nonexpiry_transition_rejects_duplicate_exact_receipts() -> None:
    actor, invitation, _challenge, _delivery = _pending_graph()
    transition = invitation.transitions.get(version=1)
    control = PlatformAccountInventoryControl.objects.get(singleton=True)

    with (
        pytest.raises(
            DatabaseError,
            match="identity_invitation_result_receipt_unique",
        ),
        transaction.atomic(),
    ):
        PlatformAccountInvitationCommandReceipt.objects.bulk_create(
            [
                PlatformAccountInvitationCommandReceipt(
                    inventory_control=control,
                    invitation=invitation,
                    actor=actor,
                    operation=(
                        PlatformAccountInvitationCommandReceipt.Operation.CREATE
                    ),
                    retry_key=uuid4(),
                    request_digest="5" * 64,
                    expected_version=0,
                    result_version=1,
                    correlation_id=transition.correlation_id,
                    source_channel=transition.source_channel,
                )
            ]
        )


def test_concurrent_distinct_retry_keys_create_one_command_receipt() -> None:
    actor, invitation, _challenge, _delivery = _pending_graph()
    transition = invitation.transitions.get(version=1)
    receipt = invitation.command_receipts.get(result_version=1)

    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE identity_platformaccountinvitationcommandreceipt "
            "DISABLE TRIGGER identity_page10_receipt_immutable"
        )
        cursor.execute(
            "DELETE FROM identity_platformaccountinvitationcommandreceipt "
            "WHERE id = %s",
            [receipt.id],
        )
        cursor.execute(
            "ALTER TABLE identity_platformaccountinvitationcommandreceipt "
            "ENABLE TRIGGER identity_page10_receipt_immutable"
        )

    ready = Barrier(2)

    def insert_receipt(retry_key: UUID) -> str:
        close_old_connections()
        try:
            ready.wait(timeout=15)
            with transaction.atomic():
                PlatformAccountInvitationCommandReceipt.objects.bulk_create(
                    [
                        PlatformAccountInvitationCommandReceipt(
                            inventory_control_id=True,
                            invitation_id=invitation.id,
                            actor_id=actor.id,
                            operation=(
                                PlatformAccountInvitationCommandReceipt.Operation.CREATE
                            ),
                            retry_key=retry_key,
                            request_digest=hashlib.sha256(retry_key.bytes).hexdigest(),
                            expected_version=0,
                            result_version=1,
                            correlation_id=transition.correlation_id,
                            source_channel=transition.source_channel,
                        )
                    ]
                )
        except DatabaseError:
            return "rejected"
        else:
            return "committed"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert_receipt, uuid4()) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]

    assert sorted(results) == ["committed", "rejected"]
    assert invitation.command_receipts.filter(result_version=1).count() == 1


def test_initial_delivery_attempt_limit_is_code_owned() -> None:
    with pytest.raises(
        DatabaseError,
        match="identity delivery initial state is inconsistent",
    ):
        _pending_graph(max_attempts=100)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("receipt", "receipt parent is unavailable"),
        ("attempt", "attempt parent is unavailable"),
        ("late_outcome", "late delivery outcome parent is unavailable"),
        ("reconciliation", "reconciliation parent is unavailable"),
    ],
)
def test_raw_child_guards_reject_missing_deferred_parents(
    case: str,
    message: str,
) -> None:
    actor = _platform_actor()
    missing_parent_id = uuid4()
    occurred_at = timezone.now()

    def insert_missing_child() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            if case == "receipt":
                cursor.execute(
                    "INSERT INTO identity_platformaccountinvitationcommandreceipt "
                    "(id, created_at, updated_at, operation, retry_key, "
                    "request_digest, expected_version, result_version, "
                    "correlation_id, source_channel, actor_id, invitation_id, "
                    "inventory_control_id) VALUES (%s, %s, %s, 'create', %s, "
                    "%s, 0, 1, %s, 'integration_test', %s, %s, true)",
                    [
                        uuid4(),
                        occurred_at,
                        occurred_at,
                        uuid4(),
                        "5" * 64,
                        uuid4(),
                        actor.id,
                        missing_parent_id,
                    ],
                )
            elif case == "attempt":
                cursor.execute(
                    "INSERT INTO identity_platformidentitydeliveryattempt "
                    "(id, created_at, updated_at, attempt_number, lease_token, "
                    "started_at, finished_at, outcome, provider_reference, "
                    "safe_error_code, next_retry_at, delivery_id) VALUES "
                    "(%s, %s, %s, 1, %s, %s, %s, 'uncertain', '', "
                    "'email_delivery_uncertain', NULL, %s)",
                    [
                        uuid4(),
                        occurred_at,
                        occurred_at,
                        uuid4(),
                        occurred_at,
                        occurred_at,
                        missing_parent_id,
                    ],
                )
            elif case == "late_outcome":
                cursor.execute(
                    "INSERT INTO identity_platformidentitydeliverylateoutcome "
                    "(id, created_at, updated_at, attempt_number, lease_token, "
                    "observed_at, outcome, classification, provider_reference, "
                    "safe_error_code, delivery_id) VALUES (%s, %s, %s, 1, %s, "
                    "%s, 'delivered', 'lease_superseded', %s, '', %s)",
                    [
                        uuid4(),
                        occurred_at,
                        occurred_at,
                        uuid4(),
                        occurred_at,
                        "synthetic-missing-parent-provider",
                        missing_parent_id,
                    ],
                )
            else:
                cursor.execute(
                    "INSERT INTO "
                    "identity_platformidentitydeliveryreconciliationreceipt "
                    "(id, created_at, updated_at, operation, reason, retry_key, "
                    "request_digest, expected_version, result_version, "
                    "correlation_id, source_channel, actor_id, delivery_id, "
                    "inventory_control_id) VALUES (%s, %s, %s, "
                    "'resolve_retry', %s, %s, %s, 1, 2, %s, "
                    "'integration_test', %s, %s, true)",
                    [
                        uuid4(),
                        occurred_at,
                        occurred_at,
                        "Reject missing reconciliation parent evidence.",
                        uuid4(),
                        "6" * 64,
                        uuid4(),
                        actor.id,
                        missing_parent_id,
                    ],
                )

    with pytest.raises(DatabaseError, match=message):
        insert_missing_child()


def test_invitation_challenge_origin_remains_frozen_after_terminalization() -> None:
    actor, invitation, challenge, _delivery = _pending_graph()
    revoke_platform_account_invitation(
        actor=actor,
        invitation_id=invitation.id,
        expected_version=1,
        reason="Terminalize the synthetic invitation before the rewrite probe.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )

    with (
        pytest.raises(DatabaseError, match="origin and digest-key lineage"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_identitychallenge "
            "SET purpose = 'verify_email', invitation_id = NULL, "
            "invitation_version = NULL, token_digest_key_id = '' WHERE id = %s",
            [challenge.id],
        )


def test_raw_terminal_delivery_rewrite_is_rejected() -> None:
    actor, invitation, _challenge, delivery = _pending_graph()
    revoke_platform_account_invitation(
        actor=actor,
        invitation_id=invitation.id,
        expected_version=1,
        reason="Cancel the synthetic delivery before the terminal rewrite probe.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    delivery.refresh_from_db()

    with (
        pytest.raises(DatabaseError, match="cancelled timestamp is immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "cancelled_at = cancelled_at + interval '1 second' WHERE id = %s",
            [delivery.id],
        )


def test_raw_delivery_cancellation_requires_invitation_lifecycle() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    cancelled_at = max(timezone.now(), delivery.created_at)

    with (
        pytest.raises(
            DatabaseError,
            match="cancellation lacks invitation lifecycle evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery SET status = 'cancelled', "
            "aggregate_version = aggregate_version + 1, "
            "cancellation_requested_at = %s, "
            "cancellation_code = 'invitation_revoked', cancelled_at = %s, "
            "safe_error_code = 'invitation_revoked', encryption_algorithm = '', "
            "encryption_key_id = '', encrypted_payload = NULL, "
            "wrapped_data_key = NULL, payload_nonce = NULL, "
            "payload_aad_digest = '', payload_destroyed_at = %s, "
            "payload_destruction_reason = 'revoked', updated_at = %s "
            "WHERE id = %s",
            [
                cancelled_at,
                cancelled_at,
                cancelled_at,
                cancelled_at,
                delivery.id,
            ],
        )


def test_raw_attempt_with_mismatched_lease_is_rejected() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    _lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    finished_at = started_at + timedelta(seconds=1)

    with (
        pytest.raises(DatabaseError, match="attempt lineage is inconsistent"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, 1, %s, %s, %s, 'uncertain', '', "
            "'email_delivery_uncertain', NULL, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                uuid4(),
                started_at,
                finished_at,
                delivery.id,
            ],
        )


def test_raw_attempt_then_parent_finalization_preserves_worker_order() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    finished_at = started_at + timedelta(seconds=1)
    provider_reference = "synthetic-raw-child-first-provider"

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, 1, %s, %s, %s, 'delivered', %s, '', NULL, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                lease_token,
                started_at,
                finished_at,
                provider_reference,
                delivery.id,
            ],
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery SET status = 'delivered', "
            "aggregate_version = aggregate_version + 1, claimed_at = NULL, "
            "lease_expires_at = NULL, lease_token = NULL, delivered_at = %s, "
            "provider_reference = %s, encryption_algorithm = '', "
            "encryption_key_id = '', encrypted_payload = NULL, "
            "wrapped_data_key = NULL, payload_nonce = NULL, "
            "payload_aad_digest = '', payload_destroyed_at = %s, "
            "payload_destruction_reason = 'delivered', updated_at = %s "
            "WHERE id = %s",
            [
                finished_at,
                provider_reference,
                finished_at,
                finished_at,
                delivery.id,
            ],
        )

    delivery.refresh_from_db()
    assert delivery.status == PlatformIdentityDelivery.Status.DELIVERED
    assert delivery.attempts.get().lease_token == lease_token


def test_raw_parent_result_must_match_the_leased_attempt_outcome() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    finished_at = started_at + timedelta(seconds=1)
    retry_at = finished_at + timedelta(minutes=1)

    with (  # noqa: PT012 - attempt and contradictory parent are one mutation
        pytest.raises(
            DatabaseError,
            match="delivered state does not match leased attempt evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, 1, %s, %s, %s, 'transient_failure', '', "
            "'email_provider_unavailable', %s, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                lease_token,
                started_at,
                finished_at,
                retry_at,
                delivery.id,
            ],
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery SET status = 'delivered', "
            "aggregate_version = aggregate_version + 1, claimed_at = NULL, "
            "lease_expires_at = NULL, lease_token = NULL, delivered_at = %s, "
            "provider_reference = %s, encryption_algorithm = '', "
            "encryption_key_id = '', encrypted_payload = NULL, "
            "wrapped_data_key = NULL, payload_nonce = NULL, "
            "payload_aad_digest = '', payload_destroyed_at = %s, "
            "payload_destruction_reason = 'delivered', updated_at = %s "
            "WHERE id = %s",
            [
                finished_at,
                "synthetic-contradictory-provider",
                finished_at,
                finished_at,
                delivery.id,
            ],
        )


def test_raw_nonprocessing_delivery_requires_exact_reconciliation() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    assert delivery.reconciliation_required_at is not None
    resolved_at = max(timezone.now(), delivery.reconciliation_required_at)

    with (
        pytest.raises(
            DatabaseError,
            match="operator reconciliation lacks exact receipt evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery SET status = 'delivered', "
            "aggregate_version = aggregate_version + 1, delivered_at = %s, "
            "provider_reference = %s, next_retry_at = NULL, "
            "safe_error_code = '', encryption_algorithm = '', "
            "encryption_key_id = '', encrypted_payload = NULL, "
            "wrapped_data_key = NULL, payload_nonce = NULL, "
            "payload_aad_digest = '', payload_destroyed_at = %s, "
            "payload_destruction_reason = 'delivered', "
            "reconciliation_state = 'resolved', reconciled_at = %s, "
            "reconciliation_code = 'operator_confirmed_delivered', "
            "updated_at = %s "
            "WHERE id = %s",
            [
                resolved_at,
                "synthetic-unreconciled-provider",
                resolved_at,
                resolved_at,
                resolved_at,
                delivery.id,
            ],
        )

    with (
        pytest.raises(
            DatabaseError,
            match="operator reconciliation lacks exact receipt evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "reconciliation_state = 'resolved', reconciled_at = %s, "
            "reconciliation_code = 'fake_resolution', updated_at = %s "
            "WHERE id = %s",
            [resolved_at, resolved_at, delivery.id],
        )

    with (
        pytest.raises(
            DatabaseError,
            match="retrying delivery changed state without reconciliation",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "available_at = %s, next_retry_at = %s, "
            "safe_error_code = 'fabricated_retry', updated_at = %s "
            "WHERE id = %s",
            [resolved_at, resolved_at, resolved_at, delivery.id],
        )


def test_raw_fake_late_result_without_lost_lease_lineage_is_rejected() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, lease_expires_at = _claim_raw(delivery)
    finished_at = _settle_lost_lease_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
        lease_expires_at=lease_expires_at,
    )

    with (
        pytest.raises(DatabaseError, match="lacks lost-lease lineage"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliverylateoutcome "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "observed_at, outcome, classification, provider_reference, "
            "safe_error_code, delivery_id) VALUES (%s, %s, %s, 1, %s, %s, "
            "'delivered', 'lease_superseded', %s, '', %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                uuid4(),
                finished_at,
                "synthetic-fake-late-provider",
                delivery.id,
            ],
        )


def test_raw_wrong_reconciliation_operation_is_rejected() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    expected_version = delivery.aggregate_version
    resolved_at = timezone.now()

    def write_wrong_reconciliation() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE identity_platformidentitydelivery "
                "SET aggregate_version = aggregate_version + 1, "
                "status = 'retrying', available_at = %s, next_retry_at = %s, "
                "safe_error_code = 'delivery_reconciliation_retry', "
                "reconciliation_state = 'resolved', reconciled_at = %s, "
                "reconciliation_code = 'operator_confirmed_retry', "
                "updated_at = %s WHERE id = %s",
                [resolved_at, resolved_at, resolved_at, resolved_at, delivery.id],
            )
            cursor.execute(
                "INSERT INTO "
                "identity_platformidentitydeliveryreconciliationreceipt "
                "(id, created_at, updated_at, operation, reason, retry_key, "
                "request_digest, expected_version, result_version, "
                "correlation_id, source_channel, actor_id, delivery_id, "
                "inventory_control_id) VALUES (%s, clock_timestamp(), "
                "clock_timestamp(), 'resolve_delivered', %s, %s, %s, %s, %s, "
                "%s, 'integration_test', %s, %s, true)",
                [
                    uuid4(),
                    "Deliberately mismatched synthetic reconciliation.",
                    uuid4(),
                    "4" * 64,
                    expected_version,
                    expected_version + 1,
                    uuid4(),
                    actor.id,
                    delivery.id,
                ],
            )

    with pytest.raises(DatabaseError, match="reconciliation result is inconsistent"):
        write_wrong_reconciliation()


def test_resolved_reconciliation_is_frozen_without_new_uncertainty() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    resolve_platform_identity_delivery_for_retry(
        actor=actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Resolve the synthetic uncertainty before tamper probes.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    delivery.refresh_from_db()
    assert delivery.reconciliation_state == "resolved"
    assert delivery.reconciled_at is not None
    reopened_at = delivery.reconciled_at + timedelta(seconds=1)

    with (
        pytest.raises(
            DatabaseError,
            match="resolved reconciliation evidence is immutable",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "reconciliation_code = 'tampered_resolution', updated_at = %s "
            "WHERE id = %s",
            [reopened_at, delivery.id],
        )

    with (
        pytest.raises(
            DatabaseError,
            match="reopening reconciliation requires exact uncertainty evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "reconciliation_state = 'required', "
            "reconciliation_required_at = %s, reconciled_at = NULL, "
            "reconciliation_code = '', updated_at = %s WHERE id = %s",
            [reopened_at, reopened_at, delivery.id],
        )


def test_later_reconciliation_receipt_cannot_reuse_an_older_audit() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    resolved = resolve_platform_identity_delivery_for_retry(
        actor=actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Create genuine evidence before the forged audit-reuse probe.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    delivery.refresh_from_db()
    old_receipt = resolved.receipt
    forged_retry_key = uuid4()
    forged_created_at = old_receipt.created_at - timedelta(microseconds=1)
    forged_result_version = delivery.aggregate_version + 1

    with (  # noqa: PT012 - forged parent and child must commit atomically
        pytest.raises(
            DatabaseError,
            match="reconciliation receipt lacks exact audit evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = %s, updated_at = clock_timestamp() "
            "WHERE id = %s",
            [forged_result_version, delivery.id],
        )
        cursor.execute(
            "INSERT INTO "
            "identity_platformidentitydeliveryreconciliationreceipt "
            "(id, created_at, updated_at, operation, reason, retry_key, "
            "request_digest, expected_version, result_version, "
            "correlation_id, source_channel, actor_id, delivery_id, "
            "inventory_control_id) VALUES (%s, %s, %s, 'resolve_retry', %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, true)",
            [
                uuid4(),
                forged_created_at,
                forged_created_at,
                "Forge a later receipt that reuses older audit coordinates.",
                forged_retry_key,
                old_receipt.request_digest,
                delivery.aggregate_version,
                forged_result_version,
                old_receipt.correlation_id,
                old_receipt.source_channel,
                actor.id,
                delivery.id,
            ],
        )


def test_later_duplicate_reconciliation_audit_is_rejected() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    resolved = resolve_platform_identity_delivery_for_retry(
        actor=actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Create genuine evidence before the duplicate-audit probe.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    audit = AuditEvent.objects.get(correlation_id=resolved.receipt.correlation_id)

    with (
        pytest.raises(
            DatabaseError,
            match="audit_identity_reconcile_retry_unique",
        ),
        transaction.atomic(),
    ):
        AuditEvent.objects.bulk_create(
            [
                AuditEvent(
                    schema_version=audit.schema_version,
                    occurred_at=audit.occurred_at,
                    principal_kind=audit.principal_kind,
                    principal_id=audit.principal_id,
                    principal_context_id=audit.principal_context_id,
                    organization_id=audit.organization_id,
                    event_edition_id=audit.event_edition_id,
                    capability_code=audit.capability_code,
                    operation=audit.operation,
                    target_type=audit.target_type,
                    target_id=audit.target_id,
                    outcome=audit.outcome,
                    reason_code=audit.reason_code,
                    obligations=audit.obligations,
                    changed_fields=audit.changed_fields,
                    correlation_id=audit.correlation_id,
                    causation_id=audit.causation_id,
                    request_id=audit.request_id,
                    idempotency_key_hash=audit.idempotency_key_hash,
                    source_channel=audit.source_channel,
                    delegated=audit.delegated,
                    elevated=audit.elevated,
                    break_glass=audit.break_glass,
                    safe_metadata=audit.safe_metadata,
                    retention_class=audit.retention_class,
                    integrity_batch_id=audit.integrity_batch_id,
                )
            ]
        )


def test_concurrent_distinct_retry_keys_create_one_reconciliation_receipt() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=lease_token,
        started_at=started_at,
    )
    resolve_platform_identity_delivery_for_retry(
        actor=actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Create the prior reconciliation version for the race probe.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    delivery.refresh_from_db()
    expected_version = delivery.aggregate_version
    result_version = expected_version + 1
    reconciled_at = delivery.reconciled_at
    assert reconciled_at is not None

    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery DISABLE TRIGGER "
            "identity_page10_hardened_delivery_complete"
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = %s, updated_at = clock_timestamp() "
            "WHERE id = %s",
            [result_version, delivery.id],
        )
        cursor.execute(
            "ALTER TABLE identity_platformidentitydelivery ENABLE TRIGGER "
            "identity_page10_hardened_delivery_complete"
        )

    ready = Barrier(2)

    def insert_receipt(retry_key: UUID) -> str:
        close_old_connections()
        correlation_id = uuid4()
        try:
            ready.wait(timeout=15)
            with transaction.atomic():
                PlatformIdentityDeliveryReconciliationReceipt.objects.bulk_create(
                    [
                        PlatformIdentityDeliveryReconciliationReceipt(
                            inventory_control_id=True,
                            delivery_id=delivery.id,
                            actor_id=actor.id,
                            operation=(
                                PlatformIdentityDeliveryReconciliationReceipt.Operation.RESOLVE_RETRY
                            ),
                            reason="Resolve the synthetic concurrent receipt race.",
                            retry_key=retry_key,
                            request_digest=hashlib.sha256(retry_key.bytes).hexdigest(),
                            expected_version=expected_version,
                            result_version=result_version,
                            correlation_id=correlation_id,
                            source_channel="integration_test",
                        )
                    ]
                )
                _append_reconciliation_audit(
                    actor_id=actor.id,
                    delivery_id=delivery.id,
                    operation=(
                        PlatformIdentityDeliveryReconciliationReceipt.Operation.RESOLVE_RETRY
                    ),
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                    source_channel="integration_test",
                    occurred_at=reconciled_at,
                )
        except DatabaseError:
            return "rejected"
        else:
            return "committed"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert_receipt, uuid4()) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]

    assert sorted(results) == ["committed", "rejected"]
    assert (
        delivery.reconciliation_receipts.filter(result_version=result_version).count()
        == 1
    )


def test_forward_validation_accepts_historical_retry_receipt_after_delivery() -> None:
    actor, _invitation, _challenge, delivery = _pending_graph()
    first_lease, first_started_at, _first_lease_expires_at = _claim_raw(delivery)
    _settle_uncertain_raw(
        delivery,
        lease_token=first_lease,
        started_at=first_started_at,
    )
    resolve_platform_identity_delivery_for_retry(
        actor=actor,
        delivery_id=delivery.id,
        expected_version=delivery.aggregate_version,
        reason="Resolve uncertainty before a successful synthetic retry.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="integration_test",
    )
    second_lease, second_started_at, _second_lease_expires_at = _claim_raw(delivery)
    delivered_at = second_started_at + timedelta(seconds=1)
    provider_reference = "synthetic-historical-receipt-provider"
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) "
            "VALUES (%s, %s, %s, 2, %s, %s, %s, 'delivered', %s, '', NULL, %s)",
            [
                uuid4(),
                delivered_at,
                delivered_at,
                second_lease,
                second_started_at,
                delivered_at,
                provider_reference,
                delivery.id,
            ],
        )
        cursor.execute(
            "UPDATE identity_platformidentitydelivery SET status = 'delivered', "
            "aggregate_version = aggregate_version + 1, claimed_at = NULL, "
            "lease_expires_at = NULL, lease_token = NULL, delivered_at = %s, "
            "provider_reference = %s, encryption_algorithm = '', "
            "encryption_key_id = '', encrypted_payload = NULL, "
            "wrapped_data_key = NULL, payload_nonce = NULL, "
            "payload_aad_digest = '', payload_destroyed_at = %s, "
            "payload_destruction_reason = 'delivered', updated_at = %s "
            "WHERE id = %s",
            [
                delivered_at,
                provider_reference,
                delivered_at,
                delivered_at,
                delivery.id,
            ],
        )

    migration = import_module(
        "maru.identity.migrations.0014_invitation_delivery_integrity"
    )
    schema_editor = SimpleNamespace(connection=connection)
    with transaction.atomic():
        migration.validate_existing_page10_delivery_history(None, schema_editor)


def test_raw_retry_timestamp_must_follow_attempt_completion() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    lease_token, started_at, _lease_expires_at = _claim_raw(delivery)
    finished_at = started_at + timedelta(seconds=1)

    with (
        pytest.raises(DatabaseError, match="retry chronology is inconsistent"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) VALUES (%s, %s, %s, "
            "1, %s, %s, %s, 'transient_failure', '', "
            "'email_provider_unavailable', %s, %s)",
            [
                uuid4(),
                finished_at,
                finished_at,
                lease_token,
                started_at,
                finished_at,
                finished_at,
                delivery.id,
            ],
        )


def test_forward_validation_rejects_an_old_legal_incomplete_attempt_graph() -> None:
    _actor, _invitation, _challenge, delivery = _pending_graph()
    migration = import_module(
        "maru.identity.migrations.0014_invitation_delivery_integrity"
    )
    schema_editor = SimpleNamespace(connection=connection)
    occurred_at = max(timezone.now(), delivery.created_at)

    with (  # noqa: PT012 - migration preflight observes one raw tamper
        pytest.raises(DatabaseError, match="attempt history is incomplete"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE identity_platformidentitydeliveryattempt DISABLE TRIGGER "
            "identity_page10_hardened_attempt_insert"
        )
        cursor.execute(
            "ALTER TABLE identity_platformidentitydeliveryattempt DISABLE TRIGGER "
            "identity_page10_hardened_attempt_complete"
        )
        cursor.execute(
            "INSERT INTO identity_platformidentitydeliveryattempt "
            "(id, created_at, updated_at, attempt_number, lease_token, "
            "started_at, finished_at, outcome, provider_reference, "
            "safe_error_code, next_retry_at, delivery_id) VALUES "
            "(%s, %s, %s, 1, %s, %s, %s, 'uncertain', '', "
            "'email_delivery_uncertain', NULL, %s)",
            [
                uuid4(),
                occurred_at,
                occurred_at,
                uuid4(),
                occurred_at,
                occurred_at,
                delivery.id,
            ],
        )
        migration.validate_existing_page10_delivery_history(None, schema_editor)


def test_forward_validation_rejects_old_mismatched_command_receipt() -> None:
    _actor, invitation, _challenge, _delivery = _pending_graph()
    migration = import_module(
        "maru.identity.migrations.0014_invitation_delivery_integrity"
    )
    schema_editor = SimpleNamespace(connection=connection)
    receipt = invitation.command_receipts.get(result_version=1)

    with (  # noqa: PT012 - migration preflight observes one raw tamper
        pytest.raises(
            DatabaseError,
            match="non-expiry invitation transition lacks exact command receipt",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE identity_platformaccountinvitationcommandreceipt "
            "DISABLE TRIGGER identity_page10_receipt_immutable"
        )
        cursor.execute(
            "UPDATE identity_platformaccountinvitationcommandreceipt "
            "SET correlation_id = %s WHERE id = %s",
            [uuid4(), receipt.id],
        )
        migration.validate_existing_page10_delivery_history(None, schema_editor)


def test_clean_rollback_guard_holds_writer_fencing_locks() -> None:
    migration = import_module(
        "maru.identity.migrations.0014_invitation_delivery_integrity"
    )
    schema_editor = SimpleNamespace(connection=connection)
    protected_tables = {
        "identity_platformaccountinvitation",
        "identity_platformaccountinvitationtransition",
        "identity_platformaccountinvitationcommandreceipt",
        "identity_identitychallenge",
        "identity_platformidentitydelivery",
        "identity_platformidentitydeliveryattempt",
        "identity_platformidentitydeliverylateoutcome",
        "identity_platformidentitydeliveryreconciliationreceipt",
    }

    with transaction.atomic(), connection.cursor() as cursor:
        migration.refuse_live_page10_recovery_rollback(None, schema_editor)
        cursor.execute(
            "SELECT relation::regclass::text FROM pg_locks "
            "WHERE pid = pg_backend_pid() AND mode = 'ShareRowExclusiveLock' "
            "AND relation::regclass::text = ANY(%s)",
            [list(protected_tables)],
        )
        locked_tables = {row[0] for row in cursor.fetchall()}

    assert locked_tables == protected_tables


def test_live_invitation_evidence_refuses_guard_rollback() -> None:
    _pending_graph()
    migration = import_module(
        "maru.identity.migrations.0014_invitation_delivery_integrity"
    )
    schema_editor = SimpleNamespace(connection=connection)

    with transaction.atomic(), pytest.raises(RuntimeError, match="rollback refused"):
        migration.refuse_live_page10_recovery_rollback(None, schema_editor)


def test_invitation_origin_rejects_forged_insert_but_allows_ordinary_account() -> None:
    _actor, invitation, _challenge, _delivery = _pending_graph()
    forged = Account(
        email="forged-origin@example.invalid",
        account_kind=Account.Kind.PERSON,
        is_active=False,
        invitation_provisioning_origin=invitation,
    )
    forged.set_unusable_password()

    with (
        pytest.raises(
            DatabaseError,
            match="invitation provisioning origin lacks exact creation lineage",
        ),
        transaction.atomic(),
    ):
        Account.objects.bulk_create([forged])

    ordinary = Account(
        email="ordinary-null-origin@example.invalid",
        account_kind=Account.Kind.PERSON,
        is_active=False,
    )
    ordinary.set_unusable_password()
    Account.objects.bulk_create([ordinary])
    ordinary.refresh_from_db()
    assert ordinary.invitation_provisioning_origin_id is None


def test_invitation_origin_rejects_raw_clear_and_rebind() -> None:
    _actor, invitation, _challenge, _delivery = _pending_graph()
    subject = invitation.account
    subject.invitation_provisioning_origin = invitation
    subject.save(update_fields=("invitation_provisioning_origin",))
    _other_actor, other_invitation, _other_challenge, _other_delivery = _pending_graph(
        label="-other"
    )

    with (
        pytest.raises(
            DatabaseError, match="invitation provisioning origin is immutable"
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_account "
            "SET invitation_provisioning_origin_id = NULL WHERE id = %s",
            [subject.id],
        )

    with (
        pytest.raises(
            DatabaseError, match="invitation provisioning origin is immutable"
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_account SET invitation_provisioning_origin_id = %s "
            "WHERE id = %s",
            [other_invitation.id, subject.id],
        )

    subject.refresh_from_db()
    assert subject.invitation_provisioning_origin_id == invitation.id


def test_concurrent_origin_claim_allows_only_exact_reserved_account() -> None:
    _actor, invitation, _challenge, _delivery = _pending_graph()
    forged_account = _reserved_person(label="-forged-claim")
    barrier = Barrier(2)

    def claim(account_id: UUID) -> bool:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                Account.objects.filter(id=account_id).update(
                    invitation_provisioning_origin_id=invitation.id
                )
        except DatabaseError:
            return False
        else:
            return True
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        exact = pool.submit(claim, invitation.account_id)
        forged = pool.submit(claim, forged_account.id)
        outcomes = (exact.result(timeout=20), forged.result(timeout=20))

    assert outcomes == (True, False)
    invitation.account.refresh_from_db()
    forged_account.refresh_from_db()
    assert invitation.account.invitation_provisioning_origin_id == invitation.id
    assert forged_account.invitation_provisioning_origin_id is None
