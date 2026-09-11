"""Complete release reduction does not inherit planning-only success."""

from itertools import permutations

import pytest

from maru.programme.adoption import PROGRAMME_SCHEDULING_CONFLICT_SOURCE
from maru.scheduling.adoption import SCHEDULING_TIME_CONFLICT_SOURCE
from maru.scheduling.catalogs import SchedulingConflictCode as Code
from maru.scheduling.catalogs import SchedulingConflictSeverity as Severity
from maru.scheduling.conflicts import SchedulingFinding
from maru.scheduling.release_eligibility import ReleaseCheck as Check
from maru.scheduling.release_eligibility import ReleaseCheckState as State
from maru.scheduling.release_eligibility import ReleaseEvidenceInvalidError
from maru.scheduling.release_source_rules import (
    combine_release_source_states,
    release_category_for_planning_finding,
    release_state_from_readiness,
)
from maru.venues.adoption import VENUES_SCHEDULING_CONFLICT_SOURCE


@pytest.mark.parametrize(
    ("states", "result"),
    [
        ((), State.UNAVAILABLE),
        ((State.NOT_APPLICABLE,), State.NOT_APPLICABLE),
        ((State.SATISFIED, State.NOT_APPLICABLE), State.SATISFIED),
        ((State.SATISFIED, State.BLOCKED), State.BLOCKED),
        ((State.STALE, State.BLOCKED), State.STALE),
        ((State.UNAVAILABLE, State.STALE, State.BLOCKED), State.UNAVAILABLE),
    ],
)
def test_category_reduction_is_complete_and_order_independent(states, result):
    assert combine_release_source_states(states) is result
    for order in permutations(states):
        assert combine_release_source_states(order) is result


@pytest.mark.parametrize("value", [[], [State.SATISFIED], ("satisfied",), (None,)])
def test_untyped_category_inputs_are_rejected(value):
    with pytest.raises(ReleaseEvidenceInvalidError):
        combine_release_source_states(value)


@pytest.mark.parametrize(
    ("state", "result"),
    [
        ("satisfied", State.SATISFIED),
        ("not_applicable", State.NOT_APPLICABLE),
        ("stale", State.STALE),
        ("blocked", State.BLOCKED),
        ("required", State.BLOCKED),
        ("withdrawn", State.BLOCKED),
        ("absent", State.UNAVAILABLE),
        ("withheld", State.UNAVAILABLE),
        ("unavailable", State.UNAVAILABLE),
        ("unknown", State.UNAVAILABLE),
    ],
)
def test_readiness_states_cannot_infer_success(state, result):
    assert release_state_from_readiness(state) is result


@pytest.mark.parametrize(
    ("source", "code", "category"),
    [
        (SCHEDULING_TIME_CONFLICT_SOURCE, Code.DAY_CHANGED, Check.CANDIDATE),
        (
            PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
            Code.ITEM_RETIRED,
            Check.PROGRAMME_READINESS,
        ),
        (
            PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
            Code.HOST_OUTSIDE_PREFERENCE,
            Check.HOSTS,
        ),
        (
            PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
            Code.HOST_OVERLAP,
            Check.PERSON_CONFLICTS,
        ),
        (
            VENUES_SCHEDULING_CONFLICT_SOURCE,
            Code.RESERVED_ROOM_OVERLAP,
            Check.PHYSICAL_CONSTRAINTS,
        ),
        (VENUES_SCHEDULING_CONFLICT_SOURCE, Code.EVALUATION_LIMIT, Check.CANDIDATE),
    ],
)
def test_existing_planning_findings_do_not_claim_other_release_categories(
    source, code, category
):
    row = SchedulingFinding(source, code, Severity.BLOCKER)
    assert release_category_for_planning_finding(row) is category
