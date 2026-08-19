from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.identity.invitation_commands import (
    create_platform_account_invitation,
    reissue_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_crypto import InvitationPrivateKeyring
from maru.identity.invitation_delivery import deliver_platform_identity_invitation
from maru.identity.invitation_readiness import (
    inspect_platform_invitation_additive_catalog,
    platform_invitation_retention_heartbeat_is_ready,
)
from maru.identity.invitation_retention import (
    InvitationRetentionConfigurationError,
    _append_retention_audit,
    activate_configured_invitation_retention_policy,
    configured_invitation_retention_policy,
    place_invitation_retention_hold,
    release_invitation_retention_hold,
    run_platform_invitation_retention,
)
from maru.identity.models import (
    Account,
    AccountSecurityEvent,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformInvitationRetentionAssessment,
    PlatformInvitationRetentionHold,
    PlatformInvitationRetentionPolicyControl,
    PlatformInvitationRetentionReceipt,
    PlatformInvitationSchedulerRun,
)
from maru.privacyops.models import SubjectRightsRequest
from tests.factories import AccountFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]

_SOURCE_CHANNEL = "retention_test"


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
    settings.MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = (  # type: ignore[attr-defined]
        "retention-envelope-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = base64.b64encode(  # type: ignore[attr-defined]
        public_key_pem
    ).decode("ascii")
    settings.MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (  # type: ignore[attr-defined]
        "retention-digest-2026-08"
    )
    settings.MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = json.dumps(  # type: ignore[attr-defined]
        {"retention-digest-2026-08": base64.b64encode(b"r" * 32).decode("ascii")}
    )
    return InvitationPrivateKeyring(
        {"retention-envelope-2026-08": invitation_private_key}
    )


@pytest.fixture
def platform_actor() -> Account:
    return AccountFactory(
        email="retention.operator@example.invalid",
        display_name="Synthetic Retention Operator",
        is_staff=True,
        is_superuser=True,
    )


def _configure_policy(
    settings: object,
    *,
    version: int = 1,
    period_days: int = 0,
) -> object:
    approved_at = timezone.now() - timedelta(days=2)
    document = {
        "policy_id": "synthetic-abandoned-invitation",
        "version": version,
        "jurisdiction_code": "TEST",
        "trigger": "terminal_transition",
        "period_days": period_days,
        "action": "anonymize_abandoned_invitation_contact",
        "approved_by_reference": "test-review-ticket-42",
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
    }
    settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON = json.dumps(  # type: ignore[attr-defined]
        document
    )
    return configured_invitation_retention_policy()


def _create_invitation(*, actor: Account, email: str) -> PlatformAccountInvitation:
    return create_platform_account_invitation(
        actor=actor,
        email=email,
        login_handle=None,
        display_name="Synthetic Retention Subject",
        preferred_language="en",
        reason="Exercise the approved retention workflow.",
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    ).invitation


def _revoke(*, actor: Account, invitation: PlatformAccountInvitation) -> None:
    revoke_platform_account_invitation(
        actor=actor,
        invitation_id=invitation.id,
        expected_version=invitation.aggregate_version,
        reason="Close this synthetic invitation without acceptance.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
    )
    invitation.refresh_from_db()
    deadline = time.monotonic() + 2
    while True:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.clock_timestamp() >= %s",
                [invitation.last_transition_at],
            )
            caught_up = bool(cursor.fetchone()[0])
        if caught_up:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("PostgreSQL clock did not reach the terminal event")
        time.sleep(0.01)


def _create_revoked(
    *,
    actor: Account,
    email: str,
) -> tuple[PlatformAccountInvitation, IdentityChallenge, PlatformIdentityDelivery]:
    invitation = _create_invitation(actor=actor, email=email)
    challenge = IdentityChallenge.objects.get(invitation=invitation)
    delivery = PlatformIdentityDelivery.objects.get(invitation=invitation)
    _revoke(actor=actor, invitation=invitation)
    challenge.refresh_from_db()
    delivery.refresh_from_db()
    return invitation, challenge, delivery


def _receipt_candidate(
    invitation: PlatformAccountInvitation,
    *,
    applied_at=None,  # type: ignore[no-untyped-def]
) -> PlatformInvitationRetentionReceipt:
    policy = configured_invitation_retention_policy()
    trigger_at = invitation.revoked_at or invitation.expired_at
    assert trigger_at is not None
    return PlatformInvitationRetentionReceipt(
        inventory_control_id=True,
        invitation=invitation,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_digest=policy.digest,
        jurisdiction_code=policy.jurisdiction_code,
        policy_approved_by_reference=policy.approved_by_reference,
        policy_approved_at=policy.approved_at,
        trigger=policy.trigger,
        retention_period_days=policy.period_days,
        terminal_version=invitation.aggregate_version,
        trigger_at=trigger_at,
        due_at=policy.due_at(trigger_at),
        action=policy.action,
        applied_at=applied_at or timezone.now(),
        correlation_id=uuid4(),
        source_channel=_SOURCE_CHANNEL,
        safe_result_code="abandoned_invitation_contact_anonymized",
    )


def _database_relationship_gate(
    invitation: PlatformAccountInvitation,
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.identity_page10_retention_account_is_unrelated(%s, %s)",
            [invitation.account_id, invitation.id],
        )
        row = cursor.fetchone()
    return row is not None and bool(row[0])


