"""Append-only operational finance commands and receipt snapshots."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import append_audit
from maru.authorization.policy import resolve_edition_target
from maru.identity.models import Account
from maru.registration.models import (
    FinancialLedgerEntry,
    FinancialOperation,
    PaymentProviderAccount,
    ReceiptRecord,
    Registration,
    RegistrationAdjustment,
    SettlementAllocation,
    SettlementBatch,
)
from maru.registration.services import (
    MANAGE_FINANCE,
    _append_timeline,
    _audit_record,
    _promote_waitlist_for_product,
    _publish_registration_transition,
    _record_adjustment,
    _require_decision,
    _require_reason,
)

SUPPORTED_FINANCIAL_OPERATION_KINDS = (
    FinancialOperation.Kind.CANCEL,
    FinancialOperation.Kind.REFUND,
)


def _receipt_number(*, prefix: str, entry: FinancialLedgerEntry) -> str:
    return f"{prefix}-{entry.occurred_at:%Y%m%d}-{entry.id.hex[:12].upper()}"


def record_provider_payment(
    *,
    registration: Registration,
    provider: PaymentProviderAccount,
    provider_reference: str,
    amount_minor: int,
    currency: str,
    occurred_at: datetime,
) -> FinancialLedgerEntry:
    """Idempotently materialize provider success into the operational ledger."""

    existing = FinancialLedgerEntry.objects.filter(
        provider_account=provider,
        provider_reference=provider_reference,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
    ).first()
    if existing is not None:
        return existing
    entry = FinancialLedgerEntry.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        provider_account=provider,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
        direction=FinancialLedgerEntry.Direction.INFLOW,
        amount_minor=amount_minor,
        currency=currency,
        occurred_at=occurred_at,
        provider_reference=provider_reference,
        safe_description=f"Admission payment for {registration.reference}",
    )
    ReceiptRecord.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        ledger_entry=entry,
        kind=ReceiptRecord.Kind.RECEIPT,
        document_number=_receipt_number(prefix="RCPT", entry=entry),
        issued_at=occurred_at,
        amount_minor=amount_minor,
        currency=currency,
        description_snapshot=(
            f"{registration.product_name_snapshot} — {registration.reference}"
        ),
    )
    return entry


def available_refund_minor(registration: Registration) -> int:
    values = registration.financial_ledger.values("direction").annotate(
        total=Sum("amount_minor")
    )
    totals = {row["direction"]: int(row["total"] or 0) for row in values}
    return max(
        0,
        totals.get(FinancialLedgerEntry.Direction.INFLOW, 0)
        - totals.get(FinancialLedgerEntry.Direction.OUTFLOW, 0),
    )


def propose_financial_operation(
    *,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    actor: Account,
    kind: str,
    amount_minor: int,
    reason: str,
    correlation_id: UUID,
    target_account_id: UUID | None = None,
    target_product_id: UUID | None = None,
    source_channel: str = "api",
) -> FinancialOperation:
    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_FINANCE,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.financial_operation.propose",
        target_type="registration.registration",
        target_id=registration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    if kind not in FinancialOperation.Kind.values:
        raise ValidationError(
            "Choose a supported financial operation.",
            code="financial_operation_kind_invalid",
        )
    if kind not in SUPPORTED_FINANCIAL_OPERATION_KINDS:
        raise ValidationError(
            (
                "This operation needs a recipient-acceptance or repricing "
                "workflow and is not available yet."
            ),
            code="financial_operation_workflow_unavailable",
        )
    if target_account_id is not None or target_product_id is not None:
        raise ValidationError(
            "Cancellation and refund do not accept a transfer or product target.",
            code="financial_operation_target_not_applicable",
        )
    with transaction.atomic():
        registration = Registration.objects.select_for_update().get(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if kind == FinancialOperation.Kind.REFUND:
            available = available_refund_minor(registration)
            if amount_minor < 1 or amount_minor > available:
                raise ValidationError(
                    "The refund exceeds the reconciled refundable balance.",
                    code="refund_amount_invalid",
                )
        elif amount_minor:
            raise ValidationError(
                "Only a refund proposal accepts an amount.",
                code="financial_operation_amount_not_applicable",
            )
        operation = FinancialOperation.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=kind,
            amount_minor=amount_minor,
            currency=registration.currency_snapshot,
            target_account_id=target_account_id,
            target_product_id=target_product_id,
            requested_by=actor,
            requested_at=timezone.now(),
            request_reason=normalized_reason,
        )
        append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_FINANCE,
                operation="registration.financial_operation.propose",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.financial_operation",
                target_id=operation.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="financial_operation_proposed",
                obligations=obligations,
                changed_fields=("financial_operation",),
                source_channel=source_channel,
            )
        )
        return operation


def approve_financial_operation(
    *,
    organization_id: UUID,
    edition_id: UUID,
    operation_id: UUID,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "api",
) -> FinancialOperation:
    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_FINANCE,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.financial_operation.approve",
        target_type="registration.financial_operation",
        target_id=operation_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    approved_at = timezone.now()
    with transaction.atomic():
        operation = (
            FinancialOperation.objects.select_for_update()
            .select_related("registration", "registration__product")
            .get(
                id=operation_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        if operation.status != FinancialOperation.Status.PROPOSED:
            raise ValidationError(
                "Only a proposed operation can be approved.",
                code="financial_operation_not_proposed",
            )
        if operation.kind not in SUPPORTED_FINANCIAL_OPERATION_KINDS:
            raise ValidationError(
                "This operation cannot be approved without its complete workflow.",
                code="financial_operation_workflow_unavailable",
            )
        if operation.requested_by_id == actor.id:
            raise ValidationError(
                "A different authorized person must approve this operation.",
                code="financial_operation_dual_control",
            )
        registration = Registration.objects.select_for_update().get(
            id=operation.registration_id
        )
        operation.approved_by = actor
        operation.approved_at = approved_at
        operation.approval_reason = normalized_reason
        operation.status = FinancialOperation.Status.APPROVED
        operation.safe_result_code = "approved"
        changed_fields = ["financial_operation"]
        if operation.kind == FinancialOperation.Kind.CANCEL:
            if registration.state in (
                Registration.State.CANCELLED,
                Registration.State.EXPIRED,
                Registration.State.CHECKED_IN,
            ):
                raise ValidationError(
                    "This registration cannot be cancelled in its current state.",
                    code="registration_cancellation_unavailable",
                )
            previous_state = registration.state
            registration.state = Registration.State.CANCELLED
            registration.cancelled_at = approved_at
            registration.aggregate_version += 1
            registration.save(
                update_fields=(
                    "state",
                    "cancelled_at",
                    "aggregate_version",
                    "updated_at",
                )
            )
            registration.entitlements.filter(
                status="active",
            ).update(status="revoked", updated_at=approved_at)
            _record_adjustment(
                registration=registration,
                kind=RegistrationAdjustment.Kind.REGISTRATION_CANCELLED,
                reason=normalized_reason,
                occurred_at=approved_at,
                actor_kind="account",
                actor_id=actor.id,
                from_state=previous_state,
                to_state=registration.state,
            )
            _append_timeline(
                registration=registration,
                kind="registration_cancelled",
                title="Registration cancelled",
                summary=(
                    "Registration staff cancelled the admission. Any refund is "
                    "tracked separately."
                ),
                occurred_at=approved_at,
                actor_kind="account",
                actor_id=actor.id,
                correlation_id=correlation_id,
            )
            operation.status = FinancialOperation.Status.COMPLETED
            operation.completed_at = approved_at
            operation.safe_result_code = "registration_cancelled"
            changed_fields.extend(("state", "entitlement", "timeline"))
            _publish_registration_transition(
                registration=registration,
                event_name="registration.cancelled.v1",
                from_state=previous_state,
                correlation_id=correlation_id,
                actor_kind="account",
                actor_id=actor.id,
            )
            _promote_waitlist_for_product(
                product=registration.product,
                offered_at=approved_at,
                correlation_id=correlation_id,
            )
        elif operation.kind == FinancialOperation.Kind.REFUND:
            if operation.amount_minor > available_refund_minor(registration):
                raise ValidationError(
                    "The refundable balance changed; review the proposal again.",
                    code="refund_balance_changed",
                )
            operation.status = FinancialOperation.Status.PROVIDER_PENDING
            operation.safe_result_code = "refund_provider_pending"
        operation.save(
            update_fields=(
                "approved_by",
                "approved_at",
                "approval_reason",
                "status",
                "completed_at",
                "safe_result_code",
                "updated_at",
            )
        )
        append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_FINANCE,
                operation="registration.financial_operation.approve",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.financial_operation",
                target_id=operation.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=operation.safe_result_code,
                obligations=obligations,
                changed_fields=tuple(changed_fields),
                source_channel=source_channel,
            )
        )
        return operation


def record_provider_refund(
    *,
    operation: FinancialOperation,
    provider: PaymentProviderAccount,
    provider_reference: str,
    occurred_at: datetime,
) -> FinancialLedgerEntry:
    """Complete an approved refund after authenticated provider evidence."""

    with transaction.atomic():
        operation = FinancialOperation.objects.select_for_update().get(id=operation.id)
        if operation.status == FinancialOperation.Status.COMPLETED:
            existing = operation.ledger_entries.filter(
                kind=FinancialLedgerEntry.Kind.REFUND
            ).first()
            if existing is None:
                raise ValidationError(
                    "The completed refund has no ledger evidence.",
                    code="refund_ledger_missing",
                )
            return existing
        if operation.status != FinancialOperation.Status.PROVIDER_PENDING:
            raise ValidationError(
                "The refund is not waiting for provider confirmation.",
                code="refund_not_provider_pending",
            )
        entry = FinancialLedgerEntry.objects.create(
            registration=operation.registration,
            operation=operation,
            organization_id=operation.organization_id,
            edition_id=operation.edition_id,
            provider_account=provider,
            kind=FinancialLedgerEntry.Kind.REFUND,
            direction=FinancialLedgerEntry.Direction.OUTFLOW,
            amount_minor=operation.amount_minor,
            currency=operation.currency,
            occurred_at=occurred_at,
            provider_reference=provider_reference,
            safe_description=f"Refund for {operation.registration.reference}",
        )
        ReceiptRecord.objects.create(
            registration=operation.registration,
            organization_id=operation.organization_id,
            edition_id=operation.edition_id,
            ledger_entry=entry,
            kind=ReceiptRecord.Kind.CREDIT_NOTE,
            document_number=_receipt_number(prefix="CREDIT", entry=entry),
            issued_at=occurred_at,
            amount_minor=operation.amount_minor,
            currency=operation.currency,
            description_snapshot=f"Refund — {operation.registration.reference}",
        )
        operation.status = FinancialOperation.Status.COMPLETED
        operation.completed_at = occurred_at
        operation.safe_result_code = "refund_reconciled"
        operation.save(
            update_fields=(
                "status",
                "completed_at",
                "safe_result_code",
                "updated_at",
            )
        )
        return entry


def reconcile_provider_settlement(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    provider_account_id: UUID,
    provider_reference: str,
    currency: str,
    gross_minor: int,
    fee_minor: int,
    refund_minor: int,
    dispute_minor: int,
    net_minor: int,
    settled_at: datetime,
    ledger_entry_ids: tuple[UUID, ...],
    reason: str,
    correlation_id: UUID,
) -> SettlementBatch:
    """Reconcile a provider payout to every included append-only movement."""

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_FINANCE,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.settlement.reconcile",
        target_type="registration.settlement_batch",
        target_id=None,
        correlation_id=correlation_id,
        source_channel="api",
    )
    normalized_reference = provider_reference.strip()
    normalized_reason = _require_reason(reason)
    normalized_currency = currency.upper()
    if not normalized_reference or len(set(ledger_entry_ids)) != len(ledger_entry_ids):
        raise ValidationError(
            "Settlement reference and unique movement identifiers are required.",
            code="settlement_input_invalid",
        )
    if net_minor != gross_minor - fee_minor - refund_minor - dispute_minor:
        raise ValidationError(
            "Settlement totals do not reconcile to the provider net amount.",
            code="settlement_total_mismatch",
        )
    with transaction.atomic():
        provider = PaymentProviderAccount.objects.get(
            id=provider_account_id,
            organization_id=organization_id,
        )
        entries = list(
            FinancialLedgerEntry.objects.select_for_update()
            .filter(
                id__in=ledger_entry_ids,
                organization_id=organization_id,
                edition_id=edition_id,
                provider_account=provider,
                currency=normalized_currency,
            )
            .select_related("provider_account")
        )
        if len(entries) != len(ledger_entry_ids):
            raise ValidationError(
                "One or more settlement movements are unavailable.",
                code="settlement_movement_unavailable",
            )
        totals = {
            kind: sum(entry.amount_minor for entry in entries if entry.kind == kind)
            for kind in (
                FinancialLedgerEntry.Kind.PAYMENT,
                FinancialLedgerEntry.Kind.REFUND,
                FinancialLedgerEntry.Kind.DISPUTE,
                FinancialLedgerEntry.Kind.CHARGEBACK,
            )
        }
        if (
            totals[FinancialLedgerEntry.Kind.PAYMENT] != gross_minor
            or totals[FinancialLedgerEntry.Kind.REFUND] != refund_minor
            or totals[FinancialLedgerEntry.Kind.DISPUTE]
            + totals[FinancialLedgerEntry.Kind.CHARGEBACK]
            != dispute_minor
        ):
            raise ValidationError(
                "Selected movements do not match the settlement totals.",
                code="settlement_allocation_mismatch",
            )
        if any(hasattr(entry, "settlement_allocation") for entry in entries):
            raise ValidationError(
                "A movement is already allocated to another settlement.",
                code="settlement_movement_already_allocated",
            )
        batch = SettlementBatch.objects.create(
            provider_account=provider,
            organization_id=organization_id,
            edition_id=edition_id,
            provider_reference=normalized_reference,
            currency=normalized_currency,
            gross_minor=gross_minor,
            fee_minor=fee_minor,
            refund_minor=refund_minor,
            dispute_minor=dispute_minor,
            net_minor=net_minor,
            settled_at=settled_at,
            status=SettlementBatch.Status.RECONCILED,
            reconciled_at=timezone.now(),
            reconciled_by_id=actor.id,
            safe_result_code="settlement_reconciled",
        )
        SettlementAllocation.objects.bulk_create(
            [
                SettlementAllocation(
                    settlement=batch,
                    ledger_entry=entry,
                    amount_minor=entry.amount_minor,
                )
                for entry in entries
            ]
        )
        if fee_minor:
            FinancialLedgerEntry.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                provider_account=provider,
                kind=FinancialLedgerEntry.Kind.PROVIDER_FEE,
                direction=FinancialLedgerEntry.Direction.OUTFLOW,
                amount_minor=fee_minor,
                currency=normalized_currency,
                occurred_at=settled_at,
                provider_reference=normalized_reference,
                settlement_reference=normalized_reference,
                safe_description="Provider settlement fee",
            )
        FinancialLedgerEntry.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            provider_account=provider,
            kind=FinancialLedgerEntry.Kind.SETTLEMENT,
            direction=FinancialLedgerEntry.Direction.NONCASH,
            amount_minor=net_minor,
            currency=normalized_currency,
            occurred_at=settled_at,
            provider_reference=normalized_reference,
            settlement_reference=normalized_reference,
            safe_description="Provider settlement reconciliation",
        )
        append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_FINANCE,
                operation="registration.settlement.reconcile",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.settlement_batch",
                target_id=batch.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="settlement_reconciled",
                obligations=obligations,
                changed_fields=("settlement", "allocations", "ledger"),
                source_channel="api",
            )
        )
        _ = normalized_reason
        return batch
