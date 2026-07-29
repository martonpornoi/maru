from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent
from maru.participation.models import ParticipationCapacity
from maru.registration.availability import assess_product_availability
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Entitlement,
    PaymentAttempt,
    Registration,
    RegistrationAdjustment,
    RegistrationQuestion,
)
from maru.registration.services import (
    confirm_demo_payment,
    extend_payment_deadline,
    process_registration_lifecycle,
    submit_registration,
    waive_registration_payment,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _registration_world(
    *,
    capacity: int = 10,
    product_capacity: int = 10,
    price_minor: int = 12_000,
    payment_window_minutes: int = 60,
    product_values: dict[str, object] | None = None,
):
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        capacity=capacity,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
        default_payment_window_minutes=payment_window_minutes,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Name on badge",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print the attendee credential.",
    )
    values: dict[str, object] = {
        "configuration": configuration,
        "code": "admission",
        "name": "Convention admission",
        "price_minor": price_minor,
        "capacity": product_capacity,
        "position": 10,
        "entitlement_code": "event-admission",
        "entitlement_name": "Event admission",
    }
    values.update(product_values or {})
    product = AdmissionProduct.objects.create(**values)
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Lifecycle test setup reviewed."
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
    return edition, configuration, product, now


def _register(
    *,
    edition,
    product: AdmissionProduct,
    account=None,
    now=None,
) -> Registration:
    attendee = account or AccountFactory()
    ParticipationFactory(account=attendee, edition=edition)
    return submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers={"badge-name": attendee.display_name or "Attendee"},
        correlation_id=uuid4(),
        now=now,
    )


def test_volunteer_offer_and_sales_windows_are_explainable() -> None:
    edition, _configuration, product, now = _registration_world(
        product_values={
            "sales_open_at": timezone.now() - timedelta(hours=1),
            "sales_close_at": timezone.now() + timedelta(hours=1),
            "required_capacity_codes": ["volunteer.accepted"],
            "eligibility_explanation": (
                "Available to accepted volunteers before public registration."
            ),
        }
    )
    visitor = AccountFactory()
    visitor_participation = ParticipationFactory(account=visitor, edition=edition)
    volunteer = AccountFactory()
    volunteer_participation = ParticipationFactory(account=volunteer, edition=edition)
    ParticipationCapacityFactory(
        participation=volunteer_participation,
        code="volunteer.accepted",
        status=ParticipationCapacity.Status.ACTIVE,
    )

    anonymous = assess_product_availability(product=product, account=None, at=now)
    ordinary = assess_product_availability(product=product, account=visitor, at=now)
    eligible = assess_product_availability(product=product, account=volunteer, at=now)

    assert anonymous.code == "product_sign_in_required"
    assert ordinary.code == "product_capacity_required"
    assert eligible.code == "available"
    assert eligible.selectable is True
    assert visitor_participation.id != volunteer_participation.id


def test_product_availability_explains_hidden_windows_and_full_without_waiting() -> (
    None
):
    edition, _configuration, product, now = _registration_world(
        capacity=1,
        product_capacity=1,
    )
    product.status = AdmissionProduct.Status.HIDDEN
    assert (
        assess_product_availability(product=product, account=None, at=now).code
        == "product_hidden"
    )

    product.status = AdmissionProduct.Status.AVAILABLE
    product.sales_open_at = now + timedelta(minutes=1)
    assert (
        assess_product_availability(product=product, account=None, at=now).code
        == "product_sales_not_open"
    )

    product.sales_open_at = None
    product.sales_close_at = now
    assert (
        assess_product_availability(product=product, account=None, at=now).code
        == "product_sales_closed"
    )

    product.sales_close_at = None
    _register(edition=edition, product=product, now=now)
    product.waitlist_enabled = False
    full = assess_product_availability(product=product, account=None, at=now)
    assert full.code == "capacity_reached"
    assert full.selectable is False


def test_capacity_uses_waitlist_then_fifo_offer_after_payment_expiry() -> None:
    edition, _configuration, product, now = _registration_world(
        capacity=1,
        product_capacity=1,
        payment_window_minutes=30,
    )
    reserved = _register(edition=edition, product=product, now=now)
    waiting = _register(
        edition=edition,
        product=product,
        now=now + timedelta(minutes=1),
    )

    assert reserved.state == Registration.State.PAYMENT_PENDING
    assert reserved.payment_due_at == now + timedelta(minutes=30)
    assert waiting.state == Registration.State.WAITLISTED
    assert waiting.payment_due_at is None

    result = process_registration_lifecycle(
        edition_id=edition.id,
        now=now + timedelta(minutes=31),
    )

    reserved.refresh_from_db()
    waiting.refresh_from_db()
    assert result.expired == 1
    assert result.promoted == 1
    assert reserved.state == Registration.State.EXPIRED
    assert waiting.state == Registration.State.PAYMENT_PENDING
    assert waiting.offered_at == now + timedelta(minutes=31)
    assert waiting.payment_due_at == now + timedelta(minutes=61)
    assert RegistrationAdjustment.objects.filter(
        registration=reserved,
        kind=RegistrationAdjustment.Kind.PAYMENT_EXPIRED,
    ).exists()
    assert RegistrationAdjustment.objects.filter(
        registration=waiting,
        kind=RegistrationAdjustment.Kind.WAITLIST_PROMOTED,
    ).exists()
    assert DomainEvent.objects.filter(
        aggregate_id=waiting.id,
        event_name="registration.waitlist.offered.v1",
    ).exists()


