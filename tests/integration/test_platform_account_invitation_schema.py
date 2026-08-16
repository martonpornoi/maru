from __future__ import annotations

import base64
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from maru.identity.models import (
    Account,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _encoded(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _platform_administrator(*, email: str = "schema-admin@example.invalid") -> Account:
    return Account.objects.create_superuser(
        email=email,
        password="Synthetic-operator-password-1!",
    )


def _reserved_person(*, email: str = "schema-person@example.invalid") -> Account:
    account = Account(
        email=email,
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


def _inventory_control() -> PlatformAccountInventoryControl:
    control, _created = PlatformAccountInventoryControl.objects.get_or_create(
        singleton=True,
        defaults={"aggregate_version": 0},
    )
    return control


def _create_pending_graph(
    *,
    actor: Account,
    subject: Account,
) -> tuple[
    PlatformAccountInvitation,
    IdentityChallenge,
    PlatformIdentityDelivery,
]:
    occurred_at = timezone.now()
    control = _inventory_control()
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
            token_digest="1" * 64,
            token_digest_key_id="schema-digest-key-v1",
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
            encryption_key_id="schema-key-v1",
            encrypted_payload=_encoded(b"p" * 17),
            wrapped_data_key=_encoded(b"k" * 256),
            payload_nonce=b"n" * 12,
            payload_aad_digest="3" * 64,
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
            reason="Synthetic schema verification.",
            correlation_id=correlation_id,
            source_channel="test",
        )
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
            source_channel="test",
        )
    return invitation, challenge, delivery


def test_invitation_digest_key_lineage_is_required_and_database_immutable() -> None:
    actor = _platform_administrator(email="digest-key-actor@example.invalid")
    subject = _reserved_person(email="digest-key-subject@example.invalid")
    _invitation, challenge, _delivery = _create_pending_graph(
        actor=actor,
        subject=subject,
    )

    challenge.token_digest_key_id = ""
    with pytest.raises(ValidationError) as captured:
        challenge.save(update_fields=("token_digest_key_id", "updated_at"))
    assert (
        captured.value.error_dict["token_digest_key_id"][0].code
        == "identity_challenge_digest_key_required"
    )

    with (
        pytest.raises(DatabaseError, match="digest-key lineage is immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_identitychallenge "
            "SET token_digest_key_id = %s WHERE id = %s",
            ["different-digest-key", challenge.id],
        )


def test_non_invitation_challenge_rejects_invitation_digest_key_raw_write() -> None:
    account = Account.objects.create_user(
        email="digest-key-verification@example.invalid",
        password="Synthetic-password-for-digest-key-test-1!",
        display_name="Synthetic Digest Verification",
    )
    challenge = IdentityChallenge.objects.create(
        account=account,
        purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
        token_digest="9" * 64,
        email_snapshot=account.email,
        expires_at=timezone.now() + timedelta(hours=1),
        request_fingerprint="8" * 64,
    )

    with (
        pytest.raises(
            DatabaseError,
            match="non-invitation challenge has an invitation digest key",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_identitychallenge "
            "SET token_digest_key_id = %s WHERE id = %s",
            ["forged-digest-key", challenge.id],
        )


def test_pending_invitation_graph_and_singleton_control_are_persisted() -> None:
    control = _inventory_control()
    actor = _platform_administrator()
    subject = _reserved_person()

    invitation, challenge, delivery = _create_pending_graph(
        actor=actor,
        subject=subject,
    )

    invitation.refresh_from_db()
    assert control.singleton is True
    assert invitation.current_challenge_id == challenge.id
    assert invitation.status == PlatformAccountInvitation.Status.PENDING
    assert delivery.status == PlatformIdentityDelivery.Status.PENDING
    assert subject.is_active is False
    assert subject.has_usable_password() is False


def test_subject_and_digest_invariants_reject_direct_bulk_writes() -> None:
    actor = _platform_administrator()
    active_subject = Account.objects.create_user(
        email="active-subject@example.invalid",
        password="Synthetic-person-password-1!",
    )
    now = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformAccountInvitation.objects.bulk_create(
            [
                PlatformAccountInvitation(
                    account=active_subject,
                    created_by=actor,
                    expires_at=now + timedelta(days=7),
                    last_transition_at=now,
                )
            ]
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        IdentityChallenge.objects.bulk_create(
            [
                IdentityChallenge(
                    account=active_subject,
                    purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
                    token_digest="A" * 64,
                    email_snapshot=active_subject.email,
                    expires_at=now + timedelta(minutes=30),
                    request_fingerprint="b" * 64,
                )
            ]
        )


def test_account_inventory_fence_covers_visible_account_writes() -> None:
    _platform_administrator()
    control = PlatformAccountInventoryControl.objects.get(singleton=True)
    initial_version = control.aggregate_version

    subject = Account.objects.create_user(
        email="inventory-subject@example.invalid",
        password="Synthetic-person-password-1!",
    )
    control.refresh_from_db()
    assert control.aggregate_version == initial_version + 1

    Account.objects.filter(pk=subject.pk).update(display_name="Inventory subject")
    control.refresh_from_db()
    assert control.aggregate_version == initial_version + 2

    # Credential material is intentionally absent from the bounded inventory
    # projection and must not invalidate an otherwise stable page cursor.
    Account.objects.filter(pk=subject.pk).update(password="!synthetic-unusable")
    control.refresh_from_db()
    assert control.aggregate_version == initial_version + 2

    Account.objects.filter(pk=subject.pk).delete()
    control.refresh_from_db()
    assert control.aggregate_version == initial_version + 3


def test_reserved_account_contact_cannot_diverge_from_pending_challenge() -> None:
    actor = _platform_administrator()
    subject = _reserved_person()
    _create_pending_graph(actor=actor, subject=subject)

    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.filter(pk=subject.pk).update(
            email="changed-after-invite@example.invalid"
        )

    subject.refresh_from_db()
    assert subject.email == "schema-person@example.invalid"


def test_incomplete_pending_graph_is_rejected_at_commit() -> None:
    actor = _platform_administrator()
    subject = _reserved_person()
    occurred_at = timezone.now()

    def create_incomplete_graph() -> None:
        with transaction.atomic():
            invitation = PlatformAccountInvitation.objects.create(
                account=subject,
                created_by=actor,
                expires_at=occurred_at + timedelta(days=7),
                last_transition_at=occurred_at,
            )
            PlatformAccountInvitationTransition.objects.create(
                invitation=invitation,
                version=1,
                operation=PlatformAccountInvitationTransition.Operation.CREATED,
                actor=actor,
                occurred_at=occurred_at,
                reason="Deliberately incomplete schema probe.",
                correlation_id=uuid4(),
                source_channel="test",
            )

    with pytest.raises(IntegrityError):
        create_incomplete_graph()


def test_transition_receipt_and_attempt_evidence_are_append_only() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT public.maru_authority_provenance_test_reset_allowed()")
        reset_escape = cursor.fetchone()
    assert reset_escape == (True,)

    actor = _platform_administrator()
    subject = _reserved_person()
    invitation, _challenge, delivery = _create_pending_graph(
        actor=actor,
        subject=subject,
    )
    transition = invitation.transitions.get(version=1)
    receipt = invitation.command_receipts.get(result_version=1)
    attempted_at = timezone.now()
    finished_at = attempted_at + timedelta(seconds=1)
    retry_at = finished_at + timedelta(minutes=1)
    lease_token = uuid4()
    delivery.status = PlatformIdentityDelivery.Status.PROCESSING
    delivery.aggregate_version += 1
    delivery.attempt_count = 1
    delivery.claimed_at = attempted_at
    delivery.lease_expires_at = attempted_at + timedelta(minutes=5)
    delivery.lease_token = lease_token
    delivery.last_attempt_at = attempted_at
    delivery.save()
    with transaction.atomic():
        attempt = PlatformIdentityDeliveryAttempt.objects.create(
            delivery=delivery,
            attempt_number=1,
            lease_token=lease_token,
            started_at=attempted_at,
            finished_at=finished_at,
            outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="provider_result_uncertain",
        )
        delivery.status = PlatformIdentityDelivery.Status.RETRYING
        delivery.aggregate_version += 1
        delivery.claimed_at = None
        delivery.lease_expires_at = None
        delivery.lease_token = None
        delivery.available_at = retry_at
        delivery.next_retry_at = retry_at
        delivery.safe_error_code = "provider_result_uncertain"
        delivery.reconciliation_state = (
            PlatformIdentityDelivery.ReconciliationState.REQUIRED
        )
        delivery.reconciliation_required_at = finished_at
        delivery.save()

    for model, record in (
        (PlatformAccountInvitationTransition, transition),
        (PlatformAccountInvitationCommandReceipt, receipt),
        (PlatformIdentityDeliveryAttempt, attempt),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=record.pk).update(updated_at=timezone.now())
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=record.pk).delete()


def test_delivery_envelope_and_attempt_bounds_are_model_validated() -> None:
    actor = _platform_administrator()
    subject = _reserved_person()
    _invitation, _challenge, delivery = _create_pending_graph(
        actor=actor,
        subject=subject,
    )

    delivery.payload_nonce = b"short"
    with pytest.raises(ValidationError, match="12-byte"):
        delivery.save()

    attempted_at = timezone.now()
    oversized_attempt = PlatformIdentityDeliveryAttempt(
        delivery=delivery,
        attempt_number=delivery.max_attempts + 1,
        lease_token=uuid4(),
        started_at=attempted_at,
        finished_at=attempted_at,
        outcome=PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
        safe_error_code="attempt_limit_reached",
    )
    with pytest.raises(ValidationError, match="exceeds"):
        oversized_attempt.save()
