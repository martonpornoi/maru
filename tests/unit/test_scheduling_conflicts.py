"""Fast declared-source rules for time, person and physical consequences."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme.adoption import PROGRAMME_SCHEDULING_CONFLICT_SOURCE
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from maru.programme.scheduling_queries import (
    ProgrammeSchedulingHost,
    ProgrammeSchedulingItem,
    ProgrammeSchedulingSnapshot,
)
from maru.scheduling import conflicts
from maru.scheduling.catalogs import SchedulingConflictCode as Code
from maru.scheduling.catalogs import SchedulingConflictSeverity as Severity
from maru.scheduling.conflicts import (
    SchedulingDayFacts,
    SchedulingOccurrenceFacts,
    SchedulingPlacementFacts,
    evaluate_scheduling_facts,
)
from maru.scheduling.time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
)
from maru.venues.adoption import VENUES_SCHEDULING_CONFLICT_SOURCE
from maru.venues.scheduling_queries import (
    VenueSchedulingBusyPeriod,
    VenueSchedulingSnapshot,
    VenueSchedulingSpace,
    VenueSchedulingWindow,
)

START = datetime(2030, 8, 2, 8, tzinfo=UTC)
WINDOW = SchedulingWindow(START, START + timedelta(hours=12))


def instant(minutes):
    return START + timedelta(minutes=minutes)


def envelope(*minutes):
    return SchedulingEnvelope(*(instant(value) for value in minutes))


@pytest.fixture
def sample():
    occurrence = SchedulingOccurrenceFacts(uuid4(), uuid4(), 1, 1, active=True)
    day = SchedulingDayFacts(
        uuid4(), 1, 1, active=True, window=WINDOW, precision_minutes=5
    )
    placement = SchedulingPlacementFacts(
        uuid4(), occurrence, day, uuid4(), envelope(0, 15, 60, 75), "seated", 50, ()
    )
    programme = ProgrammeSchedulingSnapshot(
        PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
        1,
        (
            ProgrammeSchedulingItem(
                occurrence.item_id, 1, "active", hosting_required=False
            ),
        ),
        (),
    )
    venue = VenueSchedulingSnapshot(
        VENUES_SCHEDULING_CONFLICT_SOURCE,
        1,
        (
            VenueSchedulingSpace(
                placement.space_id,
                1,
                1,
                active=True,
                member_ids=(uuid4(),),
                seated_capacity=100,
                standing_capacity=140,
                table_capacity=60,
                fire_capacity=150,
                windows=(VenueSchedulingWindow(WINDOW.starts_at, WINDOW.ends_at),),
            ),
        ),
        (),
    )
    return placement, programme, venue


def evaluate(sample, *, placements=None, edition=WINDOW, programme=None, venue=None):
    return evaluate_scheduling_facts(
        placements or (sample[0],),
        edition=edition,
        programme=programme or sample[1],
        venues=venue or sample[2],
    )


def codes(findings):
    return {finding.code for finding in findings}


def with_host(sample, *, status="shared", periods=None):
    placement, programme, venue = sample
    host_id = uuid4()
    host = ProgrammeSchedulingHost(
        host_id,
        placement.occurrence.item_id,
        1,
        1,
        uuid4(),
        status,
        periods
        if periods is not None
        else (ProgrammeHostAvailabilityPeriod(instant(0), instant(120)),),
    )
    placement = replace(
        placement, hosts=(SchedulingHostPresence(host_id, instant(15), instant(60)),)
    )
    programme = replace(
        programme,
        hosts=(host,),
        items=(replace(programme.items[0], hosting_required=True),),
    )
    return placement, programme, venue


def test_healthy_declared_sources_are_not_a_release_or_reservation_claim(sample):
    assert evaluate(sample) == ()


@pytest.mark.parametrize(
    ("owner", "field", "value", "expected"),
    [
        ("occurrence", "active", False, Code.OCCURRENCE_RETIRED),
        ("occurrence", "current_version", 2, Code.OCCURRENCE_CHANGED),
        ("day", "active", False, Code.DAY_RETIRED),
        ("day", "current_version", 2, Code.DAY_CHANGED),
        ("day", "window", SchedulingWindow(instant(0), instant(60)), Code.DAY_BOUNDS),
        ("day", "precision_minutes", 10, Code.MINUTE_GRID),
    ],
)
def test_changed_owned_metadata_blocks_without_rewriting_intent(
    sample, owner, field, value, expected
):
    placement = sample[0]
    placement = replace(
        placement, **{owner: replace(getattr(placement, owner), **{field: value})}
    )
    assert expected in codes(evaluate(sample, placements=(placement,)))


def test_edition_shrink_invalidates_an_outside_day_even_if_placement_fits(sample):
    assert Code.EDITION_BOUNDS in codes(
        evaluate(sample, edition=SchedulingWindow(instant(0), instant(180)))
    )


def test_unknown_edition_is_explicitly_unavailable(sample):
    assert Code.EDITION_UNAVAILABLE in codes(evaluate(sample, edition=None))


@pytest.mark.parametrize("owner", ["programme", "venue"])
def test_missing_source_never_becomes_passing(sample, owner):
    findings = evaluate_scheduling_facts(
        (sample[0],),
        edition=WINDOW,
        programme=None if owner == "programme" else sample[1],
        venues=None if owner == "venue" else sample[2],
    )
    assert len(findings) == 1
    assert findings[0].severity == Severity.UNAVAILABLE


def test_unknown_source_contract_is_not_substituted(sample):
    assert codes(
        evaluate(sample, programme=replace(sample[1], contract="programme.unknown@99"))
    ) == {Code.PROGRAMME_UNAVAILABLE}


def test_retired_item_and_missing_required_host_are_independent(sample):
    programme = replace(
        sample[1],
        items=(
            replace(sample[1].items[0], lifecycle="retired", hosting_required=True),
        ),
    )
    assert codes(evaluate(sample, programme=programme)) == {
        Code.ITEM_RETIRED,
        Code.HOST_REQUIRED,
    }


@pytest.mark.parametrize(
    ("status", "expected", "severity"),
    [
        ("ended", Code.HOST_NOT_CURRENT, Severity.BLOCKER),
        ("inactive", Code.HOST_NOT_CURRENT, Severity.BLOCKER),
        ("unconfirmed", Code.HOST_NOT_CURRENT, Severity.BLOCKER),
        ("unavailable", Code.HOST_UNAVAILABLE, Severity.BLOCKER),
        ("not_shared", Code.HOST_SOURCE_UNAVAILABLE, Severity.UNAVAILABLE),
        ("outside_edition", Code.HOST_SOURCE_UNAVAILABLE, Severity.UNAVAILABLE),
    ],
)
def test_host_status_never_means_inferred_free_time(sample, status, expected, severity):
    findings = evaluate(with_host(sample, status=status, periods=()))
    assert codes(findings) == {expected}
    assert findings[0].severity == severity


def test_required_host_presence_need_not_cover_room_setup_and_teardown(sample):
    assert (
        evaluate(
            with_host(
                sample,
                periods=(ProgrammeHostAvailabilityPeriod(instant(15), instant(60)),),
            )
        )
        == ()
    )


def test_adjacent_periods_cover_presence_but_preference_is_a_separate_warning(sample):
    periods = (
        ProgrammeHostAvailabilityPeriod(instant(15), instant(30)),
        ProgrammeHostAvailabilityPeriod(instant(30), instant(60), "preferred"),
    )
    findings = evaluate(with_host(sample, periods=periods))
    assert codes(findings) == {Code.HOST_OUTSIDE_PREFERENCE}
    assert findings[0].severity == Severity.WARNING


def test_availability_gap_is_a_hard_blocker_not_preference_warning(sample):
    periods = (
        ProgrammeHostAvailabilityPeriod(instant(15), instant(30)),
        ProgrammeHostAvailabilityPeriod(instant(35), instant(60), "preferred"),
    )
    assert codes(evaluate(with_host(sample, periods=periods))) == {
        Code.HOST_OUTSIDE_AVAILABILITY
    }


def test_preference_coverage_has_no_warning(sample):
    assert (
        evaluate(
            with_host(
                sample,
                periods=(
                    ProgrammeHostAvailabilityPeriod(
                        instant(15), instant(60), "preferred"
                    ),
                ),
            )
        )
        == ()
    )


@pytest.mark.parametrize(
    ("field", "value"), [("person_key", None), ("item_id", uuid4())]
)
def test_incomplete_or_wrong_purpose_host_proof_is_unavailable(sample, field, value):
    placement, programme, venue = with_host(sample)
    programme = replace(
        programme, hosts=(replace(programme.hosts[0], **{field: value}),)
    )
    assert codes(evaluate((placement, programme, venue))) == {
        Code.HOST_SOURCE_UNAVAILABLE
    }


def test_same_person_overlap_across_items_and_rooms_is_detected(sample):
    first, programme, venue = with_host(sample)
    second = replace(
        first,
        id=uuid4(),
        occurrence=replace(first.occurrence, id=uuid4(), item_id=uuid4()),
        space_id=uuid4(),
    )
    host = replace(
        programme.hosts[0], host_id=uuid4(), item_id=second.occurrence.item_id
    )
    second = replace(second, hosts=(replace(first.hosts[0], host_id=host.host_id),))
    programme = replace(
        programme,
        hosts=(*programme.hosts, host),
        items=(
            *programme.items,
            ProgrammeSchedulingItem(
                second.occurrence.item_id, 1, "active", hosting_required=True
            ),
        ),
    )
    venue = replace(
        venue,
        spaces=(
            *venue.spaces,
            replace(
                venue.spaces[0], selection_id=second.space_id, member_ids=(uuid4(),)
            ),
        ),
    )
    findings = evaluate((first, programme, venue), placements=(first, second))
    assert codes(findings) == {Code.HOST_OVERLAP}
    assert {findings[0].occurrence_id, findings[0].other_occurrence_id} == {
        first.occurrence.id,
        second.occurrence.id,
    }


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("active", False, Code.VENUE_INACTIVE),
        ("seated_capacity", 0, Code.VENUE_CAPACITY),
        ("fire_capacity", 40, Code.VENUE_CAPACITY),
        ("availability_version", 0, Code.VENUE_AVAILABILITY_MISSING),
        ("windows", (), Code.VENUE_HARD_AVAILABILITY),
        ("member_ids", (), Code.VENUE_UNAVAILABLE),
    ],
)
def test_physical_dependencies_remain_independent(sample, field, value, expected):
    venue = replace(sample[2], spaces=(replace(sample[2].spaces[0], **{field: value}),))
    assert codes(evaluate(sample, venue=venue)) == {expected}


def test_hard_physical_availability_requires_one_containing_window(sample):
    space = replace(
        sample[2].spaces[0],
        windows=(
            VenueSchedulingWindow(instant(0), instant(30)),
            VenueSchedulingWindow(instant(30), instant(120)),
        ),
    )
    assert codes(evaluate(sample, venue=replace(sample[2], spaces=(space,)))) == {
        Code.VENUE_HARD_AVAILABILITY
    }


def second_placement(first, minutes):
    return replace(
        first,
        id=uuid4(),
        occurrence=replace(first.occurrence, id=uuid4()),
        envelope=envelope(*minutes),
    )


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        ((50, 55, 90, 100), Code.CANDIDATE_ROOM_OVERLAP),
        ((60, 75, 100, 105), Code.TURNOVER_OVERLAP),
        ((75, 80, 100, 105), None),
    ],
)
def test_two_cliques_distinguish_conflict_turnover_and_adjacency(
    sample, minutes, expected
):
    findings = evaluate(
        sample, placements=(sample[0], second_placement(sample[0], minutes))
    )
    assert codes(findings) == ({expected} if expected else set())


def test_combination_shared_members_are_checked_without_duplicate_findings(sample):
    first = sample[0]
    second = replace(second_placement(first, (0, 15, 60, 75)), space_id=uuid4())
    physical = sample[2].spaces[0].member_ids
    venue = replace(
        sample[2],
        spaces=(
            replace(sample[2].spaces[0], member_ids=(*physical, uuid4())),
            replace(sample[2].spaces[0], selection_id=second.space_id),
        ),
    )
    findings = evaluate(sample, placements=(first, second), venue=venue)
    assert codes(findings) == {Code.CANDIDATE_ROOM_OVERLAP}
    assert len(findings) == 1


def busy(sample, minutes, *, booking_id=None):
    setup, start, end, teardown = map(instant, minutes)
    key, member_id = uuid4(), sample[2].spaces[0].member_ids[0]
    return (
        VenueSchedulingBusyPeriod(
            key,
            1,
            booking_id,
            member_id,
            "setup_effective",
            VenueSchedulingWindow(setup, end),
        ),
        VenueSchedulingBusyPeriod(
            key,
            1,
            booking_id,
            member_id,
            "effective_teardown",
            VenueSchedulingWindow(start, teardown),
        ),
    )


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        ((50, 55, 90, 100), Code.RESERVED_ROOM_OVERLAP),
        ((60, 75, 100, 105), Code.TURNOVER_OVERLAP),
        ((75, 80, 100, 105), None),
    ],
)
def test_live_busy_periods_keep_conflict_and_turnover_visible(
    sample, minutes, expected
):
    findings = evaluate(
        sample, venue=replace(sample[2], busy_periods=busy(sample, minutes))
    )
    assert codes(findings) == ({expected} if expected else set())


def test_only_exact_owner_proven_matching_booking_avoids_self_conflict(sample):
    booking_id = uuid4()
    venue = replace(
        sample[2], busy_periods=busy(sample, (0, 15, 60, 75), booking_id=booking_id)
    )
    assert (
        evaluate(
            sample,
            placements=(replace(sample[0], own_booking_id=booking_id),),
            venue=venue,
        )
        == ()
    )
    assert Code.RESERVED_ROOM_OVERLAP in codes(evaluate(sample, venue=venue))


def test_unknown_busy_clique_is_unavailable_not_assumed_compatible(sample):
    period = replace(busy(sample, (0, 15, 60, 75))[0], conflict_group="unknown")
    assert codes(
        evaluate(sample, venue=replace(sample[2], busy_periods=(period,)))
    ) == {Code.VENUE_UNAVAILABLE}


@pytest.mark.parametrize("limit", ["MAX_CONFLICTS", "MAX_CONFLICT_COMPARISONS"])
def test_overflow_is_a_whole_unavailable_result(sample, monkeypatch, limit):
    monkeypatch.setattr(conflicts, limit, 0)
    findings = evaluate(
        sample, placements=(sample[0], second_placement(sample[0], (0, 15, 60, 75)))
    )
    assert codes(findings) == {Code.EVALUATION_LIMIT}
    assert findings[0].severity == Severity.UNAVAILABLE


def test_duplicate_occurrences_are_rejected_before_evaluation(sample):
    with pytest.raises(ValidationError):
        evaluate(sample, placements=(sample[0], sample[0]))


def test_result_order_does_not_depend_on_candidate_iteration_order(sample):
    second = second_placement(sample[0], (0, 15, 60, 75))
    assert evaluate(sample, placements=(sample[0], second)) == evaluate(
        sample, placements=(second, sample[0])
    )


def test_full_size_adjacent_candidate_does_not_spend_quadratic_comparison_budget(
    sample, monkeypatch
):
    long_window = SchedulingWindow(instant(0), instant(2880))
    base = replace(
        sample[0], day=replace(sample[0].day, window=long_window, precision_minutes=1)
    )
    placements = tuple(
        replace(
            base,
            id=uuid4(),
            occurrence=replace(base.occurrence, id=uuid4()),
            envelope=envelope(index, index, index + 1, index + 1),
        )
        for index in range(2000)
    )
    venue = replace(
        sample[2],
        spaces=(
            replace(
                sample[2].spaces[0],
                windows=(
                    VenueSchedulingWindow(long_window.starts_at, long_window.ends_at),
                ),
            ),
        ),
    )
    monkeypatch.setattr(conflicts, "MAX_CONFLICT_COMPARISONS", 10)
    assert (
        evaluate(sample, placements=placements, edition=long_window, venue=venue) == ()
    )
