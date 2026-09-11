"""Ended approved history is not rewritten or promoted into new release eligibility."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import connection

from maru.identity.models import Account
from maru.programme.models import ProgrammeItem
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.models import (
    SchedulingReleaseApproval,
    SchedulingReleaseDependencyChange,
)
from maru.venues.models import VenueBooking
from maru.venues.services import cancel_venue_booking
from tests.integration.test_scheduling_placements import planning_world
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

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    # Use the real database clock. No altered journal timestamps or disabled
    # source guards, and no sleep to manufacture an ended obligation.
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        now = cursor.fetchone()[0]
    starts = (now - timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    return planning_world(monkeypatch, starts_at=starts)


def test_native_change_after_end_preserves_history_but_not_new_eligibility(
    review_scope,
):
    published = publish(review_scope, approve(review_scope))
    initial = load(review_scope)
    booking = VenueBooking.objects.get(edition_id=review_scope.request.edition_id)
    actor = Account.objects.get(id=review_scope.request.actor_id)
    cancel_venue_booking(
        actor=actor,
        organization_id=booking.organization_id,
        edition_id=booking.edition_id,
        space_selection_id=booking.space_selection_id,
        booking_id=booking.id,
        expected_version=booking.aggregate_version,
        reason="Close the retained synthetic room approval after its work interval",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    change = SchedulingReleaseDependencyChange.objects.get(
        dependency__kind="venue_booking", dependency__source_id=booking.id
    )
    assert change.recorded_at > review_scope.world.placement.envelope.teardown_ends_at
    assert load(review_scope) == initial
    assert (
        load(review_scope, release_id=published.object_id).selections
        == initial.selections
    )
    with pytest.raises(SchedulingUnavailableError):
        approve(
            review_scope,
            request=replace(review_scope.review_request, idempotency_key=uuid4()),
        )
    assert SchedulingReleaseApproval.objects.count() == 1


def test_copy_withdrawal_has_no_past_history_expiry(review_scope):
    published = publish(review_scope, approve(review_scope))
    initial = load(review_scope)
    item = ProgrammeItem.objects.get(id=review_scope.selection.item_id)
    withdraw_programme_public_rendition(
        actor_id=review_scope.request.actor_id,
        organization_id=item.organization_id,
        edition_id=item.edition_id,
        item_id=item.id,
        rendition_id=initial.selections[0].public_rendition_id,
        expected_version=item.aggregate_version,
        reason="End disclosure of the retained synthetic past copy",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=review_scope.policy,
    )
    for options in ({}, {"release_id": published.object_id}):
        current = load(review_scope, **options)
        assert current.state == "invalidated"
        assert current.selections == ()
