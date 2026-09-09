"""No-database editor instants and honest immutable-candidate comparisons."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.planning_interactions import (
    compare_planning_placements,
    parse_planning_minute,
)
from maru.scheduling.planning_queries import PlanningPlacement
from maru.scheduling.time_rules import SchedulingEnvelope


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-08-02T10:00", datetime(2030, 8, 2, 8, tzinfo=UTC)),
        ("2030-08-02T10:00+02:00", datetime(2030, 8, 2, 8, tzinfo=UTC)),
        ("2030-08-02T08:00Z", datetime(2030, 8, 2, 8, tzinfo=UTC)),
        ("2030-08-03T00:30", datetime(2030, 8, 2, 22, 30, tzinfo=UTC)),
        ("2030-10-27T02:30+02:00", datetime(2030, 10, 27, 0, 30, tzinfo=UTC)),
        ("2030-10-27T02:30+01:00", datetime(2030, 10, 27, 1, 30, tzinfo=UTC)),
    ],
)
def test_edition_zone_and_explicit_offsets_select_exact_instants(value, expected):
    assert parse_planning_minute(value, zone_name="Europe/Budapest") == expected


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("2030-03-31T02:30", "scheduling_minute_nonexistent"),
        ("2030-10-27T02:30", "scheduling_minute_ambiguous"),
    ],
)
def test_local_gap_and_fold_are_never_silently_adjusted(value, code):
    with pytest.raises(ValidationError) as result:
        parse_planning_minute(value, zone_name="Europe/Budapest")
    assert result.value.code == code


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2030-08-02 10:00",
        "2030-08-02T10:00:00",
        "2030-08-02T10:00:01Z",
        "2030-08-02T10:00+0200",
        "2030-02-30T10:00",
        "2030-08-02T24:00",
        "2030-08-02T10:00+24:00",
        "2030-08-02T10:00+01:60",
        "2030-08-02T10:00-02:99",
        "0001-01-01T00:00+01:00",
        "2030-08-02T10:00\n",
        " 2030-08-02T10:00",
        "\uff12\uff10\uff13\uff10-08-02T10:00",
        None,
        1,
        True,
    ],
)
def test_malformed_minutes_fail_without_coercion_or_precision_loss(value):
    with pytest.raises(ValidationError):
        parse_planning_minute(value, zone_name="Europe/Budapest")


def test_even_explicit_offset_cannot_hide_unknown_edition_zone():
    with pytest.raises(ValidationError):
        parse_planning_minute("2030-08-02T08:00Z", zone_name="Unknown/Zone")


def placement():
    start = datetime(2030, 8, 2, 8, tzinfo=UTC)
    return PlanningPlacement(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "seated",
        80,
        SchedulingEnvelope(
            start, start, start + timedelta(hours=1), start + timedelta(hours=1)
        ),
        uuid4(),
    )


def test_comparison_keeps_added_removed_changed_and_unchanged_occurrences():
    removed, changed, unchanged, added = (placement() for _ in range(4))
    revised = replace(changed, id=uuid4(), expected_attendance=90)
    result = compare_planning_placements(
        (removed, changed, unchanged), (revised, unchanged, added)
    )
    by_id = {entry.occurrence_id: entry for entry in result}
    assert by_id[removed.occurrence_id].status == "removed"
    assert by_id[removed.occurrence_id].after is None
    assert by_id[added.occurrence_id].status == "added"
    assert by_id[added.occurrence_id].before is None
    assert by_id[unchanged.occurrence_id].status == "unchanged"
    assert by_id[changed.occurrence_id].status == "changed"
    assert by_id[changed.occurrence_id].changed_fields == ("expected_attendance",)
    assert [entry.occurrence_id for entry in result] == sorted(by_id, key=str)


def test_new_placement_evidence_is_not_unchanged_even_with_equal_visible_geometry():
    before = placement()
    after = replace(before, id=uuid4())
    result = compare_planning_placements((before,), (after,))[0]
    assert result.status == "changed"
    assert result.changed_fields == ()
    assert result.before == before
    assert result.after == after


def test_comparison_does_not_mutate_or_merge_manifests():
    original = placement()
    before = (original,)
    assert compare_planning_placements(before, before)[0].status == "unchanged"
    assert before == (original,)
    assert compare_planning_placements((), ()) == ()


@pytest.mark.parametrize("side", ["before", "after"])
def test_duplicate_occurrences_cannot_look_like_complete_comparison(side):
    original = placement()
    duplicate = (original, replace(original, id=uuid4()))
    with pytest.raises(ValidationError):
        compare_planning_placements(
            duplicate if side == "before" else (), duplicate if side == "after" else ()
        )
