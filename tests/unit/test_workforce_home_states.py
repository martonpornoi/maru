"""Home choices preserve existing intervals, independent decisions and sharing."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from maru.workforce.home_states import (
    AssignmentHomeFact,
    ShiftHomeFact,
    assignment_home_item,
    availability_home_item,
    shift_home_item,
)

NOW = datetime(2030, 8, 1, 12, tzinfo=UTC)
ACTOR = UUID(int=1)
OTHER = UUID(int=2)


def _assignment(status="proposed", **changes):
    return replace(
        AssignmentHomeFact(UUID(int=3), status, OTHER, NOW - timedelta(days=1), None),
        **changes,
    )


def _shift(status="open", **changes):
    start = NOW + timedelta(hours=1)
    if changes.get("ends_at", NOW + timedelta(hours=3)) <= NOW:
        start = NOW - timedelta(hours=2)
    return replace(
        ShiftHomeFact(UUID(int=4), status, start, NOW + timedelta(hours=3)),
        **changes,
    )


@pytest.mark.parametrize(
    ("facts", "phase", "issue", "end", "code"),
    [
        ((), "planning", True, True, "assignment_plan"),
        ((_assignment(),), "planning", True, True, "assignment_review"),
        ((_assignment(),), "planning", False, True, "assignment_wait_authority"),
        (
            (_assignment(proposed_by_id=ACTOR),),
            "planning",
            True,
            True,
            "assignment_wait_review",
        ),
        ((_assignment("active"),), "planning", True, True, "assignment_active"),
        (
            (_assignment("active", expires_at=NOW),),
            "planning",
            True,
            True,
            "assignment_end",
        ),
        (
            (_assignment("active", expires_at=NOW),),
            "planning",
            True,
            False,
            "assignment_wait_end",
        ),
        (
            (_assignment("active", expires_at=NOW + timedelta(seconds=1)),),
            "planning",
            True,
            True,
            "assignment_active",
        ),
        (
            (_assignment("active", effective_from=NOW + timedelta(days=1)),),
            "planning",
            True,
            True,
            "assignment_active",
        ),
        (
            (_assignment("rejected"), _assignment("ended")),
            "planning",
            True,
            True,
            "assignment_history",
        ),
        ((_assignment("active"),), "closing", True, True, "assignment_closing"),
        ((_assignment(),), "closing", True, True, "assignment_review"),
        (
            (_assignment("active", expires_at=NOW),),
            "closing",
            True,
            True,
            "assignment_end",
        ),
        ((_assignment(),), "retained", True, True, "assignment_history"),
        (
            (_assignment("active", expires_at=NOW),),
            "retained",
            True,
            True,
            "assignment_history",
        ),
    ],
)
def test_assignment_intervals_authority_and_independence(
    facts, phase, issue, end, code
):
    item = assignment_home_item(
        facts, phase=phase, now=NOW, actor_id=ACTOR, can_issue=issue, can_end=end
    )
    assert item.code == code
    assert item.checked_at is None
    assert item.time_zone == "UTC"
    if code in {"assignment_review", "assignment_end", "assignment_wait_end"}:
        assert item.object_id == UUID(int=3)
    else:
        assert item.object_id is None


def test_independent_proposal_takes_precedence_over_own_waiting_proposal():
    own = _assignment(proposed_by_id=ACTOR)
    independent = _assignment(id=UUID(int=5))
    item = assignment_home_item(
        (own, independent),
        phase="planning",
        now=NOW,
        actor_id=ACTOR,
        can_issue=True,
        can_end=False,
    )
    assert item.code == "assignment_review"
    assert item.object_id == independent.id


@pytest.mark.parametrize(
    ("states", "phase", "code"),
    [
        ((), "planning", None),
        (("not_shared",), "planning", "availability_wait"),
        (("withdrawn",), "planning", "availability_withdrawn"),
        (("unavailable",), "planning", "availability_empty"),
        (("shared",), "planning", "availability_shared"),
        (("shared", "not_shared"), "planning", "availability_wait"),
        (("not_shared", "withdrawn"), "planning", "availability_withdrawn"),
        (("shared", "unavailable"), "closing", "availability_empty"),
        (("withdrawn",), "retained", "availability_retained"),
        (("not_shared",), "retained", "availability_retained"),
    ],
)
def test_availability_shared_empty_withdrawn_and_private_states_stay_distinct(
    states, phase, code
):
    item = availability_home_item(states, phase=phase)
    assert (item.code if item else None) == code
    if item:
        assert item.object_id is None
        assert item.due_at is None


@pytest.mark.parametrize(
    ("fact", "phase", "manage", "code"),
    [
        (_shift("draft"), "planning", True, "shift_draft"),
        (_shift("draft"), "planning", False, "shift_wait_draft"),
        (_shift("draft", ends_at=NOW), "planning", True, "shift_ended"),
        (_shift(ends_at=NOW), "planning", True, "shift_ended"),
        (_shift(changed_evidence=True), "planning", True, "shift_changed"),
        (
            _shift(has_claims=True, has_independent_claim=True),
            "planning",
            True,
            "shift_claims",
        ),
        (_shift(has_claims=True), "planning", True, "shift_wait_claims"),
        (
            _shift(has_claims=True, has_independent_claim=True),
            "planning",
            False,
            "shift_wait_manager",
        ),
        (_shift(underfilled=True), "planning", True, "shift_coverage"),
        (_shift(), "planning", True, "shift_lock"),
        (_shift(), "planning", False, "shift_wait_lock"),
        (_shift("locked", ends_at=NOW), "planning", True, "shift_complete"),
        (_shift("locked", ends_at=NOW), "planning", False, "shift_wait_complete"),
        (_shift("locked", changed_evidence=True), "planning", True, "shift_changed"),
        (_shift("locked"), "planning", True, "shift_scheduled"),
        (_shift("locked", starts_at=NOW), "planning", True, "shift_running"),
        (_shift(), "closing", True, "shift_closing"),
        (_shift("draft"), "closing", True, "shift_closing"),
        (_shift("locked"), "closing", True, "shift_closing"),
        (_shift("locked", ends_at=NOW), "closing", True, "shift_complete"),
        (_shift("completed"), "planning", True, "shift_history"),
        (_shift("cancelled"), "planning", True, "shift_history"),
        (_shift(), "retained", True, "shift_history"),
    ],
)
def test_shift_work_review_matches_time_lifecycle_and_independent_authority(
    fact, phase, manage, code
):
    item = shift_home_item((fact,), phase=phase, now=NOW, can_manage=manage)
    assert item.code == code
    assert item.object_id == (None if code == "shift_history" else fact.id)


@pytest.mark.parametrize("phase", ["planning", "closing", "retained"])
def test_empty_shift_area_never_claims_coverage_or_completion(phase):
    item = shift_home_item((), phase=phase, now=NOW, can_manage=True)
    assert item.code == ("shift_plan" if phase == "planning" else "shift_history")
    assert item.object_id is None


def test_ended_work_precedes_stale_claims_drafts_and_informational_work():
    ended = _shift("locked", id=UUID(int=9), ends_at=NOW)
    rows = (_shift("draft"), _shift(changed_evidence=True), ended)
    for ordered in [rows, tuple(reversed(rows))]:
        item = shift_home_item(ordered, phase="planning", now=NOW, can_manage=True)
        assert item.code == "shift_complete"
        assert item.object_id == ended.id
        assert item.due_at == NOW


def test_equal_priority_shift_order_uses_time_then_stable_identity():
    later = _shift("draft", id=UUID(int=5))
    earlier = _shift("draft", id=UUID(int=6), starts_at=NOW + timedelta(minutes=1))
    tied = replace(earlier, id=UUID(int=3))
    for ordered in [(later, earlier, tied), (tied, later, earlier)]:
        item = shift_home_item(ordered, phase="planning", now=NOW, can_manage=True)
        assert item.object_id == tied.id
