from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent
from maru.registration.commerce import (
    adjust_registration_capacity,
    authorize_registration_commerce_edition_api_scope,
    authorize_tier_replacement_api_scope,
    effective_configuration_capacity,
    effective_product_capacity,
    offer_next_waitlist_batch,
    pending_target_capacity_holds,
    registration_commerce_activity,
    reserve_admission_tier_replacement,
)
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    ConfigurationStatus,
    Entitlement,
    PaymentProviderAccount,
    Registration,
    RegistrationCapacityAdjustment,
    RegistrationCommerceCommandReceipt,
    RegistrationQuestion,
    WaitlistBatchOffer,
)
from maru.registration.payments import (
    ADAPTERS,
    HostedCheckout,
    VerifiedPaymentEvent,
    create_payment_intent,
    reconcile_verified_payment_event,
)
from maru.registration.services import confirm_demo_payment, submit_registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


class _HostedAdapter:
    def create_checkout(self, *, provider, intent, return_url):
        assert provider.enabled
        assert return_url.startswith("https://")
        return HostedCheckout(
            provider_reference=f"upgrade-{intent.id}",
            checkout_url=f"https://checkout.example/{intent.id}",
            expires_at=intent.expires_at,
        )


def _world(
    *,
    capacity: int = 2,
    capacity_ceiling: int = 5,
    source_price: int = 10_000,
    waitlist_enabled: bool = True,
):
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        capacity=capacity,
        capacity_ceiling=capacity_ceiling,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
        default_payment_window_minutes=60,
        waitlist_enabled=waitlist_enabled,
        automatic_waitlist_promotion=waitlist_enabled,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Badge name",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print the attendee credential.",
    )
    source = AdmissionProduct.objects.create(
        configuration=configuration,
        code="default",
        name="Default admission",
        price_minor=source_price,
        capacity=capacity,
        capacity_ceiling=capacity_ceiling,
        position=10,
        entitlement_code="admission-default",
        entitlement_name="Default admission",
        waitlist_enabled=waitlist_enabled,
    )
    target = AdmissionProduct.objects.create(
        configuration=configuration,
        code="sponsor",
        name="Sponsor admission",
        price_minor=25_000,
        capacity=1,
        capacity_ceiling=3,
        position=20,
        entitlement_code="admission-sponsor",
        entitlement_name="Sponsor admission",
        waitlist_enabled=waitlist_enabled,
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Commerce test setup reviewed."
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
    return edition, configuration, source, target, now


def _register(*, edition, product, now):
    attendee = AccountFactory()
    ParticipationFactory(account=attendee, edition=edition)
    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers={"badge-name": attendee.display_name or "Attendee"},
        correlation_id=uuid4(),
        now=now,
    )
    return attendee, registration


def _operator(edition):
    actor = AccountFactory(display_name="Registration lead")
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_exceptions",
    )
    return actor


