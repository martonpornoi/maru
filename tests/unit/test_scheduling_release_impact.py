"""Complete deterministic selection impact without a database or recipient lookup."""

from dataclasses import FrozenInstanceError, replace
from itertools import permutations, product
from uuid import UUID

import pytest

from maru.scheduling.catalogs import MAX_OCCURRENCES
from maru.scheduling.release_artifacts import (
    ReleaseArtifactInvalidError,
    ReleaseArtifactSelection,
)
from maru.scheduling.release_impact import (
    ReleaseSelectionChangeKind as Kind,
)
from maru.scheduling.release_impact import (
    compare_release_selections,
)


def _row(number=1):
    return ReleaseArtifactSelection(
        UUID(int=number), UUID(int=10_000 + number), UUID(int=20_000 + number)
    )


def test_membership_and_reference_changes_are_distinct_and_keep_both_versions():
    original = tuple(_row(number) for number in range(1, 6))
    later = (
        original[0],
        replace(original[1], placement_id=UUID(int=30_002)),
        replace(original[2], public_rendition_id=UUID(int=30_003)),
        replace(
            original[3],
            placement_id=UUID(int=30_004),
            public_rendition_id=UUID(int=40_004),
        ),
        _row(6),
    )
    result = compare_release_selections(before=original, after=later)
    assert (result.added_count, result.changed_count, result.removed_count) == (1, 3, 1)
    assert [row.kind for row in result.changes] == [
        Kind.UNCHANGED,
        Kind.CHANGED,
        Kind.CHANGED,
        Kind.CHANGED,
        Kind.REMOVED,
        Kind.ADDED,
    ]
    assert [row.changed_fields for row in result.changes] == [
        (),
        ("placement_id",),
        ("public_rendition_id",),
        ("placement_id", "public_rendition_id"),
        (),
        (),
    ]
    assert result.changes[1].before is original[1]
    assert result.changes[1].after is later[1]
    assert result.changes[4].after is None
    assert result.changes[5].before is None


def test_input_order_has_no_effect_and_cannot_change_the_original_selections():
    before = (_row(1), _row(2), _row(3))
    after = (_row(2), _row(4), _row(5))
    expected = compare_release_selections(before=before, after=after)
    for left, right in product(permutations(before), permutations(after)):
        assert compare_release_selections(before=left, after=right) == expected
    with pytest.raises(FrozenInstanceError):
        expected.changes[0].kind = Kind.UNCHANGED
    assert before == (_row(1), _row(2), _row(3))


@pytest.mark.parametrize(
    ("before", "after", "counts"),
    [
        ((), (), (0, 0, 0)),
        ((), (_row(),), (1, 0, 0)),
        ((_row(),), (), (0, 0, 1)),
        ((_row(),), (_row(),), (0, 0, 0)),
    ],
)
def test_explicit_complete_empty_and_identical_selections(before, after, counts):
    result = compare_release_selections(before=before, after=after)
    assert (result.added_count, result.changed_count, result.removed_count) == counts


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        False,
        "",
        [],
        [_row()],
        (None,),
        (_row(), _row()),
        (_row(), replace(_row(2), placement_id=_row().placement_id)),
    ],
)
def test_partial_wrongly_typed_and_duplicate_selections_fail_closed(side, invalid):
    args = {"before": (_row(),), "after": (_row(),), side: invalid}
    with pytest.raises(ReleaseArtifactInvalidError):
        compare_release_selections(**args)


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize(
    "field", ["occurrence_id", "placement_id", "public_rendition_id"]
)
@pytest.mark.parametrize("invalid", [None, False, "id", UUID(int=0)])
def test_invalid_nested_identifiers_are_rejected(side, field, invalid):
    args = {"before": (_row(),), "after": (_row(),)}
    args[side] = (replace(_row(), **{field: invalid}),)
    with pytest.raises(ReleaseArtifactInvalidError):
        compare_release_selections(**args)


@pytest.mark.parametrize("side", ["before", "after"])
def test_complete_side_limit_is_enforced_without_truncation(side):
    rows = tuple(_row(number) for number in range(1, MAX_OCCURRENCES + 2))
    args = {"before": (), "after": (), side: rows}
    with pytest.raises(ReleaseArtifactInvalidError):
        compare_release_selections(**args)


def test_two_disjoint_maximum_manifests_keep_the_entire_union():
    before = tuple(_row(number) for number in range(1, MAX_OCCURRENCES + 1))
    after = tuple(
        _row(number) for number in range(MAX_OCCURRENCES + 1, 2 * MAX_OCCURRENCES + 1)
    )
    result = compare_release_selections(before=before, after=after)
    assert len(result.changes) == 2 * MAX_OCCURRENCES
    assert result.added_count == result.removed_count == MAX_OCCURRENCES
    assert result.changed_count == 0


def test_shared_reviewed_copy_is_valid_and_does_not_merge_occurrences():
    first = _row()
    second = replace(_row(2), public_rendition_id=first.public_rendition_id)
    result = compare_release_selections(before=(), after=(first, second))
    assert result.added_count == 2


def test_counts_remain_equivalent_to_the_existing_publication_contract():
    rows = (_row(1), _row(2), _row(3))
    states = (
        (),
        (rows[0],),
        rows,
        (replace(rows[0], placement_id=UUID(int=40_001)), rows[1]),
    )
    for before, after in product(states, repeat=2):
        old = {row.occurrence_id: row for row in before}
        new = {row.occurrence_id: row for row in after}
        impact = compare_release_selections(before=before, after=after)
        assert impact.added_count == len(new.keys() - old.keys())
        assert impact.removed_count == len(old.keys() - new.keys())
        assert impact.changed_count == sum(
            old[key] != new[key] for key in old.keys() & new.keys()
        )
