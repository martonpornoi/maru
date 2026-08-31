import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.registration.finance import (
    approve_financial_operation,
    propose_financial_operation,
    reconcile_provider_settlement,
)
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Entitlement,
    FinancialLedgerEntry,
    FinancialOperation,
    PaymentAttempt,
    PaymentException,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentWebhookReceipt,
    ReceiptRecord,
    Registration,
    RegistrationAdjustment,
    RegistrationLifecycleRun,
    RegistrationQuestion,
    RegistrationTimelineEntry,
    SettlementAllocation,
    SettlementBatch,
)
from maru.registration.payments import (
    ADAPTERS,
    HostedCheckout,
    VerifiedPaymentEvent,
    create_payment_intent,
    parse_verified_payment_event,
    reconcile_verified_payment_event,
    resolve_payment_exception,
)
from maru.registration.services import submit_registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


class FakeHostedAdapter:
    def create_checkout(self, *, provider, intent, return_url):
        assert provider.enabled
        assert return_url.startswith("https://")
        return HostedCheckout(
            provider_reference=f"remote-{intent.id}",
            checkout_url=f"https://checkout.example/{intent.id}",
            expires_at=intent.expires_at,
        )


def _payment_world(*, payment_minutes: int = 60):
    edition = EventEditionFactory()
    now = timezone.now()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
        default_payment_window_minutes=payment_minutes,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Badge name",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print a credential.",
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="weekend",
        name="Weekend",
        price_minor=10_000,
        capacity=100,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed."
    configuration.activated_at = now
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )
    attendee = AccountFactory()
    ParticipationFactory(account=attendee, edition=edition)
    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers={"badge-name": "Tavi"},
        correlation_id=uuid4(),
        now=now,
    )
    provider = PaymentProviderAccount.objects.create(
        organization=edition.organization,
        code="synthetic",
        display_name="Synthetic hosted payments",
        adapter="synthetic_test",
        api_base_url="https://payments.example",
        credential_env_var="SYNTHETIC_PAYMENT_KEY",
        webhook_secret_env_var="SYNTHETIC_WEBHOOK_SECRET",
        enabled=True,
    )
    return edition, attendee, registration, provider, now


def _event(
    *,
    intent: PaymentIntent,
    event_type: str,
    event_id: str,
    amount_minor: int | None = None,
    currency: str | None = None,
    occurred_at=None,
) -> VerifiedPaymentEvent:
    return VerifiedPaymentEvent(
        remote_event_id=event_id,
        provider_reference=intent.provider_reference,
        event_type=event_type,
        amount_minor=amount_minor if amount_minor is not None else intent.amount_minor,
        currency=currency or intent.currency,
        occurred_at=occurred_at or timezone.now(),
    )


def test_hosted_checkout_webhook_refund_dispute_and_settlement(monkeypatch) -> None:
    edition, _attendee, registration, provider, now = _payment_world()
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/payment-return",
        now=now,
    )
    assert intent.status == PaymentIntent.Status.CHECKOUT_READY
    assert (
        create_payment_intent(
            registration=registration,
            provider_account_id=provider.id,
            idempotency_key=intent.idempotency_key,
            return_url="https://register.example/payment-return",
            now=now,
        )
        == intent
    )

    paid_event = _event(
        intent=intent,
        event_type="payment.succeeded",
        event_id="evt-paid",
        occurred_at=now + timedelta(minutes=1),
    )
    receipt = reconcile_verified_payment_event(
        provider=provider,
        event=paid_event,
        signed_at=now,
        payload_digest="a" * 64,
        correlation_id=uuid4(),
        received_at=now + timedelta(minutes=1),
    )
    assert receipt.outcome == "applied"
    registration.refresh_from_db()
    assert registration.state == Registration.State.CONFIRMED
    payment_entry = FinancialLedgerEntry.objects.get(
        registration=registration,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
    )
    assert ReceiptRecord.objects.filter(ledger_entry=payment_entry).exists()
    assert (
        reconcile_verified_payment_event(
            provider=provider,
            event=paid_event,
            signed_at=now,
            payload_digest="a" * 64,
            correlation_id=uuid4(),
        ).id
        == receipt.id
    )

    proposer = AccountFactory()
    approver = AccountFactory()
    for actor in (proposer, approver):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=actor,
            capability_code="registration.manage_finance",
        )
    operation = propose_financial_operation(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=proposer,
        kind=FinancialOperation.Kind.REFUND,
        amount_minor=2_000,
        reason="Attendee requested a partial refund.",
        correlation_id=uuid4(),
    )
    operation = approve_financial_operation(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        operation_id=operation.id,
        actor=approver,
        reason="Refund policy permits this amount.",
        correlation_id=uuid4(),
    )
    assert operation.status == FinancialOperation.Status.PROVIDER_PENDING
    refunded = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.refunded",
            event_id="evt-refund",
            amount_minor=2_000,
        ),
        signed_at=now,
        payload_digest="b" * 64,
        correlation_id=uuid4(),
    )
    assert refunded.safe_result_code == "refund_reconciled"
    operation.refresh_from_db()
    assert operation.status == FinancialOperation.Status.COMPLETED
    refund_entry = FinancialLedgerEntry.objects.get(
        operation=operation,
        kind=FinancialLedgerEntry.Kind.REFUND,
    )

    disputed = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.disputed",
            event_id="evt-dispute",
            amount_minor=1_000,
        ),
        signed_at=now,
        payload_digest="c" * 64,
        correlation_id=uuid4(),
    )
    assert disputed.outcome == "exception"
    dispute_entry = FinancialLedgerEntry.objects.get(provider_reference="evt-dispute")
    assert PaymentException.objects.filter(
        kind=PaymentException.Kind.DISPUTE_REVIEW
    ).exists()

    batch = reconcile_provider_settlement(
        actor=approver,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account_id=provider.id,
        provider_reference="settlement-1",
        currency="EUR",
        gross_minor=10_000,
        fee_minor=500,
        refund_minor=2_000,
        dispute_minor=1_000,
        net_minor=6_500,
        settled_at=now + timedelta(days=2),
        ledger_entry_ids=(payment_entry.id, refund_entry.id, dispute_entry.id),
        reason="Matched to the synthetic provider report.",
        correlation_id=uuid4(),
    )
    assert batch.status == "reconciled"
    assert SettlementAllocation.objects.filter(settlement=batch).count() == 3
    with pytest.raises(IntegrityError), transaction.atomic():
        SettlementBatch.objects.filter(id=batch.id).update(status="exception")
    with pytest.raises(IntegrityError), transaction.atomic():
        FinancialLedgerEntry.objects.filter(id=payment_entry.id).update(amount_minor=1)