def test_policy_configuration_is_closed_and_has_no_default(settings: object) -> None:
    settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON = ""  # type: ignore[attr-defined]
    with pytest.raises(InvitationRetentionConfigurationError):
        configured_invitation_retention_policy()

    settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON = json.dumps(  # type: ignore[attr-defined]
        {"period_days": 30}
    )
    with pytest.raises(InvitationRetentionConfigurationError):
        configured_invitation_retention_policy()

    _configure_policy(settings, period_days=0)
    assert configured_invitation_retention_policy().period_days == 0


def test_policy_control_requires_monotonic_exact_activation(settings: object) -> None:
    first_policy = _configure_policy(settings, version=1, period_days=7)
    first = activate_configured_invitation_retention_policy()
    replay = activate_configured_invitation_retention_policy()
    assert replay.pk == first.pk
    assert replay.policy_digest == first_policy.digest

    _configure_policy(settings, version=1, period_days=8)
    with pytest.raises(InvitationRetentionConfigurationError):
        activate_configured_invitation_retention_policy()

    second_policy = _configure_policy(settings, version=2, period_days=8)
    second = activate_configured_invitation_retention_policy()
    assert second.policy_version == 2
    assert second.policy_digest == second_policy.digest


def test_due_disposal_anonymizes_contact_and_keeps_governance_evidence(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    policy = _configure_policy(settings)
    invitation, challenge, delivery = _create_revoked(
        actor=platform_actor,
        email="retention.subject@example.invalid",
    )
    account = invitation.account
    original_email = account.email
    original_digest = challenge.token_digest
    original_fingerprint = challenge.request_fingerprint
    transition_count = invitation.transitions.count()
    audit_count = AuditEvent.objects.filter(target_id=invitation.id).count()
    security_count = account.security_events.count()
    activate_configured_invitation_retention_policy()

    result = run_platform_invitation_retention(limit=1)

    account.refresh_from_db()
    challenge.refresh_from_db()
    delivery.refresh_from_db()
    receipt = PlatformInvitationRetentionReceipt.objects.get(invitation=invitation)
    assert result.disposed_count == 1
    assert result.blocked_count == 0
    assert re.fullmatch(
        r"disposed-[0-9a-f]{32}@account[.]invalid",
        account.email,
    )
    assert original_email not in account.email
    assert str(account.id) not in account.email
    assert str(invitation.id) not in account.email
    assert account.login_handle == ""
    assert account.display_name == ""
    assert account.invitation_provisioning_origin_id == invitation.id
    assert challenge.email_snapshot == account.email
    assert challenge.token_digest != original_digest
    assert challenge.request_fingerprint != original_fingerprint
    assert challenge.token_digest_key_id == ""
    assert delivery.encrypted_payload is None
    assert delivery.wrapped_data_key is None
    assert delivery.payload_nonce is None
    assert receipt.policy_id == policy.policy_id
    assert receipt.policy_version == policy.version
    assert receipt.policy_digest == policy.digest
    assert receipt.terminal_version == invitation.aggregate_version
    assert invitation.transitions.count() == transition_count
    assert account.security_events.count() == security_count
    assert AuditEvent.objects.filter(target_id=invitation.id).count() == audit_count + 1
    heartbeat = PlatformInvitationSchedulerRun.objects.get(id=result.heartbeat_id)
    assert heartbeat.policy_digest == policy.digest
    assert platform_invitation_retention_heartbeat_is_ready()

    replay = run_platform_invitation_retention(limit=1)
    assert replay.disposed_count == 0
    assert (
        PlatformInvitationRetentionReceipt.objects.filter(invitation=invitation).count()
        == 1
    )


def test_active_hold_blocks_then_audited_release_allows_disposal(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.held@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    hold = place_invitation_retention_hold(
        actor=platform_actor,
        invitation_id=invitation.id,
        reference_code="legal-case-42",
        reason_code="security-review-open",
        correlation_id=uuid4(),
    )
    assert not PlatformInvitationRetentionReceipt.objects.filter(
        invitation=invitation
    ).exists()
    blocked = run_platform_invitation_retention(limit=1)
    assert blocked.disposed_count == 0
    assert blocked.held_count == 1
    assert blocked.blocked_count == 0
    assert blocked.remaining_count == 0
    held_assessment = PlatformInvitationRetentionAssessment.objects.get(
        invitation=invitation
    )
    assert held_assessment.safe_result_code == "active_hold"
    held_heartbeat = PlatformInvitationSchedulerRun.objects.get(id=blocked.heartbeat_id)
    assert held_heartbeat.retention_cursor_invitation_id == invitation.id

    release_invitation_retention_hold(
        actor=platform_actor,
        hold_id=hold.id,
        reason_code="security-review-closed",
        correlation_id=uuid4(),
    )
    disposed = run_platform_invitation_retention(limit=1)
    assert disposed.disposed_count == 1
    assert (
        AuditEvent.objects.filter(
            target_type="identity.platform_invitation_retention_hold",
            target_id=hold.id,
        ).count()
        == 2
    )


@pytest.mark.parametrize("relationship", ["privacy_request", "group", "security_event"])
def test_account_relationships_block_service_and_database_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
    relationship: str,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email=f"retention.{relationship}@example.invalid",
    )
    account = invitation.account
    activate_configured_invitation_retention_policy()
    if relationship == "privacy_request":
        SubjectRightsRequest.objects.create(
            account=account,
            kind=SubjectRightsRequest.Kind.ACCESS,
            requested_at=timezone.now(),
            request_summary="Synthetic access request blocks disposal.",
        )
    elif relationship == "group":
        account.groups.add(Group.objects.create(name="Synthetic retention group"))
    else:
        AccountSecurityEvent.objects.create(
            account=account,
            event_type=AccountSecurityEvent.EventType.SIGN_IN,
            outcome=AccountSecurityEvent.Outcome.SUCCEEDED,
            occurred_at=timezone.now(),
            source_channel=_SOURCE_CHANNEL,
            detail_code="synthetic_non_invitation_event",
        )

    assert not _database_relationship_gate(invitation)
    result = run_platform_invitation_retention(limit=1)
    assert result.disposed_count == 0
    assert result.blocked_count == 1
    with (
        pytest.raises(DatabaseError, match="retention dependencies are not closed"),
        transaction.atomic(),
    ):
        PlatformInvitationRetentionReceipt.objects.bulk_create(
            [_receipt_candidate(invitation)]
        )


def test_catalog_relationship_gate_blocks_future_foreign_key_relation(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.future-relation@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE public.identity_synthetic_future_relation ("
            "id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES "
            "public.identity_account(id))"
        )
        cursor.execute(
            "INSERT INTO public.identity_synthetic_future_relation (id, account_id) "
            "VALUES (%s, %s)",
            [uuid4(), invitation.account_id],
        )
    try:
        assert not _database_relationship_gate(invitation)
        with (
            pytest.raises(
                DatabaseError,
                match="retention dependencies are not closed",
            ),
            transaction.atomic(),
        ):
            PlatformInvitationRetentionReceipt.objects.bulk_create(
                [_receipt_candidate(invitation)]
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE public.identity_synthetic_future_relation")


def test_multiple_invitations_for_one_reserved_account_fail_closed(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.multiple@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    occurred_at = timezone.now()
    with (
        pytest.raises(DatabaseError, match="identity_one_invitation_per_account"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO public.identity_platformaccountinvitation ("
            "id, created_at, updated_at, account_id, status, aggregate_version, "
            "expires_at, last_transition_at, accepted_at, revoked_at, expired_at, "
            "current_challenge_id, created_by_id) VALUES ("
            "%s, %s, %s, %s, 'pending', 1, %s, %s, NULL, NULL, NULL, NULL, %s)",
            [
                uuid4(),
                occurred_at,
                occurred_at,
                invitation.account_id,
                occurred_at + timedelta(days=7),
                occurred_at,
                platform_actor.id,
            ],
        )

    assert _database_relationship_gate(invitation)
    result = run_platform_invitation_retention(limit=10)
    assert result.disposed_count == 1
    assert result.blocked_count == 0
    assert PlatformInvitationRetentionReceipt.objects.filter(
        invitation=invitation
    ).exists()


def test_retention_batch_is_bounded_and_reports_remaining_work(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    first, _first_challenge, _first_delivery = _create_revoked(
        actor=platform_actor,
        email="retention.batch-one@example.invalid",
    )
    second, _second_challenge, _second_delivery = _create_revoked(
        actor=platform_actor,
        email="retention.batch-two@example.invalid",
    )
    activate_configured_invitation_retention_policy()

    result = run_platform_invitation_retention(limit=1)

    assert result.disposed_count == 1
    assert result.remaining_count == 1
    assert (
        PlatformInvitationRetentionReceipt.objects.filter(
            invitation_id__in=(first.id, second.id)
        ).count()
        == 1
    )


def test_raw_future_policy_and_receipt_evidence_are_rejected(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    policy = _configure_policy(settings)
    future = timezone.now() + timedelta(days=1)
    with (
        pytest.raises(DatabaseError, match="activation time is in the future"),
        transaction.atomic(),
    ):
        PlatformInvitationRetentionPolicyControl.objects.bulk_create(
            [
                PlatformInvitationRetentionPolicyControl(
                    singleton=True,
                    generation="retention-policy-v1",
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    policy_digest=policy.digest,
                    jurisdiction_code=policy.jurisdiction_code,
                    policy_approved_by_reference=policy.approved_by_reference,
                    policy_approved_at=policy.approved_at,
                    trigger=policy.trigger,
                    retention_period_days=policy.period_days,
                    action=policy.action,
                    activated_at=future,
                )
            ]
        )

    activate_configured_invitation_retention_policy()
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.future-receipt@example.invalid",
    )
    with (
        pytest.raises(
            DatabaseError,
            match="invitation retention receipt predates application",
        ),
        transaction.atomic(),
    ):
        PlatformInvitationRetentionReceipt.objects.bulk_create(
            [_receipt_candidate(invitation, applied_at=future)]
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        run_platform_invitation_retention(at=future)


def test_challenge_digest_key_cannot_be_blank_without_retention_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.challenge-guard@example.invalid",
    )
    with (
        pytest.raises(
            DatabaseError,
            match=r"challenge .*lineage is immutable",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE public.identity_identitychallenge "
            "SET token_digest_key_id = '' WHERE id = %s",
            [challenge.id],
        )
    assert not PlatformInvitationRetentionReceipt.objects.filter(
        invitation=invitation
    ).exists()


def test_audit_failure_rolls_back_contact_and_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.audit-rollback@example.invalid",
    )
    account = invitation.account
    original_email = account.email
    activate_configured_invitation_retention_policy()

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(
        "maru.identity.invitation_retention.append_audit",
        fail_audit,
    )
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        run_platform_invitation_retention(limit=1)

    account.refresh_from_db()
    assert account.email == original_email
    assert not PlatformInvitationRetentionReceipt.objects.filter(
        invitation=invitation
    ).exists()
    assert not PlatformInvitationSchedulerRun.objects.filter(kind="retention").exists()


def _retention_worker() -> tuple[int, int]:
    close_old_connections()
    try:
        result = run_platform_invitation_retention(limit=1)
        return result.disposed_count, result.blocked_count
    finally:
        connections.close_all()


def test_concurrent_workers_create_one_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.concurrent@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _value: _retention_worker(), range(2)))

    assert sum(disposed for disposed, _blocked in outcomes) == 1
    assert (
        PlatformInvitationRetentionReceipt.objects.filter(invitation=invitation).count()
        == 1
    )
    assert PlatformInvitationSchedulerRun.objects.filter(kind="retention").count() == 2


def test_concurrent_cursor_workers_make_progress_on_distinct_candidates(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    first, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.concurrent-cursor-one@example.invalid",
    )
    second, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.concurrent-cursor-two@example.invalid",
    )
    activate_configured_invitation_retention_policy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _value: _retention_worker(), range(2)))

    assert sum(disposed for disposed, _blocked in outcomes) == 2
    assert (
        PlatformInvitationRetentionReceipt.objects.filter(
            invitation_id__in=(first.id, second.id)
        ).count()
        == 2
    )
    heartbeats = PlatformInvitationSchedulerRun.objects.filter(kind="retention")
    assert heartbeats.count() == 2
    assert not heartbeats.filter(retention_cursor_invitation_id__isnull=True).exists()


def _add_synthetic_resolved_late_outcome(
    delivery: PlatformIdentityDelivery,
    *,
    raw_reference: str,
) -> UUID:
    attempt = PlatformIdentityDeliveryAttempt.objects.get(delivery=delivery)
    late_id = uuid4()
    observed_at = max(_database_now_for_test(), attempt.finished_at)
    with connection.cursor() as cursor:
        for relation in (
            "identity_platformidentitydelivery",
            "identity_platformidentitydeliveryattempt",
            "identity_platformidentitydeliverylateoutcome",
        ):
            cursor.execute(f"ALTER TABLE {relation} DISABLE TRIGGER USER")
        try:
            cursor.execute(
                "UPDATE identity_platformidentitydeliveryattempt "
                "SET outcome = 'lease_lost', safe_error_code = 'lease_lost' "
                "WHERE id = %s",
                [attempt.id],
            )
            cursor.execute(
                "UPDATE identity_platformidentitydelivery "
                "SET reconciliation_state = 'resolved', "
                "reconciliation_required_at = %s, reconciled_at = %s, "
                "reconciliation_code = 'synthetic_late_resolution' "
                "WHERE id = %s",
                [attempt.finished_at, observed_at, delivery.id],
            )
            cursor.execute(
                """
                INSERT INTO identity_platformidentitydeliverylateoutcome (
                    id, created_at, updated_at, delivery_id, attempt_number,
                    lease_token, observed_at, outcome, classification,
                    provider_reference, safe_error_code
                ) VALUES (
                    %s, clock_timestamp(), clock_timestamp(), %s, 1, %s,
                    %s, 'delivered', 'terminal_state', %s, ''
                )
                """,
                [
                    late_id,
                    delivery.id,
                    attempt.lease_token,
                    observed_at,
                    raw_reference,
                ],
            )
        finally:
            for relation in reversed(
                (
                    "identity_platformidentitydelivery",
                    "identity_platformidentitydeliveryattempt",
                    "identity_platformidentitydeliverylateoutcome",
                )
            ):
                cursor.execute(f"ALTER TABLE {relation} ENABLE TRIGGER USER")
    return late_id


def test_provider_references_are_one_way_tombstoned_across_delivery_evidence(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: InvitationPrivateKeyring,
) -> None:
    _configure_policy(settings)
    invitation = _create_invitation(
        actor=platform_actor,
        email="retention.provider-reference@example.invalid",
    )
    delivery = PlatformIdentityDelivery.objects.get(invitation=invitation)
    raw_reference = "provider-secret-reference"
    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=lambda _message: raw_reference,
        )
        == PlatformIdentityDelivery.Status.DELIVERED
    )
    late_id = _add_synthetic_resolved_late_outcome(
        delivery,
        raw_reference=raw_reference,
    )
    _revoke(actor=platform_actor, invitation=invitation)
    activate_configured_invitation_retention_policy()

    result = run_platform_invitation_retention(limit=1)

    delivery.refresh_from_db()
    attempt = PlatformIdentityDeliveryAttempt.objects.get(delivery=delivery)
    assert result.disposed_count == 1
    assert delivery.provider_reference != raw_reference
    assert re.fullmatch(
        r"disposed-provider-[0-9a-f]{32}",
        delivery.provider_reference,
    )
    assert attempt.provider_reference == delivery.provider_reference
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT provider_reference FROM "
            "identity_platformidentitydeliverylateoutcome WHERE id = %s",
            [late_id],
        )
        assert str(cursor.fetchone()[0]) == delivery.provider_reference
    with pytest.raises(DatabaseError, match="provider child reference disposition"):
        _execute_with_test_reset_disabled(
            "UPDATE identity_platformidentitydeliveryattempt "
            "SET provider_reference = %s WHERE id = %s",
            [raw_reference, attempt.id],
        )


