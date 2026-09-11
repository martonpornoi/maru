"""Half-open combined work and retained-rest checks never disclose foreign duties."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.workforce import programme_person_conflicts as conflicts
from maru.workforce.programme_person_conflicts import (
    ProgrammePersonObligation as Obligation,
)

START = datetime(2030, 8, 2, 8, tzinfo=UTC)
PERSON, OCCURRENCE = uuid4(), uuid4()


def host(start=0, end=60, **overrides):
    return replace(
        Obligation(
            PERSON,
            OCCURRENCE,
            uuid4(),
            "host",
            START + timedelta(minutes=start),
            START + timedelta(minutes=end),
            START + timedelta(minutes=end),
        ),
        **overrides,
    )


def work(start=0, end=60, rest=90, **overrides):
    return replace(
        Obligation(
            PERSON,
            None,
            uuid4(),
            "work",
            START + timedelta(minutes=start),
            START + timedelta(minutes=end),
            START + timedelta(minutes=rest),
        ),
        **overrides,
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (-60, 0, ()),
        (-10, 10, ("overlap",)),
        (0, 60, ("overlap",)),
        (59, 80, ("overlap",)),
        (60, 80, ("rest",)),
        (89, 100, ("rest",)),
        (90, 100, ()),
        (100, 120, ()),
    ],
)
def test_host_against_retained_work_and_rest_boundaries(start, end, expected):
    result = conflicts.evaluate_programme_person_conflicts((host(start, end), work()))
    assert tuple(row.code for row in result) == expected
    assert all(
        row.occurrence_id == OCCURRENCE and row.person_key == PERSON for row in result
    )


def test_work_conflict_reports_only_selected_occurrence_not_foreign_identity():
    selected, foreign = work(occurrence_id=OCCURRENCE), work(20, 40, 45)
    result = conflicts.evaluate_programme_person_conflicts((selected, foreign))
    assert len(result) == 1
    assert result[0].occurrence_id == OCCURRENCE
    assert str(foreign.obligation_id) not in str(result)


def test_same_retained_commitment_is_not_double_counted():
    selected = work(occurrence_id=OCCURRENCE)
    assert (
        conflicts.evaluate_programme_person_conflicts(
            (selected, replace(selected, occurrence_id=None))
        )
        == ()
    )


def test_same_occurrence_host_roles_share_presence_but_other_occurrences_conflict():
    assert conflicts.evaluate_programme_person_conflicts((host(), host())) == ()
    other = uuid4()
    result = conflicts.evaluate_programme_person_conflicts(
        (host(), host(occurrence_id=other))
    )
    assert {row.occurrence_id for row in result} == {OCCURRENCE, other}


def test_unrelated_people_or_external_only_work_does_not_disclose_consequences():
    assert (
        conflicts.evaluate_programme_person_conflicts(
            (host(), work(person_key=uuid4()))
        )
        == ()
    )
    assert conflicts.evaluate_programme_person_conflicts((work(), work())) == ()


def test_no_invented_post_host_rest():
    assert conflicts.evaluate_programme_person_conflicts((host(-60, 0), work())) == ()
    with pytest.raises(ValidationError):
        conflicts.evaluate_programme_person_conflicts(
            (host(rest_ends_at=START + timedelta(minutes=90)),)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("person_key", "unknown"),
        ("occurrence_id", "unknown"),
        ("kind", "waived"),
        ("starts_at", None),
        ("starts_at", START.replace(tzinfo=None)),
        ("ends_at", START),
        ("rest_ends_at", START),
    ],
)
def test_malformed_obligations_fail_before_comparison(field, value):
    with pytest.raises(ValidationError):
        conflicts.evaluate_programme_person_conflicts(
            (replace(work(), **{field: value}),)
        )


def test_input_comparison_and_finding_bounds_refuse_partial_results(monkeypatch):
    rows = (host(), work())
    with pytest.raises(ValidationError):
        conflicts.evaluate_programme_person_conflicts(list(rows))
    monkeypatch.setattr(conflicts, "MAX_CONFLICTS", 1)
    with pytest.raises(ValidationError):
        conflicts.evaluate_programme_person_conflicts(rows)
    monkeypatch.setattr(conflicts, "MAX_CONFLICTS", 10)
    monkeypatch.setattr(conflicts, "MAX_CONFLICT_COMPARISONS", 0)
    with pytest.raises(ValidationError):
        conflicts.evaluate_programme_person_conflicts(rows)


def test_order_and_duplicate_consequences_are_deterministic():
    rows = (host(), work(), work(1, 50, 55))
    forward = conflicts.evaluate_programme_person_conflicts(rows)
    assert forward == conflicts.evaluate_programme_person_conflicts(
        tuple(reversed(rows))
    )
    assert len(forward) == 1