def test_payment_deadline_can_be_extended_only_as_a_reasoned_exception() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_exceptions",
    )
    new_deadline = now + timedelta(days=3)

    updated = extend_payment_deadline(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=operator,
        new_deadline=new_deadline,
        reason="Attendee documented a bank-provider outage.",
        correlation_id=uuid4(),
        now=now + timedelta(minutes=10),
    )

    assert updated.payment_due_at == new_deadline
    adjustment = RegistrationAdjustment.objects.get(registration=registration)
    assert adjustment.previous_deadline == now + timedelta(minutes=60)
    assert adjustment.new_deadline == new_deadline
    assert adjustment.reason == "Attendee documented a bank-provider outage."
    assert AuditEvent.objects.filter(
        target_id=registration.id,
        operation="registration.payment_deadline.change",
    ).exists()


def test_payment_waiver_is_not_recorded_as_provider_payment() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_exceptions",
    )

    waived = waive_registration_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=operator,
        reason="Approved volunteer complimentary admission.",
        correlation_id=uuid4(),
        now=now + timedelta(minutes=5),
    )

    assert waived.state == Registration.State.CONFIRMED
    assert waived.confirmation_basis == Registration.ConfirmationBasis.WAIVER
    assert not PaymentAttempt.objects.filter(registration=waived).exists()
    assert Entitlement.objects.filter(registration=waived).exists()
    assert RegistrationAdjustment.objects.filter(
        registration=waived,
        kind=RegistrationAdjustment.Kind.PAYMENT_WAIVED,
        amount_minor=product.price_minor,
    ).exists()


def test_demo_payment_rejects_a_late_reservation() -> None:
    edition, _configuration, product, now = _registration_world(
        payment_window_minutes=30
    )
    registration = _register(edition=edition, product=product, now=now)

    with pytest.raises(ValidationError) as error:
        confirm_demo_payment(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=registration.account,
            registration_id=registration.id,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            now=now + timedelta(minutes=31),
        )

    assert error.value.code == "registration_payment_deadline_passed"
    assert not PaymentAttempt.objects.filter(registration=registration).exists()


def test_inactive_account_open_registration_is_cancelled() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    registration.account.is_active = False
    registration.account.save(update_fields=("is_active",))

    result = process_registration_lifecycle(edition_id=edition.id, now=now)

    registration.refresh_from_db()
    assert result.inactive_cancelled == 1
    assert registration.state == Registration.State.CANCELLED
    assert registration.cancelled_at == now


def test_waitlist_closes_without_requesting_payment_after_registration_ends() -> None:
    edition, configuration, product, now = _registration_world(
        capacity=1,
        product_capacity=1,
    )
    _register(edition=edition, product=product, now=now)
    waiting = _register(
        edition=edition,
        product=product,
        now=now + timedelta(minutes=1),
    )

    result = process_registration_lifecycle(
        edition_id=edition.id,
        now=configuration.closes_at,
    )

    waiting.refresh_from_db()
    assert result.closed_waitlist_cancelled == 1
    assert result.promoted == 0
    assert waiting.state == Registration.State.CANCELLED
    assert waiting.payment_due_at is None


def test_public_definition_and_reconciliation_are_purpose_specific() -> None:
    edition, _configuration, product, now = _registration_world()
    provider_registration = _register(edition=edition, product=product, now=now)
    confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=provider_registration.account,
        registration_id=provider_registration.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        now=now + timedelta(minutes=1),
    )
    _register(
        edition=edition,
        product=product,
        now=now + timedelta(minutes=2),
    )
    waived_registration = _register(
        edition=edition,
        product=product,
        now=now + timedelta(minutes=3),
    )
    exception_operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=exception_operator,
        capability_code="registration.manage_exceptions",
    )
    waive_registration_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=waived_registration.id,
        actor=exception_operator,
        reason="Approved synthetic complimentary admission.",
        correlation_id=uuid4(),
        now=now + timedelta(minutes=4),
    )
    finance = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=finance,
        capability_code="registration.view_payment_summary",
    )
    public_client = APIClient()
    finance_client = APIClient()
    finance_client.force_authenticate(finance)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"

    editions = public_client.get("/api/v1/public/editions")
    definition = public_client.get(f"/api/v1/public/editions/{edition.id}/registration")
    reconciliation = finance_client.get(f"{base}/registration/reconciliation")

    assert editions.status_code == 200
    listed_edition = next(
        item for item in editions.json() if item["edition_id"] == str(edition.id)
    )
    assert listed_edition["registration_api_path"].endswith("/registration")
    assert definition.status_code == 200
    assert definition.json()["configuration_version"] == 1
    assert definition.json()["products"][0]["availability_code"] == "available"
    assert reconciliation.status_code == 200
    product_summary = reconciliation.json()["products"][0]
    assert product_summary["provider_paid"] == 1
    assert product_summary["provider_paid_minor"] == product.price_minor
    assert product_summary["payment_pending"] == 1
    assert product_summary["waived"] == 1
    assert product_summary["waived_minor"] == product.price_minor