def test_registration_commerce_api_preflight_is_exactly_scoped() -> None:
    edition, _configuration, source, _target, now = _world()
    attendee, registration = _register(edition=edition, product=source, now=now)

    authorize_tier_replacement_api_scope(
        actor=attendee,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
    )
    with pytest.raises(AuthorizationDenied):
        authorize_tier_replacement_api_scope(
            actor=AccountFactory(display_name="Different attendee"),
            organization_id=edition.organization_id,
            edition_id=edition.id,
            registration_id=registration.id,
        )

    operator = _operator(edition)
    authorize_registration_commerce_edition_api_scope(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    with pytest.raises(AuthorizationDenied):
        authorize_registration_commerce_edition_api_scope(
            actor=AccountFactory(display_name="Unprivileged attendee"),
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )


def test_paid_tier_replacement_charges_difference_and_swaps_one_entitlement(
    settings,
    monkeypatch,
) -> None:
    settings.DEMO_PAYMENT_ADAPTER_ENABLED = True
    edition, configuration, source, target, now = _world(
        capacity=1,
        capacity_ceiling=2,
        waitlist_enabled=False,
    )
    attendee, registration = _register(edition=edition, product=source, now=now)
    registration = confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        registration_id=registration.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        now=now + timedelta(minutes=1),
    )
    source_version = registration.aggregate_version
    source_entitlement = Entitlement.objects.get(
        registration=registration,
        status=Entitlement.Status.ACTIVE,
    )
    retry_key = uuid4()
    reserved = reserve_admission_tier_replacement(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        target_product_id=target.id,
        actor=attendee,
        expected_registration_version=source_version,
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        now=now + timedelta(minutes=2),
    )
    replay = reserve_admission_tier_replacement(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        target_product_id=target.id,
        actor=attendee,
        expected_registration_version=source_version,
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        now=now + timedelta(minutes=2),
    )

    registration.refresh_from_db()
    assert replay.replayed is True
    assert replay.replacement.id == reserved.replacement.id
    assert registration.product_id == source.id
    assert registration.aggregate_version == source_version
    assert pending_target_capacity_holds(target, at=now + timedelta(minutes=2)) == 1
    assert Entitlement.objects.get(id=source_entitlement.id).status == "active"

    provider = PaymentProviderAccount.objects.create(
        organization=edition.organization,
        code="upgrade-test",
        display_name="Upgrade test payments",
        adapter="upgrade_test",
        api_base_url="https://payments.example",
        credential_env_var="UPGRADE_TEST_PAYMENT_KEY",
        webhook_secret_env_var="UPGRADE_TEST_WEBHOOK_SECRET",
        enabled=True,
    )
    monkeypatch.setitem(ADAPTERS, "upgrade_test", _HostedAdapter())
    intent = create_payment_intent(
        registration=registration,
        provider_account_id=provider.id,
        idempotency_key=uuid4(),
        return_url="https://register.example/payment-return",
        now=now + timedelta(minutes=3),
    )
    assert intent.amount_minor == target.price_minor - source.price_minor
    assert intent.tier_replacement_id == reserved.replacement.id

    event_at = now + timedelta(minutes=4)
    receipt = reconcile_verified_payment_event(
        provider=provider,
        event=VerifiedPaymentEvent(
            remote_event_id="upgrade-paid",
            provider_reference=intent.provider_reference,
            event_type="payment.succeeded",
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            occurred_at=event_at,
        ),
        signed_at=event_at,
        payload_digest="a" * 64,
        correlation_id=uuid4(),
        received_at=event_at,
    )

    registration.refresh_from_db()
    reserved.replacement.refresh_from_db()
    assert receipt.safe_result_code == "tier_replacement_payment_reconciled"
    assert registration.product_id == target.id
    assert registration.price_minor_snapshot == target.price_minor
    assert reserved.replacement.status == AdmissionTierReplacement.Status.COMPLETED
    active = Entitlement.objects.filter(
        registration=registration,
        status=Entitlement.Status.ACTIVE,
    )
    assert active.count() == 1
    assert active.get().code == target.entitlement_code
    assert Entitlement.objects.get(id=source_entitlement.id).status == "revoked"
    assert DomainEvent.objects.filter(
        aggregate_id=reserved.replacement.id,
        event_name="registration.admission_tier_replacement.completed.v1",
    ).exists()
    assert RegistrationCommerceCommandReceipt.objects.filter(
        result_id=reserved.replacement.id,
        idempotency_key=retry_key,
    ).exists()
    configuration.refresh_from_db()
    assert configuration.capacity == 1


def test_capacity_adjustments_are_append_only_versioned_and_ceiling_bounded() -> None:
    edition, configuration, _source, target, now = _world()
    operator = _operator(edition)
    overall_key = uuid4()
    overall = adjust_registration_capacity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=operator,
        new_capacity=4,
        reason="The venue released the reviewed reserve seats.",
        expected_control_version=1,
        idempotency_key=overall_key,
        correlation_id=uuid4(),
        now=now,
    )
    replay = adjust_registration_capacity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=operator,
        new_capacity=4,
        reason="The venue released the reviewed reserve seats.",
        expected_control_version=1,
        idempotency_key=overall_key,
        correlation_id=uuid4(),
        now=now,
    )
    product = adjust_registration_capacity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=target.id,
        actor=operator,
        new_capacity=3,
        reason="Sponsor inventory was confirmed by Registration.",
        expected_control_version=2,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        now=now,
    )

    assert replay.replayed is True
    assert replay.adjustment.id == overall.adjustment.id
    assert overall.control_version == 2
    assert product.control_version == 3
    assert effective_configuration_capacity(configuration) == 4
    assert effective_product_capacity(target) == 3
    configuration.refresh_from_db()
    target.refresh_from_db()
    assert configuration.capacity == 2
    assert target.capacity == 1

    with pytest.raises(ValidationError) as ceiling_error:
        adjust_registration_capacity(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=target.id,
            actor=operator,
            new_capacity=4,
            reason="Attempt to exceed the reviewed ceiling.",
            expected_control_version=3,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            now=now,
        )
    assert ceiling_error.value.code == "registration_capacity_ceiling_exceeded"

    overall.adjustment.reason = "Silently rewritten evidence"
    with pytest.raises(ValidationError):
        overall.adjustment.save(update_fields=("reason", "updated_at"))
    with pytest.raises(DatabaseError), transaction.atomic():
        RegistrationCapacityAdjustment.objects.filter(id=overall.adjustment.id).update(
            reason="Directly rewritten evidence"
        )
    assert (
        RegistrationCapacityAdjustment.objects.get(id=overall.adjustment.id).reason
        == "The venue released the reviewed reserve seats."
    )


