"""Exact physical source policy and minimized live occupancy projections."""

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.venues import scheduling_queries as source
from maru.venues.services import (
    VenueAvailabilityInterval,
    approve_venue_booking,
    cancel_venue_booking,
    set_edition_space_availability,
)
from tests.integration import test_venues as scenarios

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
START = datetime(2030, 8, 2, 8, tzinfo=UTC)


def test_physical_key_derivation_matches_postgresql_and_is_edition_bounded():
    edition = UUID("11111111-1111-1111-1111-111111111111")
    booking = UUID("22222222-2222-2222-2222-222222222222")
    payload = f"venue-physical-conflict@1:{edition}:{booking}"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT substr(encode(sha256(convert_to(%s, 'UTF8')), 'hex'), 1, 32)::uuid",
            [payload],
        )
        expected = cursor.fetchone()[0]
    assert source._physical_source_key(edition, booking) == expected
    assert source._physical_source_key(booking, edition) != expected
    assert source._physical_source_key(edition, edition) != expected
    assert expected not in {edition, booking}


@pytest.fixture
def world():
    scope = scenarios._scope(starts_on=date(2030, 8, 2))
    space = scenarios._selected_space(scope)
    for actor in (scope.scheduler, scope.approver):
        scenarios._grant_space(actor, scope, space, "venues.manage_space_schedule")
    set_edition_space_availability(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        expected_version=space.aggregate_version,
        intervals=(
            VenueAvailabilityInterval(
                START, START + timedelta(hours=12), "Private restriction"
            ),
        ),
        reason="Synthetic physical availability",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return scope, space


@pytest.fixture
def admitted(monkeypatch):
    monkeypatch.setattr(source, "profile_allows_conflict_source", lambda *_args: True)
    monkeypatch.setattr(
        source,
        "decide_verified_principal_exact_resource",
        lambda **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset({"audit", "reason"}),
            reason_code="sealed_future_profile_harness",
        ),
    )


