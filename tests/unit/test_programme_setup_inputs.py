"""Database-free input/retry boundaries for dormant Programme setup."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.events.adoption import ADOPTION_PROFILES
from maru.events.models import MAX_EDITION_SPAN_DAYS
from maru.events.programme_setup_inputs import (
    ProgrammeSetupInput,
    ProgrammeSetupMode,
    normalize_programme_setup_input,
    programme_setup_request_digest,
)


def request(**changes):
    return replace(
        ProgrammeSetupInput(
            mode=ProgrammeSetupMode.NEW_FOUNDATION,
            organization_name="  Maru  demonstration organizers  ",
            series_name=" Maru demonstration convention ",
            edition_name=" Demonstration 2027 ",
            department_name="  Programme  ",
            starts_on=date(2027, 1, 1),
            ends_on=date(2027, 1, 3),
            time_zone=" Europe/Budapest ",
            reason=" Prepare the synthetic Programme workflow. ",
        ),
        **changes,
    )


def reused(mode=ProgrammeSetupMode.EXISTING_ORGANIZATION, **changes):
    details = request(
        mode=mode,
        organization_name="",
        organization_id=UUID(int=1),
        foundation_fingerprint="a" * 64,
    )
    if mode is ProgrammeSetupMode.EXISTING_SERIES:
        details = replace(details, series_name="", series_id=UUID(int=2))
    return replace(details, **changes)


def test_setup_normalization_is_immutable_and_does_not_register_a_profile():
    submitted = request()
    normalized = normalize_programme_setup_input(submitted)
    assert normalized.organization_name == "Maru demonstration organizers"
    assert normalized.series_name == "Maru demonstration convention"
    assert normalized.edition_name == "Demonstration 2027"
    assert normalized.department_name == "Programme"
    assert normalized.time_zone == "Europe/Budapest"
    assert normalized.reason == "Prepare the synthetic Programme workflow."
    assert submitted.department_name == "  Programme  "
    assert normalize_programme_setup_input(normalized) == normalized
    with pytest.raises(FrozenInstanceError):
        normalized.edition_name = "Changed"
    assert ("programme_operations", 1) not in ADOPTION_PROFILES


@pytest.mark.parametrize("mode", list(ProgrammeSetupMode))
def test_exact_modes_have_distinct_complete_intents(mode):
    details = request() if mode is ProgrammeSetupMode.NEW_FOUNDATION else reused(mode)
    normalized = normalize_programme_setup_input(details)
    assert normalized.mode is mode
    assert len(programme_setup_request_digest(details)) == 64


@pytest.mark.parametrize(
    "mode", [None, False, 1, "", "NEW_FOUNDATION", "new_foundation ", "unknown"]
)
def test_unknown_or_coerced_modes_are_not_silently_accepted(mode):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(mode=mode))
    assert set(failure.value.error_dict) == {"mode"}


@pytest.mark.parametrize(
    "field",
    [
        "edition_name",
        "department_name",
        "organization_name",
        "series_name",
        "reason",
        "time_zone",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "   ",
        "bad\x00text",
        "bad\ttext",
        "bad\ntext",
        "bad\u202etext",
        "x" * 4097,
    ],
)
def test_required_text_is_typed_bounded_and_control_free(field, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(**{field: value}))
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("organization_name", 160),
        ("series_name", 160),
        ("edition_name", 160),
        ("department_name", 160),
        ("reason", 240),
    ],
)
def test_normalized_text_boundaries(field, limit):
    accepted = normalize_programme_setup_input(request(**{field: "x" * limit}))
    assert getattr(accepted, field) == "x" * limit
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(**{field: "x" * (limit + 1)}))
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize("field", ["starts_on", "ends_on"])
@pytest.mark.parametrize(
    "value", [None, True, "2027-01-01", datetime(2027, 1, 1, tzinfo=UTC)]
)
def test_dates_are_calendar_dates_not_coerced_datetimes(field, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(**{field: value}))
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize("days", [0, MAX_EDITION_SPAN_DAYS])
def test_inclusive_date_interval_uses_the_events_owner_limit(days):
    details = request(ends_on=date(2027, 1, 1) + timedelta(days=days))
    assert normalize_programme_setup_input(details).ends_on == details.ends_on


@pytest.mark.parametrize("days", [-1, MAX_EDITION_SPAN_DAYS + 1])
def test_inverted_or_overlong_interval_fails_before_setup(days):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(
            request(ends_on=date(2027, 1, 1) + timedelta(days=days))
        )
    assert set(failure.value.error_dict) == {"ends_on"}


@pytest.mark.parametrize("zone", ["Not/AZone", "/etc/passwd", "../UTC", "UTC\x00"])
def test_invalid_time_zone_is_a_field_error(zone):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(time_zone=zone))
    assert set(failure.value.error_dict) == {"time_zone"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", UUID(int=1)),
        ("series_id", UUID(int=2)),
        ("foundation_fingerprint", "a" * 64),
    ],
)
def test_new_foundation_rejects_hidden_reuse_inputs(field, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(request(**{field: value}))
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize(
    "mode",
    [ProgrammeSetupMode.EXISTING_ORGANIZATION, ProgrammeSetupMode.EXISTING_SERIES],
)
@pytest.mark.parametrize(
    "value", [None, False, "00000000-0000-0000-0000-000000000001", UUID(int=0)]
)
def test_reuse_requires_a_typed_non_nil_parent_identity(mode, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(reused(mode, organization_id=value))
    assert set(failure.value.error_dict) == {"organization_id"}


@pytest.mark.parametrize(
    "value",
    [None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", " " + "a" * 64],
)
def test_reuse_requires_the_exact_original_snapshot_not_a_normalized_token(value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(reused(foundation_fingerprint=value))
    assert set(failure.value.error_dict) == {"foundation_fingerprint"}


@pytest.mark.parametrize(
    ("mode", "field", "value"),
    [
        (ProgrammeSetupMode.EXISTING_ORGANIZATION, "organization_name", "Rename"),
        (ProgrammeSetupMode.EXISTING_ORGANIZATION, "series_id", UUID(int=2)),
        (ProgrammeSetupMode.EXISTING_ORGANIZATION, "series_name", ""),
        (ProgrammeSetupMode.EXISTING_SERIES, "organization_name", "Rename"),
        (ProgrammeSetupMode.EXISTING_SERIES, "series_name", "Rename"),
        (ProgrammeSetupMode.EXISTING_SERIES, "series_id", None),
        (
            ProgrammeSetupMode.EXISTING_SERIES,
            "series_id",
            "00000000-0000-0000-0000-000000000002",
        ),
        (ProgrammeSetupMode.EXISTING_SERIES, "series_id", UUID(int=0)),
    ],
)
def test_modes_do_not_ignore_conflicting_names_or_ids(mode, field, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_setup_input(reused(mode, **{field: value}))
    assert set(failure.value.error_dict) == {field}


def test_normalized_unicode_and_spacing_have_one_retry_digest():
    decomposed = request(edition_name="  Cafe\u0301   2027  ")
    composed = request(edition_name="Café 2027")
    assert programme_setup_request_digest(decomposed) == programme_setup_request_digest(
        composed
    )
    assert programme_setup_request_digest(composed) == programme_setup_request_digest(
        normalize_programme_setup_input(composed)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_name", "Another organization"),
        ("series_name", "Another series"),
        ("edition_name", "Another edition"),
        ("department_name", "Events"),
        ("reason", "A different accountable reason."),
        ("time_zone", "UTC"),
        ("starts_on", date(2027, 1, 2)),
        ("ends_on", date(2027, 1, 4)),
    ],
)
def test_every_new_foundation_fact_changes_the_retry_digest(field, value):
    assert programme_setup_request_digest(
        request(**{field: value})
    ) != programme_setup_request_digest(request())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", UUID(int=3)),
        ("series_id", UUID(int=4)),
        ("foundation_fingerprint", "b" * 64),
    ],
)
def test_reused_scope_and_snapshot_are_bound_to_the_retry_digest(field, value):
    original = reused(ProgrammeSetupMode.EXISTING_SERIES)
    assert programme_setup_request_digest(
        replace(original, **{field: value})
    ) != programme_setup_request_digest(original)


def test_digest_revalidates_instead_of_hashing_an_invalid_intent():
    with pytest.raises(ValidationError):
        programme_setup_request_digest(request(organization_id=UUID(int=1)))
    with pytest.raises(ValidationError):
        normalize_programme_setup_input(None)