def test_provider_webhook_verification_and_exception_paths(monkeypatch) -> None:
    edition, _attendee, registration, provider, now = _payment_world()
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    monkeypatch.setenv("SYNTHETIC_WEBHOOK_SECRET", "webhook-secret")
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/return",
        now=now,
    )
    payload = {
        "event_id": "signed-event",
        "payment_intent_id": intent.provider_reference,
        "type": "payment.failed",
        "amount_minor": 10_000,
        "currency": "EUR",
        "occurred_at": now.isoformat(),
    }
    body = json.dumps(payload).encode()
    timestamp = str(int(now.timestamp()))
    signature = hmac.new(
        b"webhook-secret",
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    parsed, signed_at, digest = parse_verified_payment_event(
        provider=provider,
        body=body,
        signature=f"sha256={signature}",
        timestamp=timestamp,
        now=now,
    )
    assert parsed.event_type == "payment.failed"
    assert digest == hashlib.sha256(body).hexdigest()
    assert (
        reconcile_verified_payment_event(
            provider=provider,
            event=parsed,
            signed_at=signed_at,
            payload_digest=digest,
            correlation_id=uuid4(),
        ).safe_result_code
        == "payment_failed"
    )
    with pytest.raises(ValidationError, match="signature"):
        parse_verified_payment_event(
            provider=provider,
            body=body,
            signature="invalid",
            timestamp=timestamp,
            now=now,
        )
    with pytest.raises(ValidationError, match="replay"):
        parse_verified_payment_event(
            provider=provider,
            body=body,
            signature=signature,
            timestamp=timestamp,
            now=now + timedelta(minutes=6),
        )

    for suffix, amount, currency, expected in (
        ("amount", 9_999, "EUR", "amount_mismatch"),
        ("currency", 10_000, "USD", "currency_mismatch"),
    ):
        other_edition, _, other_registration, other_provider, other_now = (
            _payment_world()
        )
        monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
        other_intent = create_payment_intent(
            registration=other_registration,
            provider_account_id=other_provider.id,
            idempotency_key=uuid4(),
            return_url="https://register.example/return",
            now=other_now,
        )
        result = reconcile_verified_payment_event(
            provider=other_provider,
            event=_event(
                intent=other_intent,
                event_type="payment.succeeded",
                event_id=f"evt-{suffix}",
                amount_minor=amount,
                currency=currency,
            ),
            signed_at=other_now,
            payload_digest=suffix * 8,
            correlation_id=uuid4(),
        )
        assert result.safe_result_code == expected
        assert other_edition.id != edition.id


def test_identified_payment_intent_requires_exact_registration_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an incompatible retained intent without writing webhook evidence."""
    now = timezone.now()
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="retained-payment",
        name="Retained payment admission",
        price_minor=10_000,
        capacity=100,
        position=10,
        entitlement_code="retained-payment",
        entitlement_name="Retained payment admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Retained payment fixture reviewed."
    configuration.activated_at = now
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )
    attendee = AccountFactory()
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=ParticipationFactory(account=attendee, edition=edition),
        account=attendee,
        configuration=configuration,
        product=product,
        reference="RETAINED-PAYMENT",
        state=Registration.State.PAYMENT_PENDING,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=now,
        payment_due_at=now + timedelta(hours=1),
    )
    provider = PaymentProviderAccount.objects.create(
        organization=edition.organization,
        code="retained-provider",
        display_name="Retained hosted payments",
        adapter="synthetic_test",
        api_base_url="https://payments.example",
        credential_env_var="RETAINED_PAYMENT_KEY",
        webhook_secret_env_var="RETAINED_WEBHOOK_SECRET",
        enabled=True,
    )
    intent = PaymentIntent.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account=provider,
        idempotency_key=uuid4(),
        amount_minor=product.price_minor,
        currency=configuration.currency,
        status=PaymentIntent.Status.CHECKOUT_READY,
        provider_reference="retained-payment-intent",
        checkout_url="https://payments.example/retained-checkout",
        expires_at=now + timedelta(hours=1),
    )
    ledger_entry = FinancialLedgerEntry.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account=provider,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
        direction=FinancialLedgerEntry.Direction.INFLOW,
        amount_minor=product.price_minor,
        currency=configuration.currency,
        occurred_at=now,
        provider_reference="retained-receipt-payment",
        safe_description="Hidden retained payment evidence",
    )
    receipt_record = ReceiptRecord.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        ledger_entry=ledger_entry,
        kind=ReceiptRecord.Kind.RECEIPT,
        document_number="RETAINED-RECEIPT",
        issued_at=now,
        amount_minor=product.price_minor,
        currency=configuration.currency,
        description_snapshot="Hidden retained receipt description",
    )
    monkeypatch.setattr(
        "maru.registration.api.settings.MARU_PAYMENT_RETURN_ORIGINS",
        ["https://register.example"],
    )
    before = {
        "receipts": PaymentWebhookReceipt.objects.count(),
        "exceptions": PaymentException.objects.count(),
        "attempts": PaymentAttempt.objects.count(),
        "ledger": FinancialLedgerEntry.objects.count(),
        "receipt_records": ReceiptRecord.objects.count(),
        "entitlements": Entitlement.objects.filter(registration=registration).count(),
        "timeline": RegistrationTimelineEntry.objects.filter(
            registration=registration
        ).count(),
        "audits": AuditEvent.objects.filter(event_edition_id=edition.id).count(),
        "events": DomainEvent.objects.filter(event_edition_id=edition.id).count(),
        "outbox": OutboxMessage.objects.filter(
            event__event_edition_id=edition.id
        ).count(),
    }
    client = APIClient()
    client.force_authenticate(attendee)
    registration_base = (
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/"
        f"registration/me/{registration.id}"
    )

    create_response = client.post(
        f"{registration_base}/payment-intents",
        {
            "provider_account_id": provider.id,
            "idempotency_key": uuid4(),
            "return_url": "https://register.example/payment-return",
        },
        format="json",
    )
    status_response = client.get(f"{registration_base}/payment-intents/{intent.id}")
    with CaptureQueriesContext(connection) as captured:
        receipt_response = client.get(f"{registration_base}/receipts")
    with pytest.raises(ValidationError) as create_error:
        create_payment_intent(
            registration=registration,
            provider_account_id=provider.id,
            idempotency_key=uuid4(),
            return_url="https://register.example/payment-return",
            now=now,
        )

    with pytest.raises(ValidationError) as raised:
        reconcile_verified_payment_event(
            provider=provider,
            event=_event(
                intent=intent,
                event_type="payment.succeeded",
                event_id="retained-payment-event",
                occurred_at=now + timedelta(minutes=1),
            ),
            signed_at=now,
            payload_digest="f" * 64,
            correlation_id=uuid4(),
            received_at=now + timedelta(minutes=1),
        )

    assert create_response.status_code == 404
    assert status_response.status_code == 404
    assert receipt_response.status_code == 404
    assert receipt_record.document_number.encode() not in receipt_response.content
    assert registration.reference.encode() not in receipt_response.content
    assert not any(
        "registration_receiptrecord" in query["sql"].lower()
        for query in captured.captured_queries
    )
    assert create_error.value.code == "payment_intent_scope_unavailable"
    assert raised.value.code == "payment_webhook_scope_unavailable"
    registration.refresh_from_db()
    intent.refresh_from_db()
    assert registration.state == Registration.State.PAYMENT_PENDING
    assert registration.aggregate_version == 1
    assert intent.status == PaymentIntent.Status.CHECKOUT_READY
    assert intent.safe_result_code == ""
    assert intent.last_provider_event_at is None
    assert {
        "receipts": PaymentWebhookReceipt.objects.count(),
        "exceptions": PaymentException.objects.count(),
        "attempts": PaymentAttempt.objects.count(),
        "ledger": FinancialLedgerEntry.objects.count(),
        "receipt_records": ReceiptRecord.objects.count(),
        "entitlements": Entitlement.objects.filter(registration=registration).count(),
        "timeline": RegistrationTimelineEntry.objects.filter(
            registration=registration
        ).count(),
        "audits": AuditEvent.objects.filter(event_edition_id=edition.id).count(),
        "events": DomainEvent.objects.filter(event_edition_id=edition.id).count(),
        "outbox": OutboxMessage.objects.filter(
            event__event_edition_id=edition.id
        ).count(),
    } == before


def test_unknown_late_unsupported_and_payment_exception_resolution(
    monkeypatch,
) -> None:
    edition, _attendee, registration, provider, now = _payment_world(payment_minutes=15)
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/return",
        now=now,
    )
    unknown = reconcile_verified_payment_event(
        provider=provider,
        event=VerifiedPaymentEvent(
            remote_event_id="unknown",
            provider_reference="not-local",
            event_type="payment.succeeded",
            amount_minor=10_000,
            currency="EUR",
            occurred_at=now,
        ),
        signed_at=now,
        payload_digest="d" * 64,
        correlation_id=uuid4(),
    )
    assert unknown.safe_result_code == "unknown_payment_intent"
    late = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.succeeded",
            event_id="late",
            occurred_at=now + timedelta(minutes=16),
        ),
        signed_at=now,
        payload_digest="e" * 64,
        correlation_id=uuid4(),
    )
    assert late.safe_result_code == "late_success"

    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_finance",
    )
    item = PaymentException.objects.filter(
        edition_id=edition.id,
        status=PaymentException.Status.OPEN,
    ).first()
    assert item is not None
    resolved = resolve_payment_exception(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        exception_id=item.id,
        reason="Reviewed against provider dashboard.",
        correlation_id=uuid4(),
    )
    assert resolved.status == PaymentException.Status.RESOLVED


def test_checkout_failure_and_finance_dual_control_guards(monkeypatch) -> None:
    edition, _attendee, registration, provider, now = _payment_world()
    monkeypatch.delitem(ADAPTERS, "synthetic_test", raising=False)
    with pytest.raises(ValidationError, match="adapter"):
        create_payment_intent(
            registration=registration,
            provider_account_id=provider.id,
            idempotency_key=uuid4(),
            return_url="https://register.example/return",
            now=now,
        )
    assert PaymentException.objects.filter(
        kind=PaymentException.Kind.PROVIDER_UNAVAILABLE
    ).exists()

    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_finance",
    )
    operation = propose_financial_operation(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=operator,
        kind=FinancialOperation.Kind.CANCEL,
        amount_minor=0,
        reason="Attendee requested cancellation.",
        correlation_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="different"):
        approve_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            operation_id=operation.id,
            actor=operator,
            reason="Self approval is prohibited.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="totals"):
        reconcile_provider_settlement(
            actor=operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            provider_account_id=provider.id,
            provider_reference="bad-settlement",
            currency="EUR",
            gross_minor=10,
            fee_minor=1,
            refund_minor=0,
            dispute_minor=0,
            net_minor=10,
            settled_at=now,
            ledger_entry_ids=(uuid4(),),
            reason="Does not balance.",
            correlation_id=uuid4(),
        )

    with pytest.raises(ValidationError, match="supported"):
        propose_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
            actor=operator,
            kind="unknown",
            amount_minor=0,
            reason="Synthetic invalid operation.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="not available yet"):
        propose_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
            actor=operator,
            kind=FinancialOperation.Kind.TRANSFER,
            amount_minor=0,
            target_account_id=uuid4(),
            reason="Transfer still needs recipient acceptance.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="do not accept"):
        propose_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
            actor=operator,
            kind=FinancialOperation.Kind.CANCEL,
            amount_minor=0,
            target_product_id=uuid4(),
            reason="Cancellation has no product target.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="refund exceeds"):
        propose_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
            actor=operator,
            kind=FinancialOperation.Kind.REFUND,
            amount_minor=1,
            reason="No provider payment exists.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="Only a refund"):
        propose_financial_operation(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
            actor=operator,
            kind=FinancialOperation.Kind.CANCEL,
            amount_minor=1,
            reason="Cancellation amount is invalid.",
            correlation_id=uuid4(),
        )


def test_approved_cancellation_revokes_entitlement_under_database_guard(
    monkeypatch,
) -> None:
    edition, _attendee, registration, provider, now = _payment_world()
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/payment-return",
        now=now,
    )
    reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.succeeded",
            event_id="evt-cancel-paid",
            occurred_at=now + timedelta(minutes=1),
        ),
        signed_at=now,
        payload_digest="f" * 64,
        correlation_id=uuid4(),
        received_at=now + timedelta(minutes=1),
    )
    entitlement = Entitlement.objects.get(registration=registration)

    proposer = AccountFactory()
    approver = AccountFactory()
    for actor in (proposer, approver):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=actor,
            capability_code="registration.manage_finance",
        )
    operation = propose_financial_operation(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=proposer,
        kind=FinancialOperation.Kind.CANCEL,
        amount_minor=0,
        reason="Attendee requested cancellation.",
        correlation_id=uuid4(),
    )
    approve_financial_operation(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        operation_id=operation.id,
        actor=approver,
        reason="Cancellation was independently verified.",
        correlation_id=uuid4(),
    )

    registration.refresh_from_db()
    entitlement.refresh_from_db()
    assert registration.state == Registration.State.CANCELLED
    assert entitlement.status == Entitlement.Status.REVOKED
    with pytest.raises(IntegrityError), transaction.atomic():
        Entitlement.objects.filter(id=entitlement.id).update(
            status=Entitlement.Status.ACTIVE
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Entitlement.objects.filter(id=entitlement.id).delete()


def test_payment_and_finance_api_workflow(monkeypatch) -> None:  # noqa: PLR0915
    edition, attendee, registration, provider, _now = _payment_world()
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    monkeypatch.setenv("SYNTHETIC_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(
        "maru.registration.api.settings.MARU_PAYMENT_RETURN_ORIGINS",
        ["https://register.example"],
    )
    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    registration_base = (
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/"
        f"registration/me/{registration.id}"
    )
    idempotency_key = uuid4()
    denied_return = attendee_client.post(
        f"{registration_base}/payment-intents",
        {
            "provider_account_id": provider.id,
            "idempotency_key": uuid4(),
            "return_url": "https://unapproved.example/payment-return",
        },
        format="json",
    )
    assert denied_return.status_code == 400
    created = attendee_client.post(
        f"{registration_base}/payment-intents",
        {
            "provider_account_id": provider.id,
            "idempotency_key": idempotency_key,
            "return_url": "https://register.example/payment-return",
        },
        format="json",
    )
    assert created.status_code == 201
    intent = PaymentIntent.objects.get(id=created.data["id"])
    repeated = attendee_client.post(
        f"{registration_base}/payment-intents",
        {
            "provider_account_id": provider.id,
            "idempotency_key": idempotency_key,
            "return_url": "https://register.example/payment-return",
        },
        format="json",
    )
    assert repeated.status_code == 200
    status_response = attendee_client.get(
        f"{registration_base}/payment-intents/{intent.id}"
    )
    assert status_response.status_code == 200
    assert status_response.data["status"] == PaymentIntent.Status.CHECKOUT_READY
    assert (
        attendee_client.get(
            f"{registration_base}/payment-intents/{uuid4()}"
        ).status_code
        == 404
    )

    webhook_url = (
        f"/api/v1/public/organizations/{edition.organization_id}/payments/"
        f"{provider.code}/webhook"
    )

    def send_provider_event(
        *,
        event_id: str,
        event_type: str,
        amount_minor: int,
    ):
        occurred_at = timezone.now()
        payload = json.dumps(
            {
                "event_id": event_id,
                "payment_intent_id": intent.provider_reference,
                "type": event_type,
                "amount_minor": amount_minor,
                "currency": "EUR",
                "occurred_at": occurred_at.isoformat(),
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(occurred_at.timestamp()))
        signature = hmac.new(
            b"webhook-secret",
            timestamp.encode() + b"." + payload,
            hashlib.sha256,
        ).hexdigest()
        return APIClient().post(
            webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_MARU_TIMESTAMP=timestamp,
            HTTP_X_MARU_SIGNATURE=f"sha256={signature}",
        )

    paid = send_provider_event(
        event_id="evt-api-paid",
        event_type="payment.succeeded",
        amount_minor=10_000,
    )
    assert paid.status_code == 200
    assert paid.data["result_code"] == "payment_reconciled"
    receipts = attendee_client.get(f"{registration_base}/receipts")
    assert receipts.status_code == 200
    assert len(receipts.data) == 1

    proposer = AccountFactory()
    approver = AccountFactory()
    for actor in (proposer, approver):
        for capability_code in (
            "registration.manage_finance",
            "registration.view_payment_summary",
        ):
            CapabilityGrantFactory(
                organization=edition.organization,
                edition=edition,
                principal=actor,
                capability_code=capability_code,
            )
    operations_url = (
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/"
        f"registrations/{registration.id}/financial-operations"
    )
    proposer_client = APIClient()
    proposer_client.force_authenticate(proposer)
    unsupported = proposer_client.post(
        operations_url,
        {
            "kind": FinancialOperation.Kind.TRANSFER,
            "target_account_id": uuid4(),
            "reason": "A transfer needs recipient acceptance.",
        },
        format="json",
    )
    assert unsupported.status_code == 400
    proposed = proposer_client.post(
        operations_url,
        {
            "kind": FinancialOperation.Kind.REFUND,
            "amount_minor": 2_000,
            "reason": "Attendee requested a partial refund.",
        },
        format="json",
    )
    assert proposed.status_code == 201
    operation_id = proposed.data["id"]
    assert proposer_client.get(operations_url).status_code == 200

    approver_client = APIClient()
    approver_client.force_authenticate(approver)
    approved = approver_client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/registration/financial-operations/"
            f"{operation_id}/approve"
        ),
        {"reason": "The refund is allowed by the published policy."},
        format="json",
    )
    assert approved.status_code == 200
    assert approved.data["status"] == FinancialOperation.Status.PROVIDER_PENDING
    refunded = send_provider_event(
        event_id="evt-api-refund",
        event_type="payment.refunded",
        amount_minor=2_000,
    )
    assert refunded.status_code == 200
    assert refunded.data["result_code"] == "refund_reconciled"

    mismatch = send_provider_event(
        event_id="evt-api-mismatch",
        event_type="payment.succeeded",
        amount_minor=9_999,
    )
    assert mismatch.status_code == 200
    assert mismatch.data["outcome"] == "exception"
    exceptions_url = (
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/"
        "registration/payment-exceptions"
    )
    exceptions = approver_client.get(exceptions_url)
    assert exceptions.status_code == 200
    exception_id = exceptions.data[0]["id"]
    resolved = approver_client.post(
        f"{exceptions_url}/{exception_id}/resolve",
        {"reason": "Compared with the provider dashboard and isolated the mismatch."},
        format="json",
    )
    assert resolved.status_code == 200
    assert resolved.data["status"] == PaymentException.Status.RESOLVED
    assert (
        approver_client.post(
            f"{exceptions_url}/{uuid4()}/resolve",
            {"reason": "The target is unavailable."},
            format="json",
        ).status_code
        == 404
    )

    entries = tuple(
        FinancialLedgerEntry.objects.filter(
            registration=registration,
            kind__in=(
                FinancialLedgerEntry.Kind.PAYMENT,
                FinancialLedgerEntry.Kind.REFUND,
            ),
        ).values_list("id", flat=True)
    )
    settlements_url = (
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/"
        "registration/settlements"
    )
    settled = approver_client.post(
        settlements_url,
        {
            "provider_account_id": provider.id,
            "provider_reference": "settlement-api-1",
            "currency": "EUR",
            "gross_minor": 10_000,
            "fee_minor": 0,
            "refund_minor": 2_000,
            "dispute_minor": 0,
            "net_minor": 8_000,
            "settled_at": timezone.now().isoformat(),
            "ledger_entry_ids": entries,
            "reason": "Provider payout reconciled to its included movements.",
        },
        format="json",
    )
    assert settled.status_code == 201
    assert approver_client.get(settlements_url).status_code == 200

    unprivileged = APIClient()
    unprivileged.force_authenticate(AccountFactory())
    assert unprivileged.get(operations_url).status_code == 403
    assert unprivileged.get(exceptions_url).status_code == 403
    assert unprivileged.get(settlements_url).status_code == 403


def test_finance_models_fail_closed_and_protect_evidence(  # noqa: PLR0915
    monkeypatch,
) -> None:
    edition, _attendee, registration, provider, now = _payment_world()
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/payment-return",
        now=now,
    )
    webhook = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.succeeded",
            event_id="evt-model-guards",
            occurred_at=now,
        ),
        signed_at=now,
        payload_digest="9" * 64,
        correlation_id=uuid4(),
        received_at=now,
    )
    ledger = FinancialLedgerEntry.objects.get(
        registration=registration,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
    )
    receipt = ReceiptRecord.objects.get(ledger_entry=ledger)
    adjustment = RegistrationAdjustment.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind=RegistrationAdjustment.Kind.PAYMENT_DEADLINE_CHANGED,
        actor_kind="system",
        reason="Synthetic immutable evidence.",
        occurred_at=now,
    )
    lifecycle_run = RegistrationLifecycleRun.objects.create(
        edition_id=edition.id,
        ran_at=now,
    )
    timeline = registration.timeline.first()
    assert timeline is not None

    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_finance",
    )
    settlement = reconcile_provider_settlement(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account_id=provider.id,
        provider_reference="settlement-model-guards",
        currency="EUR",
        gross_minor=10_000,
        fee_minor=0,
        refund_minor=0,
        dispute_minor=0,
        net_minor=10_000,
        settled_at=now,
        ledger_entry_ids=(ledger.id,),
        reason="Synthetic settlement guard coverage.",
        correlation_id=uuid4(),
    )
    allocation = SettlementAllocation.objects.get(settlement=settlement)
    with pytest.raises(ValidationError, match="unique movement"):
        reconcile_provider_settlement(
            actor=operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            provider_account_id=provider.id,
            provider_reference="duplicate-input",
            currency="EUR",
            gross_minor=20_000,
            fee_minor=0,
            refund_minor=0,
            dispute_minor=0,
            net_minor=20_000,
            settled_at=now,
            ledger_entry_ids=(ledger.id, ledger.id),
            reason="Duplicate movement input.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="do not match"):
        reconcile_provider_settlement(
            actor=operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            provider_account_id=provider.id,
            provider_reference="allocation-mismatch",
            currency="EUR",
            gross_minor=9_999,
            fee_minor=0,
            refund_minor=0,
            dispute_minor=0,
            net_minor=9_999,
            settled_at=now,
            ledger_entry_ids=(ledger.id,),
            reason="Synthetic allocation mismatch.",
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="already allocated"):
        reconcile_provider_settlement(
            actor=operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            provider_account_id=provider.id,
            provider_reference="already-allocated",
            currency="EUR",
            gross_minor=10_000,
            fee_minor=0,
            refund_minor=0,
            dispute_minor=0,
            net_minor=10_000,
            settled_at=now,
            ledger_entry_ids=(ledger.id,),
            reason="Synthetic repeated allocation.",
            correlation_id=uuid4(),
        )
    for evidence in (
        webhook,
        ledger,
        receipt,
        adjustment,
        lifecycle_run,
        settlement,
        allocation,
        timeline,
    ):
        with pytest.raises(ValidationError):
            evidence.save()
        with pytest.raises(ValidationError):
            evidence.delete()

    provider.api_base_url = "http://payments.example"
    with pytest.raises(ValidationError, match="HTTPS"):
        provider.full_clean()
    provider.api_base_url = "https://payments.example"

    wrong_scope_intent = PaymentIntent(
        registration=registration,
        organization_id=uuid4(),
        edition_id=registration.edition_id,
        provider_account=provider,
        idempotency_key=uuid4(),
        amount_minor=registration.price_minor_snapshot,
        currency=registration.currency_snapshot,
        expires_at=now + timedelta(minutes=10),
    )
    with pytest.raises(ValidationError, match="scope"):
        wrong_scope_intent.full_clean()

    same_actor_operation = FinancialOperation(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        kind=FinancialOperation.Kind.CANCEL,
        currency=registration.currency_snapshot,
        requested_by=operator,
        requested_at=now,
        request_reason="Synthetic.",
        approved_by=operator,
        approved_at=now,
        approval_reason="Invalid self approval.",
    )
    with pytest.raises(ValidationError, match="cannot approve"):
        same_actor_operation.full_clean()

    wrong_organization = OrganizationFactory()
    wrong_provider = PaymentProviderAccount.objects.create(
        organization=wrong_organization,
        code="wrong-scope",
        display_name="Wrong Scope",
        adapter="synthetic_test",
        api_base_url="https://wrong-payments.example",
        credential_env_var="WRONG_SCOPE_PAYMENT_KEY",
        webhook_secret_env_var="WRONG_SCOPE_WEBHOOK_SECRET",
        enabled=False,
    )
    wrong_ledger = FinancialLedgerEntry(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        provider_account=wrong_provider,
        kind=FinancialLedgerEntry.Kind.PAYMENT,
        direction=FinancialLedgerEntry.Direction.INFLOW,
        amount_minor=1,
        currency="EUR",
        occurred_at=now,
        safe_description="Invalid scope.",
    )
    with pytest.raises(ValidationError, match="provider scope"):
        wrong_ledger.full_clean()
    wrong_settlement = SettlementBatch(
        provider_account=wrong_provider,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        provider_reference="wrong",
        currency="EUR",
        gross_minor=0,
        fee_minor=0,
        refund_minor=0,
        dispute_minor=0,
        net_minor=0,
        settled_at=now,
        status=SettlementBatch.Status.OPEN,
        safe_result_code="invalid",
    )
    with pytest.raises(ValidationError, match="provider scope"):
        wrong_settlement.full_clean()

    wrong_receipt = ReceiptRecord(
        registration=registration,
        organization_id=uuid4(),
        edition_id=registration.edition_id,
        ledger_entry=ledger,
        kind=ReceiptRecord.Kind.RECEIPT,
        document_number="INVALID-SCOPE",
        issued_at=now,
        amount_minor=ledger.amount_minor,
        currency=ledger.currency,
        description_snapshot="Invalid.",
    )
    with pytest.raises(ValidationError, match="registration scope"):
        wrong_receipt.full_clean()

    exception = PaymentException.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account=provider,
        payment_intent=intent,
        kind=PaymentException.Kind.OUT_OF_ORDER,
        safe_summary="Synthetic protected exception.",
        opened_at=now,
    )
    operation = FinancialOperation.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        kind=FinancialOperation.Kind.CANCEL,
        currency=registration.currency_snapshot,
        requested_by=operator,
        requested_at=now,
        request_reason="Synthetic protected operation.",
    )
    with pytest.raises(ValidationError):
        exception.delete()
    with pytest.raises(ValidationError):
        operation.delete()
    assert isinstance(webhook, PaymentWebhookReceipt)


def test_payment_adapter_and_webhook_error_states_are_explicit(monkeypatch) -> None:
    edition, _attendee, registration, provider, now = _payment_world(payment_minutes=15)
    monkeypatch.setitem(ADAPTERS, "synthetic_test", FakeHostedAdapter())
    key = uuid4()
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=key,
        return_url="https://register.example/payment-return",
        now=now,
    )
    second_attendee = AccountFactory()
    ParticipationFactory(account=second_attendee, edition=edition)
    second_registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=second_attendee,
        product_id=registration.product_id,
        answers={"badge-name": "Second"},
        correlation_id=uuid4(),
        now=now,
    )
    with pytest.raises(ValidationError, match="another operation"):
        create_payment_intent(
            registration=second_registration,
            provider_account_id=provider.id,
            idempotency_key=key,
            return_url="https://register.example/payment-return",
            now=now,
        )
    with pytest.raises(ValidationError, match="expired"):
        create_payment_intent(
            registration=second_registration,
            provider_account_id=provider.id,
            idempotency_key=uuid4(),
            return_url="https://register.example/payment-return",
            now=now + timedelta(minutes=16),
        )

    paid_event = _event(
        intent=intent,
        event_type="payment.succeeded",
        event_id="evt-errors-paid",
        occurred_at=now,
    )
    reconcile_verified_payment_event(
        provider=provider,
        event=paid_event,
        signed_at=now,
        payload_digest="1" * 64,
        correlation_id=uuid4(),
        received_at=now,
    )
    with pytest.raises(ValidationError, match="different content"):
        reconcile_verified_payment_event(
            provider=provider,
            event=paid_event,
            signed_at=now,
            payload_digest="2" * 64,
            correlation_id=uuid4(),
            received_at=now,
        )
    with pytest.raises(ValidationError, match="not waiting"):
        create_payment_intent(
            registration=registration,
            provider_account_id=provider.id,
            idempotency_key=uuid4(),
            return_url="https://register.example/payment-return",
            now=now,
        )

    refund_currency = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.refunded",
            event_id="evt-refund-currency",
            amount_minor=500,
            currency="USD",
        ),
        signed_at=now,
        payload_digest="3" * 64,
        correlation_id=uuid4(),
        received_at=now,
    )
    assert refund_currency.safe_result_code == "refund_currency_mismatch"
    missing_refund = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.refunded",
            event_id="evt-refund-missing",
            amount_minor=500,
        ),
        signed_at=now,
        payload_digest="4" * 64,
        correlation_id=uuid4(),
        received_at=now,
    )
    assert missing_refund.safe_result_code == "refund_operation_missing"
    dispute_mismatch = reconcile_verified_payment_event(
        provider=provider,
        event=_event(
            intent=intent,
            event_type="payment.disputed",
            event_id="evt-dispute-mismatch",
            amount_minor=20_000,
        ),
        signed_at=now,
        payload_digest="5" * 64,
        correlation_id=uuid4(),
        received_at=now,
    )
    assert dispute_mismatch.safe_result_code == "dispute_mismatch"

    payload = json.dumps(
        {
            "event_id": "evt-parse",
            "payment_intent_id": intent.provider_reference,
            "type": "payment.succeeded",
            "amount_minor": 10_000,
            "currency": "EUR",
            "occurred_at": now.isoformat(),
        }
    ).encode()
    timestamp = str(int(now.timestamp()))
    monkeypatch.delenv("SYNTHETIC_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValidationError, match="not configured"):
        parse_verified_payment_event(
            provider=provider,
            body=payload,
            signature="invalid",
            timestamp=timestamp,
            now=now,
        )
    monkeypatch.setenv("SYNTHETIC_WEBHOOK_SECRET", "secret")
    signature = hmac.new(
        b"secret",
        timestamp.encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    with pytest.raises(ValidationError, match="payload"):
        parse_verified_payment_event(
            provider=provider,
            body=b"not-json",
            signature=hmac.new(
                b"secret",
                timestamp.encode() + b".not-json",
                hashlib.sha256,
            ).hexdigest(),
            timestamp=timestamp,
            now=now,
        )
    naive_payload = payload.replace(
        now.isoformat().encode(),
        b"2030-01-01T10:00:00",
    )
    with pytest.raises(ValidationError, match="payload"):
        parse_verified_payment_event(
            provider=provider,
            body=naive_payload,
            signature=hmac.new(
                b"secret",
                timestamp.encode() + b"." + naive_payload,
                hashlib.sha256,
            ).hexdigest(),
            timestamp=timestamp,
            now=now,
        )
    assert signature