def test_exception_and_reconciliation_apis_deny_ungranted_accounts() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    unprivileged = AccountFactory()
    client = APIClient()
    client.force_authenticate(unprivileged)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"
    initial_deadline = registration.payment_due_at

    deadline_response = client.post(
        f"{base}/registrations/{registration.id}/payment-deadline",
        {
            "new_deadline": (now + timedelta(days=2)).isoformat(),
            "reason": "This account has no exception authority.",
        },
        format="json",
    )
    waiver_response = client.post(
        f"{base}/registrations/{registration.id}/waive-payment",
        {"reason": "This account has no exception authority."},
        format="json",
    )
    reconciliation_response = client.get(f"{base}/registration/reconciliation")

    assert deadline_response.status_code == 403
    assert waiver_response.status_code == 403
    assert reconciliation_response.status_code == 403
    registration.refresh_from_db()
    assert registration.state == Registration.State.PAYMENT_PENDING
    assert registration.payment_due_at == initial_deadline
    assert not RegistrationAdjustment.objects.filter(registration=registration).exists()


def test_exception_apis_apply_and_explain_invalid_or_missing_targets() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_exceptions",
    )
    client = APIClient()
    client.force_authenticate(operator)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"
    registration_path = f"{base}/registrations/{registration.id}"
    reason = "Attendee documented a provider outage."

    changed = client.post(
        f"{registration_path}/payment-deadline",
        {
            "new_deadline": (now + timedelta(days=2)).isoformat(),
            "reason": reason,
        },
        format="json",
    )
    waived = client.post(
        f"{registration_path}/waive-payment",
        {"reason": "Approved complimentary admission."},
        format="json",
    )
    invalid_deadline = client.post(
        f"{registration_path}/payment-deadline",
        {
            "new_deadline": (now + timedelta(days=3)).isoformat(),
            "reason": reason,
        },
        format="json",
    )
    invalid_waiver = client.post(
        f"{registration_path}/waive-payment",
        {"reason": "Cannot waive a registration twice."},
        format="json",
    )
    missing_id = uuid4()
    missing_deadline = client.post(
        f"{base}/registrations/{missing_id}/payment-deadline",
        {
            "new_deadline": (now + timedelta(days=3)).isoformat(),
            "reason": reason,
        },
        format="json",
    )
    missing_waiver = client.post(
        f"{base}/registrations/{missing_id}/waive-payment",
        {"reason": "The target does not exist."},
        format="json",
    )

    assert changed.status_code == 200
    assert waived.status_code == 200
    assert waived.json()["confirmation_basis"] == "waiver"
    assert invalid_deadline.status_code == 400
    assert invalid_waiver.status_code == 400
    assert invalid_deadline.json()["code"] == "invalid_payment_deadline_change"
    assert invalid_waiver.json()["code"] == "invalid_payment_waiver"
    assert missing_deadline.status_code == 404
    assert missing_waiver.status_code == 404


def test_lifecycle_command_dry_run_reports_candidates_without_mutation() -> None:
    edition, _configuration, product, now = _registration_world(
        payment_window_minutes=30
    )
    registration = _register(
        edition=edition,
        product=product,
        now=now - timedelta(hours=1),
    )
    output = StringIO()

    call_command(
        "registration_lifecycle",
        "--dry-run",
        "--edition",
        str(edition.id),
        stdout=output,
    )

    registration.refresh_from_db()
    assert "1 would expire" in output.getvalue()
    assert "1 total state changes" in output.getvalue()
    assert registration.state == Registration.State.PAYMENT_PENDING


def test_database_rejects_silent_adjustment_rewrite() -> None:
    edition, _configuration, product, now = _registration_world()
    registration = _register(edition=edition, product=product, now=now)
    adjustment = RegistrationAdjustment.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind=RegistrationAdjustment.Kind.PAYMENT_DEADLINE_CHANGED,
        previous_deadline=registration.payment_due_at,
        new_deadline=registration.payment_due_at + timedelta(hours=1),
        actor_kind="account",
        actor_id=registration.account_id,
        reason="Synthetic append-only evidence.",
        occurred_at=now,
    )

    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationAdjustment.objects.filter(id=adjustment.id).update(
            reason="Silently rewritten"
        )
