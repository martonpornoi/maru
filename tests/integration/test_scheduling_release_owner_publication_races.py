"""Real publication waits and rollback across physical and copy-disclosure owners."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from uuid import uuid4

import pytest
from django.db import transaction

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.programme.models import ProgrammeItem, ProgrammePublicRendition
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.models import SchedulingRelease, SchedulingReleasePointer
from maru.venues.models import VenueBooking, VenueProperty
from maru.venues.services import (
    cancel_venue_booking,
    select_space_for_edition,
    select_venue_for_edition,
    update_venue_property,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_scheduling_release_identity_races import (
    _observe_lock_wait,
    _worker,
)
from tests.integration.test_scheduling_release_queries import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import approve, load, publish
from tests.integration.test_scheduling_release_queries import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    world as world,  # noqa: PLC0414
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("rollback_first", [False, True])
def test_two_publications_cannot_both_advance_the_same_observed_pointer(
    review_scope, rollback_first
):
    first_approval = approve(review_scope)
    review_scope.review_request = replace(
        review_scope.review_request, idempotency_key=uuid4()
    )
    second_approval = approve(review_scope)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            first = publish(review_scope, first_approval)
            future = executor.submit(
                _worker, lambda: publish(review_scope, second_approval), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_first:
                transaction.set_rollback(True)
        if rollback_first:
            expected = future.result(timeout=12)
        else:
            with pytest.raises(SchedulingVersionConflictError):
                future.result(timeout=12)
            expected = first
    assert SchedulingRelease.objects.count() == 1
    pointer = SchedulingReleasePointer.objects.get()
    assert pointer.version == 1
    assert pointer.active_release_id == expected.object_id
    assert load(review_scope).state == "available"


def mutation(scope, kind):
    actor = Account.objects.get(id=scope.request.actor_id)
    if kind == "copy":
        item = ProgrammeItem.objects.get(id=scope.selection.item_id)
        copy = ProgrammePublicRendition.objects.filter(item=item).latest(
            "rendition_number"
        )
        return lambda: withdraw_programme_public_rendition(
            actor_id=actor.id,
            organization_id=item.organization_id,
            edition_id=item.edition_id,
            item_id=item.id,
            rendition_id=copy.id,
            expected_version=item.aggregate_version,
            reason="Synthetic concurrent disclosure withdrawal",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=scope.policy,
        )
    booking = VenueBooking.objects.get(edition_id=scope.request.edition_id)
    if kind == "booking":
        return lambda: cancel_venue_booking(
            actor=actor,
            organization_id=booking.organization_id,
            edition_id=booking.edition_id,
            space_selection_id=booking.space_selection_id,
            booking_id=booking.id,
            expected_version=booking.aggregate_version,
            reason="Synthetic concurrent physical approval cancellation",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    property_record = VenueProperty.objects.get(
        id=booking.space_selection.venue_selection.property_id
    )
    # A genuinely separate edition selects the same physical member. The shared
    # property writer must govern this release without acquiring that foreign
    # edition's pointer, regardless of which publication/mutation commits first.
    edition = EventEdition.objects.get(id=booking.edition_id)
    foreign = EventEditionFactory(
        series=edition.series, starts_on=edition.starts_on, ends_on=edition.ends_on
    )
    department = create_department_for_test(
        edition=foreign, name="Other Programme", expected_code="other-programme"
    )
    selector = AccountFactory()
    CapabilityGrantFactory(
        organization_id=foreign.organization_id,
        edition=foreign,
        principal=selector,
        capability_code="venues.select_for_edition",
    )
    attribution = {
        "actor": selector,
        "organization_id": foreign.organization_id,
        "edition_id": foreign.id,
        "reason": "Synthetic shared physical venue across editions",
        "source_channel": "test",
    }
    selected_venue = select_venue_for_edition(
        **attribution,
        property_id=property_record.id,
        responsible_department_id=department.id,
        local_name="Other edition venue",
        public_description_override="",
        public_contact_override="",
        opening_restrictions="",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    source = booking.space_selection
    selected_space = select_space_for_edition(
        **attribution,
        venue_selection_id=selected_venue.object_id,
        source_space_id=source.source_space_id,
        source_combination_id=None,
        selected_configuration_id=source.selected_configuration_id,
        local_name="Other edition room",
        capacity=None,
        public_access_info="",
        opening_restrictions="",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    assert selected_space.object_id != source.id
    assert foreign.id != edition.id
    manager = AccountFactory()
    CapabilityGrantFactory(
        principal=manager,
        organization_id=property_record.organization_id,
        capability_code="venues.manage_properties",
    )
    return lambda: update_venue_property(
        actor=manager,
        organization_id=property_record.organization_id,
        property_id=property_record.id,
        expected_version=property_record.aggregate_version,
        changes={"location_name": "Synthetic relocated property"},
        reason="Synthetic concurrent shared physical-property change",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


@pytest.mark.parametrize("kind", ["copy", "booking", "property"])
@pytest.mark.parametrize("rollback_publication", [False, True])
def test_owner_waits_for_uncommitted_publication_then_governs_exact_release(
    review_scope,
    kind,
    rollback_publication,
):
    change = mutation(review_scope, kind)
    approved = approve(review_scope)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            publish(review_scope, approved)
            future = executor.submit(_worker, change, backends)
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_publication:
                transaction.set_rollback(True)
        future.result(timeout=12)
    result = load(review_scope)
    assert result.state == ("absent" if rollback_publication else "invalidated")
    assert result.selections == ()


@pytest.mark.parametrize("kind", ["copy", "booking", "property"])
@pytest.mark.parametrize("rollback_owner", [False, True])
def test_publication_waits_for_native_owner_and_uses_post_wait_source_state(
    review_scope,
    kind,
    rollback_owner,
):
    change = mutation(review_scope, kind)
    approved = approve(review_scope)
    backends = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            change()
            future = executor.submit(
                _worker, lambda: publish(review_scope, approved), backends
            )
            _observe_lock_wait(backends.get(timeout=5))
            assert not future.done()
            if rollback_owner:
                transaction.set_rollback(True)
        if rollback_owner:
            future.result(timeout=12)
        else:
            with pytest.raises(SchedulingUnavailableError):
                future.result(timeout=12)
    assert load(review_scope).state == ("available" if rollback_owner else "absent")