def test_more_than_thirty_two_reissues_are_disposed_in_bounded_chunks(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation = _create_invitation(
        actor=platform_actor,
        email="retention.long-history@example.invalid",
    )
    for _index in range(33):
        invitation = reissue_platform_account_invitation(
            actor=platform_actor,
            invitation_id=invitation.id,
            expected_version=invitation.aggregate_version,
            reason="Exercise bounded retention history.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel=_SOURCE_CHANNEL,
        ).invitation
    _revoke(actor=platform_actor, invitation=invitation)
    activate_configured_invitation_retention_policy()

    result = run_platform_invitation_retention(limit=1)

    challenges = IdentityChallenge.objects.filter(invitation=invitation)
    assert result.disposed_count == 1
    assert challenges.count() == 34
    assert not challenges.exclude(token_digest_key_id="").exists()
    assert not challenges.exclude(
        email_snapshot=invitation.account.email,
    ).exists()


def test_fair_cursor_advances_past_blocked_oldest_candidate(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    blocked, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.cursor-blocked@example.invalid",
    )
    blocked.account.groups.add(Group.objects.create(name="synthetic-retention-block"))
    eligible, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.cursor-eligible@example.invalid",
    )
    activate_configured_invitation_retention_policy()

    first = run_platform_invitation_retention(limit=1)
    second = run_platform_invitation_retention(limit=1)
    third = run_platform_invitation_retention(limit=1)

    assert (first.blocked_count, first.disposed_count) == (1, 0)
    assert (second.blocked_count, second.disposed_count) == (0, 1)
    assert PlatformInvitationRetentionReceipt.objects.filter(
        invitation=eligible
    ).exists()
    assert not PlatformInvitationRetentionReceipt.objects.filter(
        invitation=blocked
    ).exists()
    assessment = PlatformInvitationRetentionAssessment.objects.get(invitation=blocked)
    assert third.blocked_count == 1
    assert assessment.safe_result_code == "account_relationship"
    assert assessment.assessment_version == 2


