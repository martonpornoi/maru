from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    ConfigurationStatus,
    Entitlement,
    PaymentAttempt,
    PaymentProviderAccount,
    Registration,
    RegistrationCapacityAdjustment,
    RegistrationQuestion,
    WaitlistBatchOffer,
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


def _world(*, source_price: int):
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        capacity=1,
        capacity_ceiling=4,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
        default_payment_window_minutes=60,
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
        description="The standard convention admission.",
        price_minor=source_price,
        capacity=1,
        capacity_ceiling=4,
        position=10,
        entitlement_code="admission-default",
        entitlement_name="Default admission",
    )
    target = AdmissionProduct.objects.create(
        configuration=configuration,
        code="sponsor",
        name="Sponsor admission",
        description="A higher supporter admission tier.",
        price_minor=25_000,
        capacity=2,
        capacity_ceiling=4,
        position=20,
        entitlement_code="admission-sponsor",
        entitlement_name="Sponsor admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Commerce HTML test setup reviewed."
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
    account = AccountFactory()
    ParticipationFactory(account=account, edition=edition)
    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=account,
        product_id=product.id,
        answers={"badge-name": account.display_name or "Attendee"},
        correlation_id=uuid4(),
        now=now,
    )
    return account, registration


def _staff_location(edition) -> str:
    return reverse(
        "registration-commerce-workspace",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
        ),
    )


def test_attendee_upgrade_controls_are_owned_closed_and_demo_idempotent(
    settings,
) -> None:
    settings.DEMO_PAYMENT_ADAPTER_ENABLED = True
    edition, _configuration, source, target, now = _world(source_price=10_000)
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
    PaymentProviderAccount.objects.create(
        organization=edition.organization,
        code="hosted",
        display_name="Hosted test payments",
        adapter="unavailable_test_adapter",
        api_base_url="https://payments.example",
        credential_env_var="HTML_TEST_PAYMENT_KEY",
        webhook_secret_env_var="HTML_TEST_WEBHOOK_KEY",
        enabled=True,
    )
    client = Client()
    client.force_login(attendee)
    profile_url = reverse("public-registration-profile", args=(edition.id,))
    page = client.get(profile_url)

    assert page.status_code == 200
    assert b"Move to a higher admission tier" in page.content
    assert b"Sponsor admission" in page.content
    assert b"15000" in page.content
    assert b"Hosted test payments" not in page.content
    option = page.context["tier_replacement_options"][0]
    form = option["form"]
    command = {
        "target_product_id": form["target_product_id"].value(),
        "expected_registration_version": form["expected_registration_version"].value(),
        "idempotency_key": form["idempotency_key"].value(),
    }
    upgrade_url = reverse(
        "public-registration-tier-replacement",
        args=(edition.id,),
    )

    rejected = client.post(upgrade_url, {**command, "selected_person_id": uuid4()})
    assert rejected.status_code == 302
    assert not AdmissionTierReplacement.objects.filter(
        registration=registration
    ).exists()

    reserved = client.post(upgrade_url, command)
    assert reserved.status_code == 302
    replacement = AdmissionTierReplacement.objects.get(registration=registration)
    assert replacement.amount_due_minor == 15_000
    registration.refresh_from_db()
    assert registration.product_id == source.id
    assert Entitlement.objects.filter(
        registration=registration,
        status=Entitlement.Status.ACTIVE,
        code=source.entitlement_code,
    ).exists()

    pending_page = client.get(profile_url)
    assert b"is reserved until" in pending_page.content
    assert b"Pay with Hosted test payments" in pending_page.content
    demo_form = pending_page.context["demo_payment_form"]
    demo_key = demo_form["idempotency_key"].value()
    demo_url = reverse("public-registration-demo-payment", args=(edition.id,))
    first = client.post(demo_url, {"idempotency_key": demo_key})
    replay = client.post(demo_url, {"idempotency_key": demo_key})
    assert first.status_code == replay.status_code == 302

    registration.refresh_from_db()
    replacement.refresh_from_db()
    assert replacement.status == AdmissionTierReplacement.Status.COMPLETED
    assert registration.product_id == target.id
    active = Entitlement.objects.filter(
        registration=registration,
        status=Entitlement.Status.ACTIVE,
    )
    assert active.count() == 1
    assert active.get().code == target.entitlement_code
    assert (
        PaymentAttempt.objects.filter(
            registration=registration,
            provider="demo",
            idempotency_key=demo_key,
            amount_minor=15_000,
        ).count()
        == 1
    )

    foreign_edition = EventEditionFactory()
    assert (
        client.post(
            reverse(
                "public-registration-tier-replacement",
                args=(foreign_edition.id,),
            ),
            command,
        ).status_code
        == 404
    )
    other = AccountFactory()
    client.force_login(other)
    assert client.get(profile_url).status_code == 404


