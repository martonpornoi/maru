"""Boundary and semantic regressions for explicit Programme staffing terms."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme.staffing_inputs import (
    MAX_STAFFING_BREAK_MINUTES,
    MAX_STAFFING_HEADCOUNT,
    MAX_STAFFING_REST_MINUTES,
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
    ProgrammeStaffingSource,
)
from maru.workforce.models import (
    MAX_SHIFT_BREAK_MINUTES,
    MAX_SHIFT_HEADCOUNT,
    MAX_SHIFT_REST_MINUTES,
)
from maru.workforce.shift_inputs import validate_shift_numbers


def expectation():
    return ProgrammeStaffingExpectation(
        uuid4(),
        "  Cafe\u0301   setup ",
        " East stage ",
        " Set up the room ",
        "",
        datetime(2027, 7, 3, 9, tzinfo=timezone(timedelta(hours=2))),
        datetime(2027, 7, 3, 11, tzinfo=timezone(timedelta(hours=2))),
        2,
        15,
        60,
    )


def change():
    return ProgrammeStaffingChange(uuid4(), uuid4(), None, 1, 0, 1, 1, expectation())


def test_staffing_change_normalizes_without_choosing_a_candidate():
    original = change()
    normalized = original.normalized()
    assert normalized.expectation == original.expectation.normalized()
    assert normalized.requirement_id is None
    assert not normalized.retire
    assert original.expectation.title.startswith("  ")


@pytest.mark.parametrize(
    "field",
    [
        "expected_item_version",
        "expected_occurrence_version",
        "expected_edition_version",
    ],
)
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1", 2**63 - 1])
def test_staffing_change_rejects_invalid_source_versions(field, value):
    with pytest.raises(ValidationError):
        replace(change(), **{field: value}).normalized()


@pytest.mark.parametrize(
    "values",
    [
        {"expected_requirement_version": 1},
        {"requirement_id": uuid4()},
        {"retire": True},
        {"expectation": None},
        {"retire": "no"},
        {"requirement_id": uuid4(), "expected_requirement_version": 1, "retire": True},
        {"item_id": "invalid"},
        {"occurrence_id": None},
    ],
)
def test_staffing_change_rejects_ambiguous_or_foreign_shape(values):
    with pytest.raises(ValidationError):
        replace(change(), **values).normalized()


def test_retirement_requires_an_existing_requirement_and_no_replacement_terms():
    intent = replace(
        change(),
        requirement_id=uuid4(),
        expected_requirement_version=1000,
        retire=True,
        expectation=None,
    )
    assert intent.normalized() == intent


def test_explicit_work_is_normalized_without_mutating_input():
    original = expectation()
    result = original.normalized()
    assert result.title == "Café setup"
    assert result.location_label == "East stage"
    assert result.starts_at == datetime(2027, 7, 3, 7, tzinfo=UTC)
    assert result.ends_at == datetime(2027, 7, 3, 9, tzinfo=UTC)
    assert result.position_id == original.position_id
    assert result.minimum_rest_minutes == 60
    assert original.title != result.title
    assert result.normalized() == result
    validate_shift_numbers(
        required_headcount=result.required_headcount,
        break_minutes=result.break_minutes,
        minimum_rest_minutes=result.minimum_rest_minutes,
        starts_at=result.starts_at,
        ends_at=result.ends_at,
    )


def test_staffing_limits_match_the_workforce_owner_contract():
    assert MAX_STAFFING_HEADCOUNT == MAX_SHIFT_HEADCOUNT
    assert MAX_STAFFING_BREAK_MINUTES == MAX_SHIFT_BREAK_MINUTES
    assert MAX_STAFFING_REST_MINUTES == MAX_SHIFT_REST_MINUTES


@pytest.mark.parametrize(
    "field", ["required_headcount", "break_minutes", "minimum_rest_minutes"]
)
@pytest.mark.parametrize("invalid", [True, False, -1, 1.5, "2", None])
def test_staffing_numbers_never_coerce_invalid_input(field, invalid):
    with pytest.raises(ValidationError):
        replace(expectation(), **{field: invalid}).normalized()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("required_headcount", 0),
        ("required_headcount", 1025),
        ("break_minutes", 1441),
        ("minimum_rest_minutes", 2881),
        ("title", " "),
        ("title", "x" * 161),
        ("location_label", ""),
        ("location_label", "x" * 161),
        ("briefing", ""),
        ("briefing", "x" * 1001),
        ("supervision_note", "x" * 501),
        ("briefing", "private\x00text"),
        ("title", None),
        ("position_id", "not-an-identity"),
    ],
)
def test_explicit_work_rejects_missing_or_unbounded_terms(field, invalid):
    with pytest.raises(ValidationError):
        replace(expectation(), **{field: invalid}).normalized()


@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
@pytest.mark.parametrize(
    "instant",
    [
        None,
        "2027-07-03T09:00:00Z",
        datetime(2027, 7, 3, 9, tzinfo=UTC).replace(tzinfo=None),
        datetime(2027, 7, 3, 9, 0, 1, tzinfo=UTC),
        datetime(2027, 7, 3, 9, microsecond=1, tzinfo=UTC),
        datetime(2027, 7, 3, 9, tzinfo=timezone(timedelta(seconds=1))),
    ],
)
def test_staffing_instants_require_real_offset_aware_utc_minutes(field, instant):
    with pytest.raises(ValidationError):
        replace(expectation(), **{field: instant}).normalized()


@pytest.mark.parametrize(
    ("minutes", "break_minutes"), [(0, 0), (-1, 0), (15, 15), (15, 16)]
)
def test_staffing_requires_positive_work_after_break(minutes, break_minutes):
    original = expectation()
    with pytest.raises(ValidationError):
        replace(
            original,
            ends_at=original.starts_at + timedelta(minutes=minutes),
            break_minutes=break_minutes,
        ).normalized()


def source():
    return ProgrammeStaffingSource(
        uuid4(), uuid4(), 1, uuid4(), 1, uuid4(), uuid4(), uuid4()
    )


def test_alternative_and_revision_are_part_of_exact_source_identity():
    first = source().validated()
    for field in (
        "candidate_id",
        "candidate_revision_id",
        "placement_id",
        "requirement_revision_id",
    ):
        other = replace(first, **{field: uuid4()}).validated()
        assert other != first
        assert other.occurrence_id == first.occurrence_id


@pytest.mark.parametrize(
    "field",
    [
        "requirement_id",
        "requirement_revision_id",
        "occurrence_id",
        "candidate_id",
        "candidate_revision_id",
        "placement_id",
    ],
)
def test_source_rejects_string_identifiers_even_when_parseable(field):
    with pytest.raises(ValidationError):
        replace(source(), **{field: str(uuid4())}).validated()


@pytest.mark.parametrize("field", ["requirement_version", "occurrence_version"])
@pytest.mark.parametrize("version", [False, True, 0, -1, 1.5, "1", 2**63 - 1, 2**63])
def test_source_rejects_coerced_or_unadvanceable_versions(field, version):
    with pytest.raises(ValidationError):
        replace(source(), **{field: version}).validated()