def test_source_allowlist_and_duplicate_policy_members_fail_without_evidence(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.source-allowlist@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    audit_before = AuditEvent.objects.count()

    with pytest.raises(ValidationError, match="approved retention source"):
        place_invitation_retention_hold(
            actor=platform_actor,
            invitation_id=invitation.id,
            reference_code="source-check",
            reason_code="source-check",
            correlation_id=uuid4(),
            source_channel="web",
        )
    with pytest.raises(ValidationError, match="approved retention source"):
        run_platform_invitation_retention(source_channel="management-command")

    assert PlatformInvitationRetentionHold.objects.count() == 0
    assert PlatformInvitationSchedulerRun.objects.filter(kind="retention").count() == 0
    assert AuditEvent.objects.count() == audit_before
    settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON = (  # type: ignore[attr-defined]
        '{"policy_id":"synthetic","version":1,"version":2}'
    )
    with pytest.raises(InvitationRetentionConfigurationError):
        configured_invitation_retention_policy()


def _execute_with_test_reset_disabled(
    statement: str,
    parameters: list[object] | None = None,
) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(statement, parameters or [])


def _database_now_for_test():  # type: ignore[no-untyped-def]
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.clock_timestamp()")
        return cursor.fetchone()[0]


def test_database_clock_rejects_plus_250ms_and_naive_policy_evidence(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    policy = _configure_policy(settings)
    database_now = _database_now_for_test()
    future = database_now + timedelta(milliseconds=250)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        activate_configured_invitation_retention_policy(
            activated_at=timezone.now().replace(tzinfo=None),
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        activate_configured_invitation_retention_policy(activated_at=future)
    with (
        pytest.raises(DatabaseError, match="policy activation time is in the future"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO identity_platforminvitationretentionpolicycontrol (
                singleton, generation, policy_id, policy_version, policy_digest,
                jurisdiction_code, policy_approved_by_reference,
                policy_approved_at, trigger, retention_period_days, action,
                activated_at
            ) VALUES (
                true, 'retention-policy-v1', %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            [
                policy.policy_id,
                policy.version,
                policy.digest,
                policy.jurisdiction_code,
                policy.approved_by_reference,
                future,
                policy.trigger,
                policy.period_days,
                policy.action,
                database_now,
            ],
        )

    with (
        pytest.raises(DatabaseError, match="scheduler heartbeat time or cursor"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() + interval '250 milliseconds' AS at
            )
            INSERT INTO identity_platforminvitationschedulerrun (
                id, created_at, updated_at, kind, generation, ran_at,
                processed_count, remaining_count,
                private_key_coverage_complete, policy_digest,
                inspected_count, blocked_count, held_count,
                retention_cursor_transition_at,
                retention_cursor_invitation_id
            )
            SELECT %s, at, at, 'retention', 'retention-v2', at,
                   0, 0, false, %s, 0, 0, 0, NULL, NULL
              FROM evidence
            """,
            [uuid4(), policy.digest],
        )

    with (
        pytest.raises(DatabaseError, match="scheduler heartbeat time or cursor"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() AS at
            )
            INSERT INTO identity_platforminvitationschedulerrun (
                id, created_at, updated_at, kind, generation, ran_at,
                processed_count, remaining_count,
                private_key_coverage_complete, policy_digest,
                inspected_count, blocked_count, held_count,
                retention_cursor_transition_at,
                retention_cursor_invitation_id
            )
            SELECT %s, at, at, 'retention', 'retention-v2', at,
                   0, 0, false, %s, 1, 0, 1,
                   at - interval '1 second', %s
              FROM evidence
            """,
            [uuid4(), policy.digest, uuid4()],
        )


def test_database_clock_rejects_plus_250ms_hold_and_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    policy = _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.strict-clock@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    database_now = _database_now_for_test()
    future = database_now + timedelta(milliseconds=250)
    with (
        pytest.raises(DatabaseError, match="retention hold time is in the future"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO identity_platforminvitationretentionhold (
                id, created_at, updated_at, invitation_id, reference_code,
                reason_code, placed_at, placed_by_id, place_correlation_id,
                active, released_at, released_by_id, release_reason_code,
                release_correlation_id
            ) VALUES (
                %s, %s, %s, %s, 'future-hold', 'future-hold', %s, %s, %s,
                true, NULL, NULL, '', NULL
            )
            """,
            [
                uuid4(),
                future,
                future,
                invitation.id,
                database_now,
                platform_actor.id,
                uuid4(),
            ],
        )
    trigger_at = invitation.revoked_at
    assert trigger_at is not None
    with (
        pytest.raises(
            DatabaseError,
            match="retention receipt time or source is invalid",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO identity_platforminvitationretentionreceipt (
                id, created_at, updated_at, inventory_control_id, invitation_id,
                policy_id, policy_version, policy_digest, jurisdiction_code,
                policy_approved_by_reference, policy_approved_at, trigger,
                retention_period_days, terminal_version, trigger_at, due_at,
                action, applied_at, correlation_id, source_channel,
                safe_result_code
            ) VALUES (
                %s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, 'scheduler',
                'abandoned_invitation_contact_anonymized'
            )
            """,
            [
                uuid4(),
                future,
                future,
                invitation.id,
                policy.policy_id,
                policy.version,
                policy.digest,
                policy.jurisdiction_code,
                policy.approved_by_reference,
                policy.approved_at,
                policy.trigger,
                policy.period_days,
                invitation.aggregate_version,
                trigger_at,
                policy.due_at(trigger_at),
                policy.action,
                database_now,
                uuid4(),
            ],
        )


def test_disposed_assessment_requires_matching_receipt(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    policy = _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.assessment-binding@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    with (
        pytest.raises(DatabaseError, match="retention assessment evidence is invalid"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() AS at
            )
            INSERT INTO identity_platforminvitationretentionassessment (
                id, created_at, updated_at, invitation_id, policy_digest,
                terminal_version, assessment_version, safe_result_code,
                assessed_at
            )
            SELECT %s, at, at, %s, %s, %s, 1, 'disposed', at FROM evidence
            """,
            [
                uuid4(),
                invitation.id,
                policy.digest,
                invitation.aggregate_version,
            ],
        )

    with (
        pytest.raises(DatabaseError, match="retention assessment must begin"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() AS at
            )
            INSERT INTO identity_platforminvitationretentionassessment (
                id, created_at, updated_at, invitation_id, policy_digest,
                terminal_version, assessment_version, safe_result_code,
                assessed_at
            )
            SELECT %s, at - interval '2 seconds', at - interval '1 second',
                   %s, %s, %s, 1, 'not_due', at - interval '1500 milliseconds'
              FROM evidence
            """,
            [
                uuid4(),
                invitation.id,
                policy.digest,
                invitation.aggregate_version,
            ],
        )


def test_non_disposed_assessment_requires_current_policy_after_advance(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    historical_policy = _configure_policy(settings, version=1)
    activate_configured_invitation_retention_policy()
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.assessment-current-policy@example.invalid",
    )
    current_policy = _configure_policy(settings, version=2)
    activate_configured_invitation_retention_policy()

    statement = """
        WITH evidence AS MATERIALIZED (
            SELECT clock_timestamp() AS at
        )
        INSERT INTO identity_platforminvitationretentionassessment (
            id, created_at, updated_at, invitation_id, policy_digest,
            terminal_version, assessment_version, safe_result_code,
            assessed_at
        )
        SELECT %s, at, at, %s, %s, %s, 1, 'not_due', at FROM evidence
    """
    with (
        pytest.raises(DatabaseError, match="retention assessment evidence is invalid"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            statement,
            [
                uuid4(),
                invitation.id,
                historical_policy.digest,
                invitation.aggregate_version,
            ],
        )

    assessment_id = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            statement,
            [
                assessment_id,
                invitation.id,
                current_policy.digest,
                invitation.aggregate_version,
            ],
        )
    assessment = PlatformInvitationRetentionAssessment.objects.get(id=assessment_id)
    assert assessment.safe_result_code == "not_due"
    assert assessment.policy_digest == current_policy.digest


def test_post_receipt_account_challenge_and_membership_are_immutable(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, challenge, delivery = _create_revoked(
        actor=platform_actor,
        email="retention.permanent-tombstone@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    assert run_platform_invitation_retention(limit=1).disposed_count == 1

    mutations = (
        (
            "UPDATE identity_account SET display_name = 'forged' WHERE id = %s",
            [invitation.account_id],
            "tombstone is immutable",
        ),
        (
            "UPDATE identity_identitychallenge SET email_snapshot = "
            "'forged@example.invalid' WHERE id = %s",
            [challenge.id],
            "immutable",
        ),
    )
    for statement, parameters, message in mutations:
        with (
            pytest.raises(DatabaseError, match=message),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement, parameters)
    group = Group.objects.create(name="forged-disposed-authority")
    with (
        pytest.raises(DatabaseError, match="cannot receive authority"),
        transaction.atomic(),
    ):
        invitation.account.groups.add(group)

    assessment = PlatformInvitationRetentionAssessment.objects.get(
        invitation=invitation
    )
    with (
        pytest.raises(DatabaseError, match="terminal and immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platforminvitationretentionassessment "
            "SET assessment_version = assessment_version + 1, "
            "assessed_at = clock_timestamp(), updated_at = clock_timestamp() "
            "WHERE id = %s",
            [assessment.id],
        )
    with (
        pytest.raises(DatabaseError, match="delivery evidence is immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platformidentitydelivery "
            "SET aggregate_version = aggregate_version + 1, "
            "updated_at = clock_timestamp() WHERE id = %s",
            [delivery.id],
        )


def test_retention_management_command_converts_invalid_limit_to_command_error() -> None:
    with pytest.raises(CommandError, match="retention batch"):
        call_command("run_platform_invitation_retention", limit=0)


def test_raw_retention_evidence_mutation_and_truncation_are_denied(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    held_invitation, _held_challenge, _held_delivery = _create_revoked(
        actor=platform_actor,
        email="retention.raw-held@example.invalid",
    )
    disposed_invitation, _disposed_challenge, _disposed_delivery = _create_revoked(
        actor=platform_actor,
        email="retention.raw-receipt@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    hold = place_invitation_retention_hold(
        actor=platform_actor,
        invitation_id=held_invitation.id,
        reference_code="raw-guard-case",
        reason_code="raw-guard-review",
        correlation_id=uuid4(),
    )
    result = run_platform_invitation_retention(limit=2)
    assert result.disposed_count == 1
    receipt = PlatformInvitationRetentionReceipt.objects.get(
        invitation=disposed_invitation
    )

    mutations = (
        (
            "UPDATE public.identity_platforminvitationretentionpolicycontrol "
            "SET policy_version = policy_version WHERE singleton = true",
            [],
            "policy progression is invalid",
        ),
        (
            "DELETE FROM public.identity_platforminvitationretentionpolicycontrol "
            "WHERE singleton = true",
            [],
            "policy control is protected",
        ),
        (
            "TRUNCATE public.identity_platforminvitationretentionpolicycontrol",
            [],
            "policy control is protected",
        ),
        (
            "UPDATE public.identity_platforminvitationretentionhold "
            "SET reference_code = 'forged' WHERE id = %s",
            [hold.id],
            "retention hold",
        ),
        (
            "DELETE FROM public.identity_platforminvitationretentionhold WHERE id = %s",
            [hold.id],
            "holds are protected",
        ),
        (
            "TRUNCATE public.identity_platforminvitationretentionhold",
            [],
            "append-only",
        ),
        (
            "UPDATE public.identity_platforminvitationretentionreceipt "
            "SET safe_result_code = 'forged' WHERE id = %s",
            [receipt.id],
            "append-only",
        ),
        (
            "DELETE FROM public.identity_platforminvitationretentionreceipt "
            "WHERE id = %s",
            [receipt.id],
            "append-only",
        ),
        (
            "TRUNCATE public.identity_platforminvitationretentionreceipt",
            [],
            "append-only",
        ),
    )
    for statement, parameters, message in mutations:
        with pytest.raises(DatabaseError, match=message):
            _execute_with_test_reset_disabled(statement, parameters)

    assert PlatformInvitationRetentionPolicyControl.objects.count() == 1
    assert PlatformInvitationRetentionReceipt.objects.filter(id=receipt.id).exists()
    assert hold.active


def test_normal_test_database_flush_can_reset_retention_evidence(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    invitation, _challenge, _delivery = _create_revoked(
        actor=platform_actor,
        email="retention.flush@example.invalid",
    )
    activate_configured_invitation_retention_policy()
    place_invitation_retention_hold(
        actor=platform_actor,
        invitation_id=invitation.id,
        reference_code="flush-proof",
        reason_code="flush-proof",
        correlation_id=uuid4(),
    )

    call_command("flush", verbosity=0, interactive=False)

    assert Account.objects.count() == 0
    assert PlatformInvitationRetentionPolicyControl.objects.count() == 0
    assert PlatformInvitationRetentionReceipt.objects.count() == 0
    migration = import_module(
        "maru.identity.migrations.0017_invitation_retention_workflow"
    )
    migration.refuse_invitation_provenance_downgrade(
        None,
        SimpleNamespace(connection=connection),
    )


def test_live_invitation_provenance_refuses_retention_schema_reversal(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: None,
) -> None:
    _configure_policy(settings)
    _create_revoked(
        actor=platform_actor,
        email="retention.rollback-fence@example.invalid",
    )
    migration = import_module(
        "maru.identity.migrations.0017_invitation_retention_workflow"
    )

    with pytest.raises(RuntimeError, match="Refusing to discard invitation"):
        migration.refuse_invitation_provenance_downgrade(
            None,
            SimpleNamespace(connection=connection),
        )


def _identity_migration_targets(
    executor: MigrationExecutor,
    target: tuple[str, str],
) -> list[tuple[str, str]]:
    return [
        target if leaf[0] == "identity" else leaf
        for leaf in executor.loader.graph.leaf_nodes()
    ]


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_empty_v8_reverses_reapplies_and_restores_exact_catalog() -> None:
    before = ("identity", "0017_invitation_retention_workflow")
    after = ("identity", "0018_invitation_retention_v8")
    executor = MigrationExecutor(connection)

    executor.migrate(_identity_migration_targets(executor, before))
    reapplied = MigrationExecutor(connection)
    reapplied.migrate(_identity_migration_targets(reapplied, after))

    catalog = inspect_platform_invitation_additive_catalog()
    assert catalog.additive_contract_ready
    assert catalog.uncataloged_function_identities == ()
    assert catalog.uncataloged_trigger_names == ()


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_populated_v7_v1_receipt_after_v2_activation_upgrades_to_v8(
    settings: object,
    platform_actor: Account,
    configured_invitation_crypto: InvitationPrivateKeyring,
) -> None:
    before = ("identity", "0017_invitation_retention_workflow")
    after = ("identity", "0018_invitation_retention_v8")
    executor = MigrationExecutor(connection)
    executor.migrate(_identity_migration_targets(executor, before))

    receipt_policy = _configure_policy(settings, version=1)
    invitation = _create_invitation(
        actor=platform_actor,
        email="retention.v7-provider-upgrade@example.invalid",
    )
    delivery = PlatformIdentityDelivery.objects.get(invitation=invitation)
    raw_reference = "disposed-provider-11111111111111111111111111111111"
    assert (
        deliver_platform_identity_invitation(
            delivery.id,
            private_keyring=configured_invitation_crypto,
            adapter=lambda _message: raw_reference,
        )
        == PlatformIdentityDelivery.Status.DELIVERED
    )
    late_id = _add_synthetic_resolved_late_outcome(
        delivery,
        raw_reference=raw_reference,
    )
    _revoke(actor=platform_actor, invitation=invitation)
    activate_configured_invitation_retention_policy()
    applied_at = min(_database_now_for_test(), timezone.now())
    correlation_id = uuid4()
    trigger_at = invitation.revoked_at
    assert trigger_at is not None
    with transaction.atomic():
        PlatformInvitationRetentionReceipt.objects.create(
            inventory_control_id=True,
            invitation=invitation,
            policy_id=receipt_policy.policy_id,
            policy_version=receipt_policy.version,
            policy_digest=receipt_policy.digest,
            jurisdiction_code=receipt_policy.jurisdiction_code,
            policy_approved_by_reference=receipt_policy.approved_by_reference,
            policy_approved_at=receipt_policy.approved_at,
            trigger=receipt_policy.trigger,
            retention_period_days=receipt_policy.period_days,
            terminal_version=invitation.aggregate_version,
            trigger_at=trigger_at,
            due_at=receipt_policy.due_at(trigger_at),
            action=receipt_policy.action,
            applied_at=applied_at,
            correlation_id=correlation_id,
            source_channel="scheduler",
            safe_result_code="abandoned_invitation_contact_anonymized",
        )
        tombstone_email = f"disposed-{uuid4().hex}@account.invalid"
        Account.objects.filter(id=invitation.account_id).update(
            email=tombstone_email,
            login_handle="",
            display_name="",
        )
        IdentityChallenge.objects.filter(invitation=invitation).update(
            email_snapshot=tombstone_email,
            token_digest="a" * 64,
            token_digest_key_id="",
            request_fingerprint="b" * 64,
            updated_at=applied_at,
        )
        _append_retention_audit(
            actor=None,
            operation="identity.account_invitation.retention_apply",
            target_type="identity.platform_account_invitation",
            target_id=invitation.id,
            correlation_id=correlation_id,
            source_channel="scheduler",
            changed_fields=("account_contact", "challenge_contact"),
            policy=receipt_policy,
            occurred_at=applied_at,
        )

    active_policy = _configure_policy(settings, version=2)
    active_control = activate_configured_invitation_retention_policy()
    assert active_control.policy_version == 2
    assert active_control.policy_digest == active_policy.digest
    assert active_control.policy_digest != receipt_policy.digest

    upgraded = MigrationExecutor(connection)
    upgraded.migrate(_identity_migration_targets(upgraded, after))
    delivery.refresh_from_db()
    attempt = PlatformIdentityDeliveryAttempt.objects.get(delivery=delivery)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT provider_reference FROM "
            "identity_platformidentitydeliverylateoutcome WHERE id = %s",
            [late_id],
        )
        late_reference = str(cursor.fetchone()[0])
    assessment = PlatformInvitationRetentionAssessment.objects.get(
        invitation=invitation
    )
    assert re.fullmatch(
        r"disposed-provider-[0-9a-f]{32}",
        delivery.provider_reference,
    )
    assert delivery.provider_reference != raw_reference
    assert attempt.provider_reference == delivery.provider_reference == late_reference
    assert assessment.safe_result_code == "disposed"
    assert assessment.policy_digest == receipt_policy.digest
    assert assessment.policy_digest != active_control.policy_digest
    assert assessment.created_at == assessment.updated_at == assessment.assessed_at

    reversed_executor = MigrationExecutor(connection)
    with pytest.raises(RuntimeError, match="Cannot remove retention v8"):
        reversed_executor.migrate(
            _identity_migration_targets(reversed_executor, before)
        )
