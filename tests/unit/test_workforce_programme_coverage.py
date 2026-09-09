"""Coverage semantics preserve independent confirmation and unknown evidence."""

from dataclasses import replace

import pytest

from maru.workforce.programme_coverage import (
    StaffingCoverage,
    StaffingCoverageCounts,
    StaffingCoverageIntegrityError,
    StaffingCoverageState,
    StaffingSourceState,
    evaluate_staffing_coverage,
)


@pytest.mark.parametrize(
    ("counts", "state", "uncovered", "reconcilable"),
    [
        (StaffingCoverageCounts("draft", 2, 0, 0, 0, 0), "draft", 2, True),
        (StaffingCoverageCounts("draft", 2, 0, 0, 0, 1), "draft", 2, False),
        (StaffingCoverageCounts("open", 2, 0, 0, 0, 0), "open_gap", 2, False),
        (
            StaffingCoverageCounts("open", 2, 2, 0, 0, 2),
            "awaiting_confirmation",
            2,
            False,
        ),
        (
            StaffingCoverageCounts("open", 2, 1, 1, 1, 2),
            "awaiting_confirmation",
            1,
            False,
        ),
        (StaffingCoverageCounts("open", 2, 0, 2, 2, 2), "covered", 0, False),
        (StaffingCoverageCounts("open", 2, 0, 2, 1, 2), "review_required", 1, False),
        (
            StaffingCoverageCounts("locked", 2, 0, 1, 1, 1),
            "locked_underfilled",
            1,
            False,
        ),
        (StaffingCoverageCounts("locked", 2, 0, 2, 2, 2), "locked_covered", 0, False),
        (StaffingCoverageCounts("locked", 2, 0, 2, 0, 2), "review_required", 2, False),
    ],
)
def test_planning_distinguishes_claims_current_confirmation_and_locked_underfill(
    counts,
    state,
    uncovered,
    reconcilable,
):
    result = evaluate_staffing_coverage(
        source_state=StaffingSourceState.CURRENT, counts=counts
    )
    assert result.state == state
    assert result.uncovered == uncovered
    assert result.current_confirmed == counts.current_confirmed
    assert result.pending_claims == counts.claimed
    assert result.draft_reconcilable is reconcilable


@pytest.mark.parametrize(
    "source_state",
    [
        StaffingSourceState.UNBOUND,
        StaffingSourceState.STALE,
        StaffingSourceState.WITHHELD,
        StaffingSourceState.UNAVAILABLE,
    ],
)
@pytest.mark.parametrize(
    "counts", [None, object(), StaffingCoverageCounts("open", 2, 0, 2, 2, 2)]
)
def test_noncurrent_source_never_reads_or_releases_counts(source_state, counts):
    result = evaluate_staffing_coverage(source_state=source_state, counts=counts)
    expected = (
        "unrequested"
        if source_state is StaffingSourceState.UNBOUND
        else source_state.value
    )
    assert result == StaffingCoverage(StaffingCoverageState(expected))


@pytest.mark.parametrize("state", ["completed", "cancelled"])
def test_retained_terminal_work_is_neither_current_coverage_nor_a_new_gap(state):
    result = evaluate_staffing_coverage(
        source_state=StaffingSourceState.CURRENT,
        counts=StaffingCoverageCounts(state, 2, 0, 0, 0, 4),
    )
    assert result == StaffingCoverage(StaffingCoverageState(state))


@pytest.mark.parametrize(
    "field", ["required", "claimed", "confirmed", "current_confirmed", "retained"]
)
@pytest.mark.parametrize("invalid", [True, -1, 1.5, "1", None])
def test_invalid_owner_counts_fail_instead_of_becoming_zero(field, invalid):
    with pytest.raises(StaffingCoverageIntegrityError):
        evaluate_staffing_coverage(
            source_state=StaffingSourceState.CURRENT,
            counts=replace(
                StaffingCoverageCounts("open", 2, 0, 0, 0, 0), **{field: invalid}
            ),
        )


@pytest.mark.parametrize(
    "counts",
    [
        StaffingCoverageCounts("open", 0, 0, 0, 0, 0),
        StaffingCoverageCounts("open", 1025, 0, 0, 0, 0),
        StaffingCoverageCounts("open", 2, 2, 1, 1, 3),
        StaffingCoverageCounts("open", 2, 0, 1, 2, 2),
        StaffingCoverageCounts("open", 2, 0, 1, 1, 0),
        StaffingCoverageCounts("open", 2, 0, 0, 0, 4097),
        StaffingCoverageCounts("unknown", 2, 0, 0, 0, 0),
        StaffingCoverageCounts("locked", 2, 1, 0, 0, 1),
        StaffingCoverageCounts("draft", 2, 0, 1, 1, 1),
        StaffingCoverageCounts("completed", 2, 0, 1, 1, 1),
        StaffingCoverageCounts("cancelled", 2, 1, 0, 0, 1),
        None,
        object(),
    ],
)
def test_inconsistent_or_partial_owner_snapshots_are_rejected(counts):
    with pytest.raises(StaffingCoverageIntegrityError):
        evaluate_staffing_coverage(
            source_state=StaffingSourceState.CURRENT, counts=counts
        )


def test_untyped_source_state_cannot_enter_a_trusted_projection():
    with pytest.raises(StaffingCoverageIntegrityError):
        evaluate_staffing_coverage(source_state="current", counts=None)