def test_staff_capacity_fifo_and_activity_html_are_scoped_and_closed() -> None:  # noqa: PLR0915
    edition, configuration, source, _target, now = _world(source_price=0)
    _account, occupied = _register(edition=edition, product=source, now=now)
    waiting = [
        _register(
            edition=edition,
            product=source,
            now=now + timedelta(minutes=offset),
        )[1]
        for offset in (1, 2, 3)
    ]
    assert occupied.state == Registration.State.CONFIRMED
    assert all(item.state == Registration.State.WAITLISTED for item in waiting)

    operator = AccountFactory(display_name="Registration operator")
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="registration.manage_exceptions",
    )
    client = Client()
    client.force_login(operator)
    location = _staff_location(edition)
    page = client.get(location)
    assert page.status_code == 200
    assert b"Registration commerce" in page.content
    assert b"FIFO order" in page.content
    assert b"4 ceiling" in page.content

    unauthorized = AccountFactory()
    client.force_login(unauthorized)
    assert client.get(location).status_code == 404
    client.force_login(operator)

    overall_form = page.context["overall_capacity_form"]
    overall_command = {
        "product_id": "",
        "new_capacity": "4",
        "expected_control_version": overall_form["expected_control_version"].value(),
        "reason": "The venue released the reviewed reserve seats.",
        "idempotency_key": overall_form["idempotency_key"].value(),
    }
    overall_url = reverse(
        "registration-commerce-adjust-overall",
        args=(edition.organization.slug, edition.series.slug, edition.slug),
    )
    rejected = client.post(overall_url, {**overall_command, "person_id": uuid4()})
    assert rejected.status_code == 302
    assert not RegistrationCapacityAdjustment.objects.exists()
    assert client.post(overall_url, overall_command).status_code == 302

    page = client.get(location)
    source_item = next(
        item for item in page.context["products"] if item["product"].id == source.id
    )
    capacity_form = source_item["capacity_form"]
    product_command = {
        "product_id": source.id,
        "new_capacity": "4",
        "expected_control_version": capacity_form["expected_control_version"].value(),
        "reason": "The default product may use all reviewed seats.",
        "idempotency_key": capacity_form["idempotency_key"].value(),
    }
    product_url = reverse(
        "registration-commerce-adjust-product",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
            source.id,
        ),
    )
    assert client.post(product_url, product_command).status_code == 302

    page = client.get(location)
    source_item = next(
        item for item in page.context["products"] if item["product"].id == source.id
    )
    batch_form = source_item["batch_form"]
    batch_command = {
        "product_id": source.id,
        "batch_size": "2",
        "expected_control_version": batch_form["expected_control_version"].value(),
        "reason": "Release exactly the next two eligible registrations.",
        "idempotency_key": batch_form["idempotency_key"].value(),
    }
    batch_url = reverse(
        "registration-commerce-offer-batch",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
            source.id,
        ),
    )
    assert client.post(batch_url, batch_command).status_code == 302
    for item in waiting:
        item.refresh_from_db()
    assert [item.state for item in waiting] == [
        Registration.State.CONFIRMED,
        Registration.State.CONFIRMED,
        Registration.State.WAITLISTED,
    ]
    assert WaitlistBatchOffer.objects.get().offered_count == 2

    final_page = client.get(location)
    assert b"Recent registration-commerce activity" in final_page.content
    assert b"Registration operator" in final_page.content
    assert b"Offered a strict FIFO waitlist batch" in final_page.content
    assert AuditEvent.objects.filter(
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        operation="registration.commerce_activity.list",
    ).exists()
    configuration.refresh_from_db()
    assert configuration.capacity == 1

    foreign = EventEditionFactory()
    foreign_product = AdmissionProduct.objects.create(
        configuration=RegistrationConfigurationFactory(edition=foreign),
        code="foreign",
        name="Foreign admission",
        price_minor=0,
        capacity=1,
        position=10,
        entitlement_code="foreign-admission",
        entitlement_name="Foreign admission",
    )
    assert (
        client.post(
            reverse(
                "registration-commerce-adjust-product",
                args=(
                    edition.organization.slug,
                    edition.series.slug,
                    edition.slug,
                    foreign_product.id,
                ),
            ),
            product_command,
        ).status_code
        == 404
    )
