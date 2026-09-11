from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from maru.events.models import EventEdition
from maru.events.services import (
    EventEditionDetails,
    transition_edition,
    update_event_edition,
)
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world():
    actor, edition = AccountFactory(), EventEditionFactory()
    for capability in ("events.transition", "events.change_profile"):
        CapabilityGrantFactory(
            principal=actor,
            organization=edition.organization,
            edition=edition,
            capability_code=capability,
        )
    return actor, edition


def _track(world):
    edition = world[1]
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind="edition_operational",
            source_id=edition.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )


def _transition(world, to_state):
    actor, edition = world
    return transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=to_state,
        actor=actor,
        reason="Synthetic edition transition",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _update(world, **changes):
    actor, edition = world
    edition.refresh_from_db()
    details = EventEditionDetails(
        name=edition.name,
        time_zone=edition.time_zone,
        language_codes=tuple(edition.language_codes),
        currency_codes=tuple(edition.currency_codes),
        starts_on=edition.starts_on,
        ends_on=edition.ends_on,
    )
    return update_event_edition(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        expected_aggregate_version=edition.aggregate_version,
        details=replace(details, **changes),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_ordinary_ready_live_progression_does_not_invalidate_release(world):
    key = _track(world)
    for state in ("preparing", "ready", "live"):
        _transition(world, state)
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_cancellation_records_exact_native_edition_invalidation(world):
    key = _track(world)
    _transition(world, "cancelled")
    key.refresh_from_db()
    change = SchedulingReleaseDependencyChange.objects.get()
    assert key.generation == change.generation == 2
    assert change.source_audit.operation == "events.edition.transition"
    assert change.source_audit.target_id == world[1].id


def test_operational_ending_records_invalidation_for_remaining_work(world):
    for state in ("preparing", "ready", "live"):
        _transition(world, state)
    key = _track(world)
    _transition(world, "closing")
    key.refresh_from_db()
    assert key.generation == 2


@pytest.mark.parametrize("field", ["starts_on", "ends_on", "time_zone"])
def test_edition_envelope_changes_invalidate_native_source(world, field):
    key = _track(world)
    value = (
        "Europe/London"
        if field == "time_zone"
        else (getattr(world[1], field) + timedelta(days=1))
    )
    _update(world, **{field: value})
    key.refresh_from_db()
    change = SchedulingReleaseDependencyChange.objects.get()
    assert key.generation == 2
    assert change.source_audit.operation == "events.edition.update"
    assert field in change.source_audit.changed_fields


def test_edition_label_changes_do_not_invalidate_operational_release(world):
    key = _track(world)
    _update(world, name="Synthetic revised edition label")
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_skipped_events_join_cannot_commit_cancellation(world):
    key = _track(world)
    with (
        patch("maru.events.services.record_events_release_change"),
        pytest.raises(IntegrityError, match="native release invalidation"),
    ):
        _transition(world, "cancelled")
    key.refresh_from_db()
    world[1].refresh_from_db()
    assert key.generation == 1
    assert world[1].lifecycle == "draft"
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_raw_date_change_cannot_commit_without_native_invalidation(world):
    key = _track(world)
    with (
        pytest.raises(IntegrityError, match="native release invalidation"),
        transaction.atomic(),
    ):
        EventEdition.objects.filter(pk=world[1].id).update(
            ends_on=world[1].ends_on + timedelta(days=1),
            aggregate_version=2,
        )
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()
