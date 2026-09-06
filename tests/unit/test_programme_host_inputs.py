"""Host-purpose inputs cannot infer people, confirmation or availability."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme.host_catalogs import ProgrammeHostAvailabilityState
from maru.programme.host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
    ProgrammeHostInvitationInput,
    ProgrammeHostResponseInput,
    host_availability_periods_digest,
    normalize_host_availability_periods,
    normalize_host_availability_state,
)

START = datetime(2026, 10, 23, tzinfo=UTC)
END = START + timedelta(days=3)


@pytest.mark.parametrize("state", ["draft", "shared", "withdrawn"])
def test_empty_complete_availability_intent_is_frozen_and_normalized(state):
    value = ProgrammeHostAvailabilityInput(uuid4(), state, (), 2, 2)
    assert value.normalized() == value
    assert (
        host_availability_periods_digest(())
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_withdrawal_cannot_smuggle_retained_periods():
    value = ProgrammeHostAvailabilityInput(
        uuid4(), "withdrawn", (ProgrammeHostAvailabilityPeriod(START, END),), 2, 2
    )
    with pytest.raises(ValidationError, match="Withdrawal"):
        value.normalized()


def test_period_digest_is_ordered_and_normalized_not_offset_dependent():
    original = ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1))
    offset = timezone(timedelta(hours=2))
    equivalent = ProgrammeHostAvailabilityPeriod(
        original.starts_at.astimezone(offset), original.ends_at.astimezone(offset)
    )
    assert host_availability_periods_digest(
        normalize((original,))
    ) == host_availability_periods_digest(normalize((equivalent,)))
    assert host_availability_periods_digest(
        normalize((original,))
    ) != host_availability_periods_digest(
        normalize((replace(original, kind="preferred"),))
    )


def invitation():
    return ProgrammeHostInvitationInput(
        uuid4(), "host", "  Opening   ceremony ", "Cue one\r\nCue two", 1
    )


def normalize(periods):
    return normalize_host_availability_periods(
        periods, edition_starts_at=START, edition_ends_at=END
    )


def test_invitation_is_explicit_frozen_and_preserves_host_briefing_paragraphs():
    value = invitation().normalized()
    assert value.title == "Opening ceremony"
    assert value.briefing == "Cue one\nCue two"
    assert value.expected_host_version == 0
    assert value.normalized() == value
    with pytest.raises(FrozenInstanceError):
        value.role = "co_host"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "person"),
        ("account_id", None),
        ("role", "organizer"),
        ("role", None),
        ("title", " "),
        ("title", "x" * 241),
        ("title", "Hidden\x00text"),
        ("briefing", None),
        ("briefing", "x" * 2001),
        ("briefing", "Hidden\x1btext"),
        ("expected_item_version", 0),
        ("expected_item_version", True),
        ("expected_item_version", 2**63 - 1),
        ("expected_item_version", 1.0),
        ("expected_host_version", -1),
        ("expected_host_version", False),
        ("expected_host_version", 2**63),
    ],
)
def test_invitation_rejects_invalid_identity_role_copy_and_versions(field, value):
    with pytest.raises(ValidationError):
        replace(invitation(), **{field: value}).normalized()


@pytest.mark.parametrize("response", ["confirm", "decline", "withdraw"])
def test_self_response_is_closed_and_has_no_caller_supplied_person_or_reason(response):
    value = ProgrammeHostResponseInput(uuid4(), response, 2, 1, 1)
    assert value.normalized() == value
    assert set(value.__dataclass_fields__) == {
        "host_id",
        "response",
        "expected_item_version",
        "expected_host_version",
        "invitation_sequence",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("response", "approve_on_behalf"),
        ("host_id", "not-a-uuid"),
        ("expected_item_version", 0),
        ("expected_host_version", 0),
        ("invitation_sequence", True),
        ("invitation_sequence", 2**63),
    ],
)
def test_response_requires_exact_bounded_positive_versions(field, value):
    response = ProgrammeHostResponseInput(uuid4(), "confirm", 2, 1, 1)
    with pytest.raises(ValidationError):
        replace(response, **{field: value}).normalized()


def test_periods_canonicalize_offsets_sort_and_preserve_half_open_adjacency():
    offset = timezone(timedelta(hours=2))
    first = ProgrammeHostAvailabilityPeriod(
        START.astimezone(offset), START + timedelta(hours=1)
    )
    second = ProgrammeHostAvailabilityPeriod(
        START + timedelta(hours=1), END, "preferred"
    )
    result = normalize((second, first))
    assert result == (
        ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1)),
        second,
    )
    assert result[0].starts_at.tzinfo is UTC
    assert normalize(result) == result


def test_empty_shared_availability_is_valid_and_not_an_unknown_write():
    assert normalize(()) == ()
    assert (
        normalize_host_availability_state("shared")
        is ProgrammeHostAvailabilityState.SHARED
    )
    assert (
        normalize_host_availability_state("draft")
        is ProgrammeHostAvailabilityState.DRAFT
    )
    assert (
        normalize_host_availability_state("withdrawn")
        is ProgrammeHostAvailabilityState.WITHDRAWN
    )
    with pytest.raises(ValidationError):
        normalize_host_availability_state("unknown")
    with pytest.raises(ValidationError):
        normalize_host_availability_state("free")


@pytest.mark.parametrize(
    "period",
    [
        ProgrammeHostAvailabilityPeriod(START.replace(tzinfo=None), END),
        ProgrammeHostAvailabilityPeriod(START, END.replace(tzinfo=None)),
        ProgrammeHostAvailabilityPeriod(START + timedelta(seconds=1), END),
        ProgrammeHostAvailabilityPeriod(START, END + timedelta(microseconds=1)),
        ProgrammeHostAvailabilityPeriod(START, START),
        ProgrammeHostAvailabilityPeriod(END, START),
        ProgrammeHostAvailabilityPeriod(START, END, "busy"),
        ProgrammeHostAvailabilityPeriod(None, END),
        ProgrammeHostAvailabilityPeriod(START - timedelta(minutes=1), END),
        ProgrammeHostAvailabilityPeriod(START, END + timedelta(minutes=1)),
    ],
)
def test_invalid_or_outside_periods_do_not_become_availability(period):
    with pytest.raises(ValidationError):
        normalize((period,))


def test_overlap_duplicate_unbounded_iterables_and_excess_periods_are_rejected():
    period = ProgrammeHostAvailabilityPeriod(START, END)
    for periods in (
        (period, period),
        (period,) * 129,
        [period],
        iter((period,)),
        ("period",),
    ):
        with pytest.raises(ValidationError):
            normalize(periods)


def test_unavailable_edition_envelope_fails_even_for_empty_periods():
    with pytest.raises(ValidationError):
        normalize_host_availability_periods(
            (), edition_starts_at=END, edition_ends_at=START
        )


def test_offset_overflow_and_subminute_historical_offset_fail_closed():
    for instant in (
        datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
        START.replace(tzinfo=timezone(timedelta(seconds=30))),
    ):
        with pytest.raises(ValidationError):
            ProgrammeHostAvailabilityPeriod(instant, END).normalized()
