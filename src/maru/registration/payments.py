"""Hosted payment adapter and authenticated webhook reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID, uuid5

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import append_audit
from maru.identity.models import Account
from maru.registration.finance import record_provider_payment, record_provider_refund
from maru.registration.models import (
    FinancialLedgerEntry,
    FinancialOperation,
    PaymentAttempt,
    PaymentException,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentWebhookReceipt,
    Registration,
)
from maru.registration.services import (
    MANAGE_FINANCE,
    _append_timeline,
    _audit_record,
    _grant_product_entitlement,
    _publish_registration_transition,
    _require_decision,
    _system_audit,
)

WEBHOOK_REPLAY_WINDOW: Final = timedelta(minutes=5)
PAYMENT_EVENT_NAMESPACE: Final = UUID("29d5e26f-a49b-48b6-8db9-b5a077dfe1fc")
PROVIDER_TIMEOUT_SECONDS: Final = 8


def _validate_provider_url(value: str) -> str:
    """Require HTTPS and an explicit deployment-owned provider host."""

    parsed = urlsplit(value)
    allowed_hosts = {
        str(host).casefold()
        for host in getattr(settings, "MARU_PAYMENT_PROVIDER_HOSTS", ())
    }
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (allowed_hosts and hostname not in allowed_hosts)
    ):
        raise ValidationError(
            "The payment provider URL is not permitted by deployment policy.",
            code="payment_provider_url_not_allowed",
        )
    return value


@dataclass(frozen=True, slots=True)
class HostedCheckout:
    provider_reference: str
    checkout_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedPaymentEvent:
    remote_event_id: str
    provider_reference: str
    event_type: str
    amount_minor: int
    currency: str
    occurred_at: datetime


class HostedPaymentAdapter(Protocol):
    def create_checkout(
        self,
        *,
        provider: PaymentProviderAccount,
        intent: PaymentIntent,
        return_url: str,
    ) -> HostedCheckout: ...


class JsonHostedPaymentAdapter:
    """Small provider contract that keeps card data on a hosted checkout."""

    def create_checkout(
        self,
        *,
        provider: PaymentProviderAccount,
        intent: PaymentIntent,
        return_url: str,
    ) -> HostedCheckout:
        credential = os.environ.get(provider.credential_env_var, "")
        if not credential:
            raise ValidationError(
                "The payment provider credential is unavailable.",
                code="payment_provider_not_configured",
            )
        body = json.dumps(
            {
                "idempotency_key": str(intent.id),
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
                "reference": intent.registration.reference,
                "return_url": return_url,
            },
            separators=(",", ":"),
        ).encode()
        endpoint = _validate_provider_url(
            f"{provider.api_base_url.rstrip('/')}/payment-intents"
        )
        request = UrlRequest(  # noqa: S310
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
                "Idempotency-Key": str(intent.id),
            },
            method="POST",
        )
        try:
            with urlopen(  # noqa: S310
                request,
                timeout=PROVIDER_TIMEOUT_SECONDS,
            ) as response:
                response_data = json.loads(response.read(32_768))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValidationError(
                "The payment provider is temporarily unavailable.",
                code="payment_provider_unavailable",
            ) from error
        try:
            provider_reference = str(response_data["id"])
            checkout_url = str(response_data["checkout_url"])
            expires_at = datetime.fromisoformat(str(response_data["expires_at"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError(
                "The payment provider returned an invalid response.",
                code="payment_provider_invalid_response",
            ) from error
        _validate_provider_url(checkout_url)
        if expires_at.tzinfo is None:
            raise ValidationError(
                "The payment provider returned an invalid expiry.",
                code="payment_provider_invalid_response",
            )
        return HostedCheckout(
            provider_reference=provider_reference,
            checkout_url=checkout_url,
            expires_at=expires_at,
        )


ADAPTERS: dict[str, HostedPaymentAdapter] = {
    "json_hosted_v1": JsonHostedPaymentAdapter(),
}


def create_payment_intent(
    *,
    registration: Registration,
    provider_account_id: UUID,
    idempotency_key: UUID,
    return_url: str,
    now: datetime | None = None,
) -> PaymentIntent:
    created_at = now or timezone.now()
    with transaction.atomic():
        locked = Registration.objects.select_for_update().get(id=registration.id)
        provider = PaymentProviderAccount.objects.select_for_update().get(
            id=provider_account_id,
            organization_id=locked.organization_id,
            enabled=True,
        )
        existing = PaymentIntent.objects.filter(
            provider_account=provider,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if existing.registration_id != locked.id:
                raise ValidationError(
                    "The payment idempotency key belongs to another operation.",
                    code="payment_idempotency_conflict",
                )
            return existing
        if locked.state != Registration.State.PAYMENT_PENDING:
            raise ValidationError(
                "This registration is not waiting for payment.",
                code="registration_not_payment_pending",
            )
        if locked.payment_due_at is None or locked.payment_due_at <= created_at:
            raise ValidationError(
                "The payment reservation has expired.",
                code="registration_payment_deadline_passed",
            )
        intent = PaymentIntent.objects.create(
            registration=locked,
            organization_id=locked.organization_id,
            edition_id=locked.edition_id,
            provider_account=provider,
            idempotency_key=idempotency_key,
            amount_minor=locked.price_minor_snapshot,
            currency=locked.currency_snapshot,
            status=PaymentIntent.Status.CREATING,
            expires_at=locked.payment_due_at,
        )
    adapter = ADAPTERS.get(provider.adapter)
    if adapter is None:
        error = ValidationError(
            "The configured payment adapter is unavailable.",
            code="payment_adapter_unknown",
        )
    else:
        try:
            checkout = adapter.create_checkout(
                provider=provider,
                intent=intent,
                return_url=return_url,
            )
        except ValidationError as caught:
            error = caught
        else:
            with transaction.atomic():
                intent = PaymentIntent.objects.select_for_update().get(id=intent.id)
                intent.provider_reference = checkout.provider_reference
                intent.checkout_url = checkout.checkout_url
                intent.expires_at = min(intent.expires_at, checkout.expires_at)
                intent.status = PaymentIntent.Status.CHECKOUT_READY
                intent.safe_result_code = "checkout_created"
                intent.save(
                    update_fields=(
                        "provider_reference",
                        "checkout_url",
                        "expires_at",
                        "status",
                        "safe_result_code",
                        "updated_at",
                    )
                )
                return intent
    with transaction.atomic():
        intent = PaymentIntent.objects.select_for_update().get(id=intent.id)
        intent.status = PaymentIntent.Status.UNCERTAIN
        intent.safe_result_code = getattr(error, "code", None) or "provider_unavailable"
        intent.save(update_fields=("status", "safe_result_code", "updated_at"))
        PaymentException.objects.create(
            organization_id=intent.organization_id,
            edition_id=intent.edition_id,
            provider_account=intent.provider_account,
            payment_intent=intent,
            kind=PaymentException.Kind.PROVIDER_UNAVAILABLE,
            safe_summary="Hosted checkout creation needs reconciliation.",
            opened_at=timezone.now(),
        )
    raise error


def _verify_signature(
    *,
    provider: PaymentProviderAccount,
    body: bytes,
    signature: str,
    timestamp: str,
    now: datetime,
) -> datetime:
    try:
        timestamp_value = int(timestamp)
        signed_at = datetime.fromtimestamp(timestamp_value, tz=UTC)
    except (ValueError, OverflowError) as error:
        raise ValidationError(
            "The payment message signature is invalid.",
            code="payment_webhook_invalid_signature",
        ) from error
    if abs(now - signed_at) > WEBHOOK_REPLAY_WINDOW:
        raise ValidationError(
            "The payment message is outside the replay window.",
            code="payment_webhook_replay_window",
        )
    secret = os.environ.get(provider.webhook_secret_env_var, "")
    if not secret:
        raise ValidationError(
            "The payment webhook is not configured.",
            code="payment_webhook_not_configured",
        )
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    supplied = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, supplied):
        raise ValidationError(
            "The payment message signature is invalid.",
            code="payment_webhook_invalid_signature",
        )
    return signed_at


def parse_verified_payment_event(
    *,
    provider: PaymentProviderAccount,
    body: bytes,
    signature: str,
    timestamp: str,
    now: datetime | None = None,
) -> tuple[VerifiedPaymentEvent, datetime, str]:
    received_at = now or timezone.now()
    signed_at = _verify_signature(
        provider=provider,
        body=body,
        signature=signature,
        timestamp=timestamp,
        now=received_at,
    )
    try:
        payload = json.loads(body)
        event = VerifiedPaymentEvent(
            remote_event_id=str(payload["event_id"]),
            provider_reference=str(payload["payment_intent_id"]),
            event_type=str(payload["type"]),
            amount_minor=int(payload["amount_minor"]),
            currency=str(payload["currency"]).upper(),
            occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationError(
            "The payment message payload is invalid.",
            code="payment_webhook_invalid_payload",
        ) from error
    if event.occurred_at.tzinfo is None or event.amount_minor < 0:
        raise ValidationError(
            "The payment message payload is invalid.",
            code="payment_webhook_invalid_payload",
        )
    return event, signed_at, hashlib.sha256(body).hexdigest()


def _open_payment_exception(
    *,
    provider: PaymentProviderAccount,
    intent: PaymentIntent | None,
    kind: str,
    summary: str,
    now: datetime,
) -> None:
    PaymentException.objects.create(
        organization_id=provider.organization_id,
        edition_id=intent.edition_id if intent else None,
        provider_account=provider,
        payment_intent=intent,
        kind=kind,
        safe_summary=summary,
        opened_at=now,
    )


def reconcile_verified_payment_event(  # noqa: PLR0912, PLR0915
    *,
    provider: PaymentProviderAccount,
    event: VerifiedPaymentEvent,
    signed_at: datetime,
    payload_digest: str,
    correlation_id: UUID,
    received_at: datetime | None = None,
) -> PaymentWebhookReceipt:
    now = received_at or timezone.now()
    with transaction.atomic():
        existing = PaymentWebhookReceipt.objects.filter(
            provider_account=provider,
            remote_event_id=event.remote_event_id,
        ).first()
        if existing is not None:
            if existing.payload_digest != payload_digest:
                raise ValidationError(
                    "A provider event identifier was reused with different content.",
                    code="payment_webhook_event_conflict",
                )
            return existing
        intent = (
            PaymentIntent.objects.select_for_update()
            .select_related("registration", "provider_account")
            .filter(
                provider_account=provider,
                provider_reference=event.provider_reference,
            )
            .first()
        )
        if intent is None:
            _open_payment_exception(
                provider=provider,
                intent=None,
                kind=PaymentException.Kind.UNKNOWN_INTENT,
                summary="Provider reported a payment intent Maru cannot identify.",
                now=now,
            )
            return PaymentWebhookReceipt.objects.create(
                provider_account=provider,
                organization_id=provider.organization_id,
                remote_event_id=event.remote_event_id,
                payload_digest=payload_digest,
                signature_timestamp=signed_at,
                received_at=now,
                outcome=PaymentWebhookReceipt.Outcome.EXCEPTION,
                safe_result_code="unknown_payment_intent",
            )
        registration = Registration.objects.select_for_update().get(
            id=intent.registration_id
        )
        if event.event_type == "payment.refunded":
            if event.currency != intent.currency:
                _open_payment_exception(
                    provider=provider,
                    intent=intent,
                    kind=PaymentException.Kind.CURRENCY_MISMATCH,
                    summary="Provider refund currency differs from the local intent.",
                    now=now,
                )
                outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
                result_code = "refund_currency_mismatch"
            else:
                operation = (
                    FinancialOperation.objects.select_for_update()
                    .filter(
                        registration=registration,
                        kind=FinancialOperation.Kind.REFUND,
                        status=FinancialOperation.Status.PROVIDER_PENDING,
                        amount_minor=event.amount_minor,
                        currency=event.currency,
                    )
                    .order_by("approved_at", "id")
                    .first()
                )
                if operation is None:
                    _open_payment_exception(
                        provider=provider,
                        intent=intent,
                        kind=PaymentException.Kind.OUT_OF_ORDER,
                        summary=(
                            "Provider reported a refund without a matching approved "
                            "refund operation."
                        ),
                        now=now,
                    )
                    outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
                    result_code = "refund_operation_missing"
                else:
                    record_provider_refund(
                        operation=operation,
                        provider=provider,
                        provider_reference=event.remote_event_id,
                        occurred_at=event.occurred_at,
                    )
                    outcome = PaymentWebhookReceipt.Outcome.APPLIED
                    result_code = "refund_reconciled"
        elif event.event_type in {"payment.disputed", "payment.chargeback"}:
            if (
                event.currency != intent.currency
                or event.amount_minor > intent.amount_minor
            ):
                _open_payment_exception(
                    provider=provider,
                    intent=intent,
                    kind=PaymentException.Kind.AMOUNT_MISMATCH,
                    summary="Provider dispute does not match the local payment.",
                    now=now,
                )
                outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
                result_code = "dispute_mismatch"
            else:
                ledger_kind = (
                    FinancialLedgerEntry.Kind.CHARGEBACK
                    if event.event_type == "payment.chargeback"
                    else FinancialLedgerEntry.Kind.DISPUTE
                )
                FinancialLedgerEntry.objects.create(
                    registration=registration,
                    organization_id=registration.organization_id,
                    edition_id=registration.edition_id,
                    provider_account=provider,
                    kind=ledger_kind,
                    direction=FinancialLedgerEntry.Direction.OUTFLOW,
                    amount_minor=event.amount_minor,
                    currency=event.currency,
                    occurred_at=event.occurred_at,
                    provider_reference=event.remote_event_id,
                    safe_description=(
                        "Provider chargeback"
                        if event.event_type == "payment.chargeback"
                        else "Provider dispute hold"
                    ),
                )
                _open_payment_exception(
                    provider=provider,
                    intent=intent,
                    kind=PaymentException.Kind.DISPUTE_REVIEW,
                    summary=(
                        "Provider reported a dispute or chargeback. Finance must "
                        "review admission and evidence."
                    ),
                    now=now,
                )
                outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
                result_code = event.event_type.replace(".", "_")
        elif event.amount_minor != intent.amount_minor:
            intent.status = PaymentIntent.Status.MISMATCH
            intent.safe_result_code = "amount_mismatch"
            intent.save(update_fields=("status", "safe_result_code", "updated_at"))
            _open_payment_exception(
                provider=provider,
                intent=intent,
                kind=PaymentException.Kind.AMOUNT_MISMATCH,
                summary="Provider amount differs from the locally recorded intent.",
                now=now,
            )
            outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
            result_code = "amount_mismatch"
        elif event.currency != intent.currency:
            intent.status = PaymentIntent.Status.MISMATCH
            intent.safe_result_code = "currency_mismatch"
            intent.save(update_fields=("status", "safe_result_code", "updated_at"))
            _open_payment_exception(
                provider=provider,
                intent=intent,
                kind=PaymentException.Kind.CURRENCY_MISMATCH,
                summary="Provider currency differs from the locally recorded intent.",
                now=now,
            )
            outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
            result_code = "currency_mismatch"
        elif event.event_type == "payment.succeeded":
            if (
                registration.state != Registration.State.PAYMENT_PENDING
                or registration.payment_due_at is None
                or event.occurred_at >= registration.payment_due_at
            ):
                intent.status = PaymentIntent.Status.LATE
                intent.safe_result_code = "late_success"
                intent.last_provider_event_at = event.occurred_at
                intent.save(
                    update_fields=(
                        "status",
                        "safe_result_code",
                        "last_provider_event_at",
                        "updated_at",
                    )
                )
                _open_payment_exception(
                    provider=provider,
                    intent=intent,
                    kind=PaymentException.Kind.LATE_SUCCESS,
                    summary=(
                        "Provider reports success after the reservation stopped "
                        "holding capacity."
                    ),
                    now=now,
                )
                outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
                result_code = "late_success"
            else:
                PaymentAttempt.objects.create(
                    registration=registration,
                    organization_id=registration.organization_id,
                    edition_id=registration.edition_id,
                    provider=provider.code,
                    provider_reference=event.remote_event_id,
                    idempotency_key=uuid5(
                        PAYMENT_EVENT_NAMESPACE,
                        f"{provider.id}:{event.remote_event_id}",
                    ),
                    amount_minor=event.amount_minor,
                    currency=event.currency,
                    status=PaymentAttempt.Status.SUCCEEDED,
                    occurred_at=event.occurred_at,
                    safe_result_code="provider_payment_succeeded",
                )
                record_provider_payment(
                    registration=registration,
                    provider=provider,
                    provider_reference=event.remote_event_id,
                    amount_minor=event.amount_minor,
                    currency=event.currency,
                    occurred_at=event.occurred_at,
                )
                previous_state = registration.state
                registration.state = Registration.State.CONFIRMED
                registration.aggregate_version += 1
                registration.confirmed_at = event.occurred_at
                registration.confirmation_basis = (
                    Registration.ConfirmationBasis.PROVIDER
                )
                registration.save(
                    update_fields=(
                        "state",
                        "aggregate_version",
                        "confirmed_at",
                        "confirmation_basis",
                        "updated_at",
                    )
                )
                _grant_product_entitlement(
                    registration=registration,
                    granted_at=event.occurred_at,
                )
                _append_timeline(
                    registration=registration,
                    kind="payment_confirmed",
                    title="Payment confirmed",
                    summary=(
                        "The hosted payment provider confirmed payment and "
                        "admission is active."
                    ),
                    occurred_at=event.occurred_at,
                    actor_kind="provider",
                    actor_id=None,
                    correlation_id=correlation_id,
                )
                audit = _system_audit(
                    registration=registration,
                    operation="registration.payment.webhook_reconcile",
                    reason_code="provider_payment_reconciled",
                    correlation_id=correlation_id,
                    changed_fields=(
                        "state",
                        "payment_attempt",
                        "entitlement",
                        "timeline",
                    ),
                )
                _publish_registration_transition(
                    registration=registration,
                    event_name="registration.payment.reconciled.v1",
                    from_state=previous_state,
                    correlation_id=correlation_id,
                    actor_kind="provider",
                    actor_id=None,
                    causation_id=audit.id,
                    workload_pool="payments",
                )
                intent.status = PaymentIntent.Status.SUCCEEDED
                intent.safe_result_code = "payment_reconciled"
                intent.last_provider_event_at = event.occurred_at
                intent.save(
                    update_fields=(
                        "status",
                        "safe_result_code",
                        "last_provider_event_at",
                        "updated_at",
                    )
                )
                outcome = PaymentWebhookReceipt.Outcome.APPLIED
                result_code = "payment_reconciled"
        elif event.event_type in {"payment.failed", "payment.abandoned"}:
            target = (
                PaymentIntent.Status.FAILED
                if event.event_type == "payment.failed"
                else PaymentIntent.Status.ABANDONED
            )
            intent.status = target
            intent.safe_result_code = event.event_type.replace(".", "_")
            intent.last_provider_event_at = event.occurred_at
            intent.save(
                update_fields=(
                    "status",
                    "safe_result_code",
                    "last_provider_event_at",
                    "updated_at",
                )
            )
            PaymentAttempt.objects.create(
                registration=registration,
                organization_id=registration.organization_id,
                edition_id=registration.edition_id,
                provider=provider.code,
                provider_reference=event.remote_event_id,
                idempotency_key=uuid5(
                    PAYMENT_EVENT_NAMESPACE,
                    f"{provider.id}:{event.remote_event_id}",
                ),
                amount_minor=event.amount_minor,
                currency=event.currency,
                status=PaymentAttempt.Status.FAILED,
                occurred_at=event.occurred_at,
                safe_result_code=intent.safe_result_code,
            )
            outcome = PaymentWebhookReceipt.Outcome.APPLIED
            result_code = intent.safe_result_code
        else:
            _open_payment_exception(
                provider=provider,
                intent=intent,
                kind=PaymentException.Kind.OUT_OF_ORDER,
                summary="Provider sent an unsupported payment state.",
                now=now,
            )
            outcome = PaymentWebhookReceipt.Outcome.EXCEPTION
            result_code = "unsupported_payment_event"
        return PaymentWebhookReceipt.objects.create(
            provider_account=provider,
            organization_id=provider.organization_id,
            remote_event_id=event.remote_event_id,
            payload_digest=payload_digest,
            signature_timestamp=signed_at,
            received_at=now,
            outcome=outcome,
            safe_result_code=result_code,
            payment_intent=intent,
        )


def resolve_payment_exception(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    exception_id: UUID,
    reason: str,
    correlation_id: UUID,
) -> PaymentException:
    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_FINANCE,
        organization_id=organization_id,
        edition_id=edition_id,
        operation="registration.payment_exception.resolve",
        target_type="registration.payment_exception",
        target_id=exception_id,
        correlation_id=correlation_id,
        source_channel="api",
    )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError(
            "Resolving a payment exception requires a reason.",
            code="payment_exception_reason_required",
        )
    with transaction.atomic():
        item = PaymentException.objects.select_for_update().get(
            id=exception_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if item.status == PaymentException.Status.RESOLVED:
            return item
        item.status = PaymentException.Status.RESOLVED
        item.resolved_at = timezone.now()
        item.resolved_by_id = actor.id
        item.resolution_reason = normalized_reason
        item.save(
            update_fields=(
                "status",
                "resolved_at",
                "resolved_by_id",
                "resolution_reason",
                "updated_at",
            )
        )
        append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_FINANCE,
                operation="registration.payment_exception.resolve",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.payment_exception",
                target_id=item.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="payment_exception_resolved",
                obligations=obligations,
                changed_fields=("payment_exception",),
                source_channel="api",
            )
        )
        return item
