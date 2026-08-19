from __future__ import annotations

import base64
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

_FROM = ("identity", "0012_invitation_delivery_reconciliation")
_TO = ("identity", "0013_invitation_token_digest_keys")
_HARDENED = ("identity", "0014_invitation_delivery_integrity")


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _encoded(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def test_identity_0014_orders_and_enforces_audit_retry_uniqueness() -> None:
    _migrate(_TO)
    executor = MigrationExecutor(connection)
    plan = executor.loader.graph.forwards_plan(_HARDENED)
    assert plan.index(
        ("audit", "0007_identity_reconciliation_audit_uniqueness")
    ) < plan.index(_HARDENED)

    migrated = _migrate(_HARDENED)
    applied = MigrationRecorder(connection).applied_migrations()
    assert ("audit", "0007_identity_reconciliation_audit_uniqueness") in applied
    audit_event_model = migrated.loader.project_state([_HARDENED]).apps.get_model(
        "audit", "AuditEvent"
    )
    principal_id = uuid4()
    retry_hash = "a" * 64
    occurred_at = timezone.now()
    common = {
        "occurred_at": occurred_at,
        "principal_kind": "account",
        "principal_id": principal_id,
        "capability_code": "identity.reconcile_account_invitation_delivery",
        "operation": "identity.account_invitation.delivery_reconcile",
        "target_type": "identity.platform_identity_delivery",
        "target_id": uuid4(),
        "outcome": "allow",
        "reason_code": "resolve_retry",
        "correlation_id": uuid4(),
        "source_channel": "migration_test",
        "idempotency_key_hash": retry_hash,
    }
    with (
        pytest.raises(
            IntegrityError,
            match="audit_identity_reconcile_retry_unique",
        ),
        transaction.atomic(),
    ):
        audit_event_model.objects.bulk_create(
            [audit_event_model(**common), audit_event_model(**common)]
        )


def test_upgrade_refuses_active_legacy_token_then_allows_terminal_evidence() -> (  # noqa: PLR0915
    None
):
    executor = _migrate(_FROM)
    apps = executor.loader.project_state([_FROM]).apps
    account_model = apps.get_model("identity", "Account")
    invitation_model = apps.get_model("identity", "PlatformAccountInvitation")
    challenge_model = apps.get_model("identity", "IdentityChallenge")
    delivery_model = apps.get_model("identity", "PlatformIdentityDelivery")
    control_model = apps.get_model("identity", "PlatformAccountInventoryControl")
    receipt_model = apps.get_model(
        "identity", "PlatformAccountInvitationCommandReceipt"
    )
    transition_model = apps.get_model("identity", "PlatformAccountInvitationTransition")

    occurred_at = timezone.now()
    actor = account_model.objects.create(
        email="legacy-digest-operator@example.invalid",
        display_name="Synthetic Legacy Digest Operator",
        account_kind="platform_administrator",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        password="!",
    )
    subject = account_model.objects.create(
        email="legacy-digest-subject@example.invalid",
        display_name="Synthetic Legacy Digest Subject",
        account_kind="person",
        is_active=False,
        is_staff=False,
        is_superuser=False,
        password="!",
    )
    control, _created = control_model.objects.get_or_create(
        singleton=True,
        defaults={"aggregate_version": 0},
    )
    with transaction.atomic():
        invitation = invitation_model.objects.create(
            account=subject,
            status="pending",
            aggregate_version=1,
            expires_at=occurred_at + timedelta(days=7),
            last_transition_at=occurred_at,
            created_by=actor,
        )
        challenge = challenge_model.objects.create(
            account=subject,
            purpose="account_invitation",
            token_digest="1" * 64,
            email_snapshot=subject.email,
            expires_at=invitation.expires_at,
            request_fingerprint="2" * 64,
            invitation=invitation,
            invitation_version=1,
            delivery_status="suppressed",
        )
        delivery = delivery_model.objects.create(
            invitation=invitation,
            challenge=challenge,
            status="pending",
            encryption_algorithm="aes-256-gcm+rsa-oaep-sha256-v1",
            encryption_key_id="legacy-envelope-key",
            encrypted_payload=_encoded(b"p" * 17),
            wrapped_data_key=_encoded(b"k" * 256),
            payload_nonce=b"n" * 12,
            payload_aad_digest="3" * 64,
        )
        invitation.current_challenge = challenge
        invitation.save(update_fields=("current_challenge", "updated_at"))
        created_correlation_id = uuid4()
        transition_model.objects.create(
            invitation=invitation,
            version=1,
            operation="created",
            actor=actor,
            occurred_at=occurred_at,
            reason="Create synthetic migration evidence.",
            correlation_id=created_correlation_id,
            source_channel="migration_test",
        )
        receipt_model.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=actor,
            operation="create",
            retry_key=uuid4(),
            request_digest="4" * 64,
            expected_version=0,
            result_version=1,
            correlation_id=created_correlation_id,
            source_channel="migration_test",
        )

    with pytest.raises(RuntimeError, match="active legacy account invitation"):
        _migrate(_TO)

    terminal_at = timezone.now()
    with transaction.atomic():
        challenge = challenge_model.objects.select_for_update().get(id=challenge.id)
        delivery = delivery_model.objects.select_for_update().get(id=delivery.id)
        invitation = invitation_model.objects.select_for_update().get(id=invitation.id)
        challenge.invalidated_at = terminal_at
        challenge.invalidation_reason = "migration_preflight_revoked"
        challenge.save(
            update_fields=("invalidated_at", "invalidation_reason", "updated_at")
        )
        delivery.status = "cancelled"
        delivery.aggregate_version = 2
        delivery.safe_error_code = "invitation_revoked"
        delivery.cancellation_requested_at = terminal_at
        delivery.cancellation_code = "invitation_revoked"
        delivery.cancelled_at = terminal_at
        delivery.encryption_algorithm = ""
        delivery.encryption_key_id = ""
        delivery.encrypted_payload = None
        delivery.wrapped_data_key = None
        delivery.payload_nonce = None
        delivery.payload_aad_digest = ""
        delivery.payload_destroyed_at = terminal_at
        delivery.payload_destruction_reason = "revoked"
        delivery.save()
        invitation.current_challenge = None
        invitation.status = "revoked"
        invitation.aggregate_version = 2
        invitation.last_transition_at = terminal_at
        invitation.revoked_at = terminal_at
        invitation.save(
            update_fields=(
                "current_challenge",
                "status",
                "aggregate_version",
                "last_transition_at",
                "revoked_at",
                "updated_at",
            )
        )
        revoked_correlation_id = uuid4()
        transition_model.objects.create(
            invitation=invitation,
            version=2,
            operation="revoked",
            actor=actor,
            occurred_at=terminal_at,
            reason="Resolve the synthetic migration blocker.",
            correlation_id=revoked_correlation_id,
            source_channel="migration_test",
        )
        receipt_model.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=actor,
            operation="revoke",
            retry_key=uuid4(),
            request_digest="5" * 64,
            expected_version=1,
            result_version=2,
            correlation_id=revoked_correlation_id,
            source_channel="migration_test",
        )

    migrated = _migrate(_TO)
    current_apps = migrated.loader.project_state([_TO]).apps
    current_challenge = current_apps.get_model(
        "identity", "IdentityChallenge"
    ).objects.get(id=challenge.id)
    assert current_challenge.token_digest_key_id == ""
    assert current_challenge.invalidated_at is not None

    current_challenge_model = current_apps.get_model("identity", "IdentityChallenge")
    current_invitation_model = current_apps.get_model(
        "identity", "PlatformAccountInvitation"
    )
    current_account_model = current_apps.get_model("identity", "Account")
    current_challenge_model.objects.create(
        account=current_account_model.objects.get(id=subject.id),
        purpose="account_invitation",
        token_digest="7" * 64,
        token_digest_key_id="migration-digest-key-v1",
        email_snapshot=subject.email,
        expires_at=invitation.expires_at,
        invalidated_at=terminal_at,
        invalidation_reason="historical_keyed_terminal",
        request_fingerprint="6" * 64,
        invitation=current_invitation_model.objects.get(id=invitation.id),
        invitation_version=2,
        delivery_status="suppressed",
    )
    with pytest.raises(RuntimeError, match="cannot be reversed after a keyed"):
        _migrate(_FROM)