def query(world, **overrides):
    scope, space = world
    values = {
        "actor_id": scope.scheduler.id,
        "organization_id": scope.edition.organization_id,
        "edition_id": scope.edition.id,
        "selection_ids": (space.id,),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    values.update(overrides)
    return source.load_venue_scheduling_dependencies(**values)


def booking(world):
    return scenarios._create_booking(world[0], world[1], start=START)


def test_existing_profile_cannot_supply_an_unpinned_physical_source(world):
    with pytest.raises(source.VenueSchedulingSourceUnavailableError):
        query(world)


def test_real_resource_policy_still_denies_under_current_manifest(world, monkeypatch):
    monkeypatch.setattr(source, "profile_allows_conflict_source", lambda *_args: True)
    with pytest.raises(source.VenueSchedulingSourceDeniedError):
        query(world)


def test_current_capacity_availability_members_and_private_field_absence(
    world, admitted
):
    with CaptureQueriesContext(connection) as captured:
        result = query(world)
    facts = result.spaces[0]
    assert facts.seated_capacity == 100
    assert facts.standing_capacity == 140
    assert facts.table_capacity == 60
    assert facts.fire_capacity == 150
    assert facts.availability_version == 1
    assert facts.active is True
    assert facts.member_ids == (world[1].source_space_id,)
    assert facts.windows == (
        source.VenueSchedulingWindow(START, START + timedelta(hours=12)),
    )
    assert result.busy_periods == ()
    assert "contact_email" not in " ".join(query["sql"] for query in captured)
    assert all(
        secret not in str(asdict(result))
        for secret in (
            "Private restriction",
            "Private provider contact",
            "Main Stage",
            "Private contract",
        )
    )
    audit = AuditEvent.objects.get(
        operation="venues.query.scheduling_dependencies", outcome="allow"
    )
    assert {"audit", "reason", "audit_sensitive_read"} <= set(audit.obligations)


def test_live_occupancy_keeps_both_cliques_after_independent_approval(world, admitted):
    created = booking(world)
    before = query(world)
    assert len(before.busy_periods) == 2
    assert {period.conflict_group for period in before.busy_periods} == {
        "setup_effective",
        "effective_teardown",
    }
    scope, space = world
    approved = approve_venue_booking(
        actor=scope.approver,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=1,
        reason="Independent physical decision",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    after = query(world)
    assert len(after.busy_periods) == 2
    assert {period.source_version for period in after.busy_periods} == {
        approved.resulting_version
    }
    assert {period.booking_id for period in after.busy_periods} == {created.object_id}
    assert before.busy_periods[0].source_key == after.busy_periods[0].source_key


def test_cancelled_reservation_disappears_from_current_busy_consequences(
    world, admitted
):
    created = booking(world)
    scope, space = world
    assert query(world).busy_periods
    cancel_venue_booking(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=1,
        reason="Physical use cancelled",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert query(world).busy_periods == ()


@pytest.mark.parametrize(
    "value",
    [
        True,
        PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="missing_fields",
        ),
    ],
)
def test_boolean_and_missing_fields_are_not_resource_authority(
    world, admitted, monkeypatch, value
):
    monkeypatch.setattr(
        source, "decide_verified_principal_exact_resource", lambda **_kwargs: value
    )
    with pytest.raises(source.VenueSchedulingSourceDeniedError):
        query(world)


def test_late_resource_policy_revocation_releases_no_facts(
    world, admitted, monkeypatch
):
    calls = 0
    real = source.decide_verified_principal_exact_resource

    def revoke(**kwargs):
        nonlocal calls
        calls += 1
        return replace(real(**kwargs), allowed=calls == 1)

    monkeypatch.setattr(source, "decide_verified_principal_exact_resource", revoke)
    with pytest.raises(source.VenueSchedulingSourceDeniedError):
        query(world)
    assert not AuditEvent.objects.filter(
        operation="venues.query.scheduling_dependencies", outcome="allow"
    ).exists()


@pytest.mark.parametrize("mismatch", ["organization", "edition", "selection"])
def test_exact_scope_mismatch_or_incomplete_set_is_denied(world, admitted, mismatch):
    overrides = {
        "organization": {"organization_id": uuid4()},
        "edition": {"edition_id": uuid4()},
        "selection": {"selection_ids": (world[1].id, uuid4())},
    }
    with pytest.raises(source.VenueSchedulingSourceDeniedError):
        query(world, **overrides[mismatch])


def test_busy_overflow_fails_the_complete_projection(world, admitted, monkeypatch):
    booking(world)
    monkeypatch.setattr(source, "MAX_SCHEDULING_BUSY_PERIODS", 1)
    with pytest.raises(source.VenueSchedulingSourceUnavailableError):
        query(world)


def test_late_physical_read_audit_failure_is_not_silent_success(
    world, admitted, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic physical audit failure")

    monkeypatch.setattr(source, "append_audit", fail)
    with pytest.raises(RuntimeError, match="physical audit failure"):
        query(world)


def test_busy_source_outside_requesting_edition_omits_foreign_ids_and_clips_time(world):
    created = booking(world)
    requested_edition = uuid4()
    periods = source._busy_periods(
        organization_id=world[0].edition.organization_id,
        edition_id=requested_edition,
        member_ids=frozenset({world[1].source_space_id}),
        window=source.VenueSchedulingWindow(
            START + timedelta(minutes=30), START + timedelta(hours=2, minutes=30)
        ),
    )
    assert len(periods) == 2
    assert all(period.booking_id is None for period in periods)
    assert all(
        START + timedelta(minutes=30)
        <= period.window.starts_at
        < period.window.ends_at
        <= START + timedelta(hours=2, minutes=30)
        for period in periods
    )
    text = str(asdict(source.VenueSchedulingSnapshot("test", 1, (), periods)))
    assert str(created.object_id) not in text
    assert str(world[0].edition.id) not in text
    assert "Private production title" not in text
