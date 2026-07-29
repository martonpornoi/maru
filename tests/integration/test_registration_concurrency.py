from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from maru.participation.models import Participation
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Registration,
    RegistrationQuestion,
)
from maru.registration.services import (
    process_registration_lifecycle,
    submit_registration,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _capacity_world(*, capacity: int = 1):
    opened_at = timezone.now() - timedelta(days=2)
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=opened_at,
        closes_at=timezone.now() + timedelta(days=2),
        capacity=capacity,
        waitlist_enabled=True,
        default_payment_window_minutes=15,
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="admission",
        name="Admission",
        price_minor=10_000,
        capacity=capacity,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
        waitlist_enabled=True,
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
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Synthetic concurrency review."
    configuration.activated_at = timezone.now()
    configuration.save()
    return edition, configuration, product


def _attendee(edition):
    account = AccountFactory()
    ParticipationFactory(
        account=account,
        edition=edition,
        status=Participation.Status.PENDING,
    )
    return account


def test_simultaneous_submissions_cannot_oversubscribe_hard_capacity() -> None:
    edition, _configuration, product = _capacity_world(capacity=1)
    accounts = (_attendee(edition), _attendee(edition))
    barrier = Barrier(2)

    def submit(account_id):
        close_old_connections()
        try:
            account = type(accounts[0]).objects.get(id=account_id)
            barrier.wait(timeout=10)
            registration = submit_registration(
                organization_id=edition.organization_id,
                edition_id=edition.id,
                actor=account,
                product_id=product.id,
                answers={"badge-name": "Concurrent attendee"},
                correlation_id=uuid4(),
            )
            return registration.state
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        states = list(executor.map(submit, (account.id for account in accounts)))

    assert sorted(states) == sorted(
        (Registration.State.PAYMENT_PENDING, Registration.State.WAITLISTED)
    )
    assert (
        Registration.objects.filter(
            edition=edition,
            state__in=(
                Registration.State.PAYMENT_PENDING,
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            ),
        ).count()
        == 1
    )


def test_concurrent_lifecycle_workers_offer_one_fifo_place() -> None:
    edition, _configuration, product = _capacity_world(capacity=1)
    due_account = _attendee(edition)
    first_waiting = _attendee(edition)
    second_waiting = _attendee(edition)
    base_time = timezone.now() - timedelta(hours=2)
    due = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=due_account,
        product_id=product.id,
        answers={"badge-name": "Due attendee"},
        correlation_id=uuid4(),
        now=base_time,
    )
    first = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=first_waiting,
        product_id=product.id,
        answers={"badge-name": "First waiting attendee"},
        correlation_id=uuid4(),
        now=base_time + timedelta(seconds=1),
    )
    second = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=second_waiting,
        product_id=product.id,
        answers={"badge-name": "Second waiting attendee"},
        correlation_id=uuid4(),
        now=base_time + timedelta(seconds=2),
    )
    barrier = Barrier(2)

    def run_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return process_registration_lifecycle(
                edition_id=edition.id,
                now=timezone.now(),
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_worker(), range(2)))

    due.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert due.state == Registration.State.EXPIRED
    assert first.state == Registration.State.PAYMENT_PENDING
    assert second.state == Registration.State.WAITLISTED
    assert sum(result.promoted for result in results) == 1
