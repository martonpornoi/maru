"""Reasoned operator commands for uncertain platform invitation delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_commands import (
    InvitationRetryConflictError,
    InvitationStateConflictError,
    InvitationUnavailableError,
    InvitationVersionConflictError,
    _advance_inventory_control,
    _lock_inventory_control,
    _lock_platform_actor,
    _require_platform_actor,
    _retry_key_hash,
)
from maru.identity.invitation_inputs import (
    canonical_request_digest,
    normalize_invitation_reason,
    validate_correlation_id,
    validate_invitation_expected_version,
    validate_retry_key,
    validate_source_channel,
)
from maru.identity.models import (
    Account,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryReconciliationReceipt,
)

RECONCILIATION_CONTRACT_VERSION = "page10-invitation-delivery-reconciliation-v1"
MAX_PROVIDER_REFERENCE_LENGTH = 160
MAX_DELIVERY_ATTEMPTS = 100


@dataclass(frozen=True, slots=True)
class DeliveryReconciliationResult:
    delivery: PlatformIdentityDelivery
    receipt: PlatformIdentityDeliveryReconciliationReceipt
    replayed: bool


def _normalize_provider_reference(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_PROVIDER_REFERENCE_LENGTH
        or not value.isprintable()
    ):
        raise ValidationError(
            {"provider_reference": "Enter a valid provider reference."},
            code="identity_delivery_provider_reference_invalid",
        )
    return value


def _locked_delivery(delivery_id: UUID) -> PlatformIdentityDelivery:
    delivery = (
        PlatformIdentityDelivery.objects.select_for_update()
        .select_related("invitation", "challenge")
        .filter(id=delivery_id)
        .first()
    )
    if delivery is None:
        raise InvitationUnavailableError
    return delivery


def _matching_receipt(
    *,
    control: PlatformAccountInventoryControl,
    actor: Account,
    retry_key: UUID,
    delivery: PlatformIdentityDelivery,
    operation: str,
    request_digest: str,
) -> PlatformIdentityDeliveryReconciliationReceipt | None:
    receipt = (
        PlatformIdentityDeliveryReconciliationReceipt.objects.select_for_update()
        .filter(
            inventory_control=control,
            actor=actor,
            retry_key=retry_key,
        )
        .first()
    )
    if receipt is None:
        return None
    if (
        receipt.delivery_id != delivery.id
        or receipt.operation != operation
        or receipt.request_digest != request_digest
    ):
        raise InvitationRetryConflictError
    return receipt


def _require_reconcilable(delivery: PlatformIdentityDelivery, *, now: datetime) -> None:
    if (
        delivery.reconciliation_state
        != PlatformIdentityDelivery.ReconciliationState.REQUIRED
        or delivery.status == PlatformIdentityDelivery.Status.PROCESSING
        or delivery.cancellation_requested_at is not None
    ):
        raise InvitationStateConflictError
    invitation = delivery.invitation
    challenge = delivery.challenge
    if (
        invitation.status != PlatformAccountInvitation.Status.PENDING
        or invitation.current_challenge_id != challenge.id
        or invitation.expires_at <= now
        or challenge.expires_at <= now
        or challenge.consumed_at is not None
        or challenge.invalidated_at is not None
    ):
        raise InvitationStateConflictError


def _reconciliation_occurred_at(delivery: PlatformIdentityDelivery) -> datetime:
    """Keep reconciliation evidence monotonic across worker clock movement."""

    observed_at = timezone.now()
    required_at = delivery.reconciliation_required_at
    if required_at is not None and required_at > observed_at:
        return required_at
    return observed_at


def _destroy_confirmed_payload(
    delivery: PlatformIdentityDelivery,
    *,
    occurred_at: datetime,
) -> None:
    if delivery.payload_destroyed_at is not None:
        return
    delivery.encryption_algorithm = ""
    delivery.encryption_key_id = ""
    delivery.encrypted_payload = None
    delivery.wrapped_data_key = None
    delivery.payload_nonce = None
    delivery.payload_aad_digest = ""
    delivery.payload_destroyed_at = occurred_at
    delivery.payload_destruction_reason = (
        PlatformIdentityDelivery.PayloadDestructionReason.DELIVERED
    )


def _audit_reconciliation(
    *,
    actor: Account,
    delivery: PlatformIdentityDelivery,
    operation: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    occurred_at: datetime,
    retry_key: UUID,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="identity.reconcile_account_invitation_delivery",
            operation="identity.account_invitation.delivery_reconcile",
            target_type="identity.platform_identity_delivery",
            target_id=delivery.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=operation,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=("delivery", "reconciliation", "receipt"),
            safe_metadata={"contract_version": RECONCILIATION_CONTRACT_VERSION},
            retention_class="identity-restricted",
            idempotency_key_hash=_retry_key_hash(retry_key),
        ),
        occurred_at=occurred_at,
    )


def _positive_expected_version(value: object) -> int:
    version = validate_invitation_expected_version(value)
    if version == 0:
        raise ValidationError(
            {"expected_version": "Enter the current positive delivery version."},
            code="identity_delivery_expected_version_invalid",
        )
    return version


def resolve_platform_identity_delivery_as_delivered(
    *,
    actor: Account,
    delivery_id: UUID,
    expected_version: object,
    provider_reference: object,
    reason: object,
    retry_key: object,
    correlation_id: object,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> DeliveryReconciliationResult:
    _require_platform_actor(actor)
    version = _positive_expected_version(expected_version)
    normalized_reference = _normalize_provider_reference(provider_reference)
    normalized_reason = normalize_invitation_reason(reason)
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    operation = str(
        PlatformIdentityDeliveryReconciliationReceipt.Operation.RESOLVE_DELIVERED
    )
    request_digest = canonical_request_digest(
        {
            "operation": operation,
            "delivery_id": delivery_id,
            "expected_version": version,
            "provider_reference": normalized_reference,
            "reason": normalized_reason,
        }
    )
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        control = _lock_inventory_control()
        delivery = _locked_delivery(delivery_id)
        existing = _matching_receipt(
            control=control,
            actor=locked_actor,
            retry_key=key,
            delivery=delivery,
            operation=operation,
            request_digest=request_digest,
        )
        if existing is not None:
            return DeliveryReconciliationResult(
                delivery=delivery,
                receipt=existing,
                replayed=True,
            )
        if delivery.aggregate_version != version:
            raise InvitationVersionConflictError
        occurred_at = _reconciliation_occurred_at(delivery)
        _require_reconcilable(delivery, now=occurred_at)
        if delivery.status not in (
            PlatformIdentityDelivery.Status.RETRYING,
            PlatformIdentityDelivery.Status.PERMANENT_FAILED,
            PlatformIdentityDelivery.Status.DELIVERED,
        ):
            raise InvitationStateConflictError
        if (
            delivery.provider_reference
            and delivery.provider_reference != normalized_reference
        ):
            raise InvitationStateConflictError
        _destroy_confirmed_payload(delivery, occurred_at=occurred_at)
        delivery.status = PlatformIdentityDelivery.Status.DELIVERED
        delivery.delivered_at = delivery.delivered_at or occurred_at
        delivery.provider_reference = normalized_reference
        delivery.safe_error_code = ""
        delivery.next_retry_at = None
        delivery.reconciliation_state = (
            PlatformIdentityDelivery.ReconciliationState.RESOLVED
        )
        delivery.reconciled_at = occurred_at
        delivery.reconciliation_code = "operator_confirmed_delivered"
        delivery.aggregate_version = version + 1
        delivery.save()
        _advance_inventory_control(control)
        receipt = PlatformIdentityDeliveryReconciliationReceipt.objects.create(
            inventory_control=control,
            delivery=delivery,
            actor=locked_actor,
            operation=operation,
            reason=normalized_reason,
            retry_key=key,
            request_digest=request_digest,
            expected_version=version,
            result_version=version + 1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _audit_reconciliation(
            actor=locked_actor,
            delivery=delivery,
            operation=operation,
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return DeliveryReconciliationResult(
            delivery=delivery,
            receipt=receipt,
            replayed=False,
        )


def resolve_platform_identity_delivery_for_retry(
    *,
    actor: Account,
    delivery_id: UUID,
    expected_version: object,
    reason: object,
    retry_key: object,
    correlation_id: object,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> DeliveryReconciliationResult:
    _require_platform_actor(actor)
    version = _positive_expected_version(expected_version)
    normalized_reason = normalize_invitation_reason(reason)
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    operation = str(
        PlatformIdentityDeliveryReconciliationReceipt.Operation.RESOLVE_RETRY
    )
    request_digest = canonical_request_digest(
        {
            "operation": operation,
            "delivery_id": delivery_id,
            "expected_version": version,
            "reason": normalized_reason,
        }
    )
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        control = _lock_inventory_control()
        delivery = _locked_delivery(delivery_id)
        existing = _matching_receipt(
            control=control,
            actor=locked_actor,
            retry_key=key,
            delivery=delivery,
            operation=operation,
            request_digest=request_digest,
        )
        if existing is not None:
            return DeliveryReconciliationResult(
                delivery=delivery,
                receipt=existing,
                replayed=True,
            )
        if delivery.aggregate_version != version:
            raise InvitationVersionConflictError
        occurred_at = _reconciliation_occurred_at(delivery)
        _require_reconcilable(delivery, now=occurred_at)
        if (
            delivery.status
            not in (
                PlatformIdentityDelivery.Status.RETRYING,
                PlatformIdentityDelivery.Status.PERMANENT_FAILED,
            )
            or delivery.payload_destroyed_at is not None
        ):
            raise InvitationStateConflictError
        if delivery.attempt_count >= delivery.max_attempts:
            if delivery.max_attempts >= MAX_DELIVERY_ATTEMPTS:
                raise InvitationStateConflictError
            delivery.max_attempts += 1
        delivery.status = PlatformIdentityDelivery.Status.RETRYING
        delivery.available_at = occurred_at
        delivery.next_retry_at = occurred_at
        delivery.safe_error_code = "delivery_reconciliation_retry"
        delivery.reconciliation_state = (
            PlatformIdentityDelivery.ReconciliationState.RESOLVED
        )
        delivery.reconciled_at = occurred_at
        delivery.reconciliation_code = "operator_confirmed_retry"
        delivery.aggregate_version = version + 1
        delivery.save()
        _advance_inventory_control(control)
        receipt = PlatformIdentityDeliveryReconciliationReceipt.objects.create(
            inventory_control=control,
            delivery=delivery,
            actor=locked_actor,
            operation=operation,
            reason=normalized_reason,
            retry_key=key,
            request_digest=request_digest,
            expected_version=version,
            result_version=version + 1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _audit_reconciliation(
            actor=locked_actor,
            delivery=delivery,
            operation=operation,
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return DeliveryReconciliationResult(
            delivery=delivery,
            receipt=receipt,
            replayed=False,
        )


__all__ = [
    "DeliveryReconciliationResult",
    "resolve_platform_identity_delivery_as_delivered",
    "resolve_platform_identity_delivery_for_retry",
]
