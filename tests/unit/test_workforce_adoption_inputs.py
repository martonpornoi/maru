"""Fast current-schema contracts for deliberate Workforce adoption and assignment."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.events.forms import WorkforceAdoptionSetupForm
from maru.events.models import MAX_EDITION_SPAN_DAYS
from maru.workforce.assignment_inputs import (
    normalize_assignment_reason,
    validate_assignment_interval,
)
from maru.workforce.forms import AvailabilityWindowForm


def _setup_form(**changes: str) -> WorkforceAdoptionSetupForm:
    data = {
        "mode": "new_foundation",
        "organization_name": " Synthetic  organizers ",
        "series_name": " Synthetic  convention ",
        "edition_name": " Synthetic  2027 ",
        "starts_on": "2027-01-01",
        "ends_on": "2027-01-03",
        "time_zone": "UTC",
        "idempotency_key": str(uuid4()),
    }
    data.update(changes)
    return WorkforceAdoptionSetupForm(data)


def test_adoption_setup_normalizes_names_without_creating_foundation_records() -> None:
    """Pure validation must not query or create registration/workforce records."""
    form = _setup_form()
    assert form.is_valid(), form.errors
    assert form.cleaned_data["organization_name"] == "Synthetic organizers"
    assert form.cleaned_data["series_name"] == "Synthetic convention"
    assert form.cleaned_data["edition_name"] == "Synthetic 2027"
    defaults = WorkforceAdoptionSetupForm()
    assert defaults.initial["mode"] == "new_foundation"
    assert defaults.initial["time_zone"] == "UTC"
    assert defaults.initial["idempotency_key"]


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"organization_name": " "}, {"organization_name"}),
        ({"series_name": " "}, {"series_name"}),
        (
            {"mode": "existing_organization", "series_name": ""},
            {"organization", "series_name"},
        ),
        ({"mode": "existing_organization"}, {"organization"}),
        ({"mode": "existing_series"}, {"series"}),
        ({"mode": "unlisted"}, {"mode"}),
        ({"starts_on": "invalid"}, {"starts_on"}),
        ({"ends_on": "2026-12-31"}, {"ends_on"}),
        (
            {
                "ends_on": (
                    date(2027, 1, 1) + timedelta(days=MAX_EDITION_SPAN_DAYS + 1)
                ).isoformat()
            },
            {"ends_on"},
        ),
    ],
)
def test_adoption_setup_requires_explicit_foundation_and_bounded_dates(
    changes: dict[str, str], fields: set[str]
) -> None:
    form = _setup_form(**changes)
    assert not form.is_valid()
    assert set(form.errors) == fields


@pytest.mark.parametrize("span", [0, MAX_EDITION_SPAN_DAYS])
def test_adoption_setup_accepts_inclusive_edition_date_boundaries(span: int) -> None:
    form = _setup_form(ends_on=(date(2027, 1, 1) + timedelta(days=span)).isoformat())
    assert form.is_valid(), form.errors


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, "assignment_text_invalid"),
        ("\tunsafe", "assignment_control_character"),
        ("\x00unsafe", "assignment_control_character"),
        (" ", "assignment_reason_required"),
        ("x" * 241, "assignment_reason_too_long"),
    ],
)
def test_assignment_reason_rejects_ambiguous_or_unbounded_evidence(
    value: object, code: str
) -> None:
    with pytest.raises(ValidationError) as failure:
        normalize_assignment_reason(value)
    assert failure.value.error_dict["reason"][0].code == code


def test_assignment_reason_normalizes_unicode_and_preserves_maximum_length() -> None:
    assert normalize_assignment_reason("  Cafe\u0301   support  ") == "Café support"
    assert normalize_assignment_reason("x" * 240) == "x" * 240


@pytest.mark.parametrize(
    ("effective", "expires", "field"),
    [
        ("2027-01-01", None, "effective_from"),
        (datetime(2027, 1, 1), None, "effective_from"),  # noqa: DTZ001 - reject naive input
        (datetime(2027, 1, 1, tzinfo=UTC), "2027-01-02", "expires_at"),
        (datetime(2027, 1, 1, tzinfo=UTC), datetime(2027, 1, 2), "expires_at"),  # noqa: DTZ001 - reject naive input
        (
            datetime(2027, 1, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
            "expires_at",
        ),
        (
            datetime(2027, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
            "expires_at",
        ),
    ],
)
def test_assignment_interval_requires_aware_strictly_ordered_instants(
    effective: object, expires: object, field: str
) -> None:
    with pytest.raises(ValidationError) as failure:
        validate_assignment_interval(effective_from=effective, expires_at=expires)
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize(
    ("starts", "ends", "field"),
    [
        ("", "2027-01-01T14:00", "starts_at"),
        ("2027-01-01T12:00", "", "ends_at"),
        ("2027-01-01T14:00", "2027-01-01T12:00", "ends_at"),
        ("2027-01-01T12:00", "2027-01-01T12:00", "ends_at"),
    ],
)
def test_availability_rows_reject_partial_or_empty_intervals(
    starts: str, ends: str, field: str
) -> None:
    form = AvailabilityWindowForm(
        {"starts_at": starts, "ends_at": ends}, zone_name="UTC"
    )
    assert not form.is_valid()
    assert set(form.errors) == {field}


def test_availability_rows_allow_an_unused_row_and_default_to_available() -> None:
    empty = AvailabilityWindowForm({}, zone_name="UTC")
    assert empty.is_valid(), empty.errors
    form = AvailabilityWindowForm(
        {"starts_at": "2027-01-01T12:00", "ends_at": "2027-01-01T14:00"},
        zone_name="UTC",
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["preference"] == "available"
    assert form.cleaned_data["starts_at"].utcoffset() == timedelta(0)