def test_waitlist_batch_is_strict_fifo_and_activity_is_purpose_scoped() -> None:
    edition, configuration, source, _target, now = _world(
        capacity=1,
        capacity_ceiling=4,
        source_price=0,
    )
    _register(edition=edition, product=source, now=now)
    waiting = [
        _register(
            edition=edition,
            product=source,
            now=now + timedelta(minutes=offset),
        )[1]
        for offset in (1, 2, 3)
    ]
    assert all(item.state == Registration.State.WAITLISTED for item in waiting)
    operator = _operator(edition)
    adjust_registration_capacity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=operator,
        new_capacity=4,
        reason="Two reviewed attendance places are ready for release.",
        expected_control_version=1,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        now=now + timedelta(minutes=4),
    )
    adjust_registration_capacity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=source.id,
        actor=operator,
        new_capacity=4,
        reason="The admission product now reflects the released places.",
        expected_control_version=2,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        now=now + timedelta(minutes=4),
    )
    retry_key = uuid4()
    offered = offer_next_waitlist_batch(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=source.id,
        actor=operator,
        batch_size=2,
        reason="Release exactly the next two eligible registrations.",
        expected_control_version=3,
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        now=now + timedelta(minutes=5),
    )
    replay = offer_next_waitlist_batch(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=source.id,
        actor=operator,
        batch_size=2,
        reason="Release exactly the next two eligible registrations.",
        expected_control_version=3,
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        now=now + timedelta(minutes=5),
    )

    for item in waiting:
        item.refresh_from_db()
    assert offered.offered_registration_ids == (waiting[0].id, waiting[1].id)
    assert replay.replayed is True
    assert set(replay.offered_registration_ids) == {
        waiting[0].id,
        waiting[1].id,
    }
    assert [item.state for item in waiting] == [
        Registration.State.CONFIRMED,
        Registration.State.CONFIRMED,
        Registration.State.WAITLISTED,
    ]
    batch = WaitlistBatchOffer.objects.get(id=offered.batch.id)
    assert batch.requested_size == 2
    assert batch.offered_count == 2
    assert batch.control_version == 4

    activity = registration_commerce_activity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=operator,
        correlation_id=uuid4(),
    )
    assert {item.event_name for item in activity} == {
        "registration.capacity.adjusted.v1",
        "registration.waitlist.batch_offered.v1",
    }
    batch_activity = next(
        item
        for item in activity
        if item.event_name == "registration.waitlist.batch_offered.v1"
    )
    assert batch_activity.actor_label == "Registration lead"
    assert batch_activity.target_count == 2
    assert AuditEvent.objects.filter(
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        operation="registration.commerce_activity.list",
    ).exists()
    configuration.refresh_from_db()
    assert configuration.capacity == 1


def test_waitlist_batch_replay_never_mixes_reused_keys_across_editions() -> None:
    first = _world(capacity=1, source_price=0)
    second = _world(capacity=1, source_price=0)
    operator = AccountFactory(display_name="Cross-edition registration lead")
    retry_key = uuid4()
    waiting_by_edition: list[Registration] = []

    for edition, _configuration, source, _target, now in (first, second):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=operator,
            capability_code="registration.manage_exceptions",
        )
        _register(edition=edition, product=source, now=now)
        waiting = _register(
            edition=edition,
            product=source,
            now=now + timedelta(minutes=1),
        )[1]
        waiting_by_edition.append(waiting)
        adjust_registration_capacity(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=operator,
            new_capacity=2,
            reason="Release one reviewed overall place.",
            expected_control_version=1,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            now=now + timedelta(minutes=2),
        )
        adjust_registration_capacity(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=source.id,
            actor=operator,
            new_capacity=2,
            reason="Release one reviewed product place.",
            expected_control_version=2,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            now=now + timedelta(minutes=2),
        )
        offer_next_waitlist_batch(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=source.id,
            actor=operator,
            batch_size=1,
            reason="Offer the next exact registration.",
            expected_control_version=3,
            idempotency_key=retry_key,
            correlation_id=uuid4(),
            now=now + timedelta(minutes=3),
        )

    edition, _configuration, source, _target, now = first
    replay = offer_next_waitlist_batch(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=source.id,
        actor=operator,
        batch_size=1,
        reason="Offer the next exact registration.",
        expected_control_version=3,
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        now=now + timedelta(minutes=3),
    )

    assert replay.replayed is True
    assert replay.offered_registration_ids == (waiting_by_edition[0].id,)
    assert waiting_by_edition[1].id not in replay.offered_registration_ids
