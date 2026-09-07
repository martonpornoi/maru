"""Cheap structural input checks before any owner or database work."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme import scheduling_queries as programme_source
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling.inputs import (
    SchedulingCommandRequest,
    SchedulingOccurrenceInput,
    SchedulingPlacementInput,
    SchedulingServiceDayInput,
    normalized_text,
    require_identifier,
    require_version,
    scheduling_digest,
)
from maru.scheduling.time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
)

START = datetime(2030, 8, 2, 8, tzinfo=UTC)


@pytest.mark.parametrize("value", [None, "", 1, True, str(uuid4())])
def test_identifier_is_never_coerced(value):
    with pytest.raises(ValidationError):
        require_identifier(value)


@pytest.mark.parametrize("value", [None, "1", True, False, -1, 0, 2**63 - 1])
def test_version_requires_exact_advanceable_integer(value):
    with pytest.raises(ValidationError):
        require_version(value)


def test_zero_version_only_represents_absent_control():
    assert require_version(0, initial=True) == 0
    assert require_version(2**63 - 2) == 2**63 - 2


@pytest.mark.parametrize(
    "value", [None, "", " ", "line\nbreak", "a\x00b", "a\u202eb", "x" * 11]
)
def test_text_rejects_empty_control_and_overbound_values(value):
    with pytest.raises(ValidationError):
        normalized_text(value, maximum=10)


def test_labels_preserve_unicode_without_inventing_content():
    assert normalized_text("  Cafe\u0301  ", maximum=10) == "Café"


def test_digest_has_stable_key_order_but_preserves_sequence_meaning():
    assert scheduling_digest({"a": 1, "b": [1, 2]}) == scheduling_digest(
        {"b": [1, 2], "a": 1}
    )
    assert scheduling_digest({"b": [1, 2]}) != scheduling_digest({"b": [2, 1]})


@pytest.mark.parametrize("channel", ["", "User input", "a" * 33, None, "a\n"])
def test_attribution_rejects_arbitrary_source_channel(channel):
    request = SchedulingCommandRequest(
        *(uuid4() for _ in range(5)), "Explicit reason", channel
    )
    with pytest.raises(ValidationError):
        request.normalized()


def test_attribution_normalizes_rationale_and_preserves_trace_and_retry():
    request = SchedulingCommandRequest(
        *(uuid4() for _ in range(5)), "  Explicit reason  "
    )
    normalized = request.normalized()
    assert normalized.reason == "Explicit reason"
    assert normalized.idempotency_key == request.idempotency_key
    assert normalized.correlation_id == request.correlation_id


@pytest.mark.parametrize(
    ("key", "sequence"),
    [
        (None, 1),
        (uuid4(), None),
        (uuid4(), True),
        (uuid4(), 0),
        (uuid4(), 2001),
        ("invalid", 1),
    ],
)
def test_explicit_group_pair_is_complete_and_bounded(key, sequence):
    with pytest.raises(ValidationError):
        SchedulingOccurrenceInput(uuid4(), key, sequence).normalized()


def test_group_and_ungrouped_occurrences_are_explicit():
    plain = SchedulingOccurrenceInput(uuid4())
    grouped = replace(plain, group_key=uuid4(), group_sequence=2000)
    assert plain.normalized() == plain
    assert grouped.normalized() == grouped


def placement():
    return SchedulingPlacementInput(
        uuid4(),
        1,
        uuid4(),
        1,
        uuid4(),
        SchedulingEnvelope(
            START,
            START + timedelta(minutes=15),
            START + timedelta(hours=1),
            START + timedelta(hours=2),
        ),
        "seated",
        50,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capacity_mode", "unknown"),
        ("capacity_mode", True),
        ("expected_attendance", True),
        ("expected_attendance", 0),
        ("expected_attendance", 2**31),
        ("occurrence_version", 0),
        ("day_id", "invalid"),
    ],
)
def test_placement_rejects_untyped_or_out_of_bound_structure(field, value):
    with pytest.raises(ValidationError):
        replace(placement(), **{field: value}).normalized()


def test_host_presence_does_not_implicitly_expand_to_room_preparation():
    intent = placement()
    presence = SchedulingHostPresence(
        uuid4(), intent.envelope.effective_starts_at, intent.envelope.effective_ends_at
    )
    normalized = replace(intent, host_presences=(presence,)).normalized()
    assert normalized.host_presences == (presence,)
    assert normalized.envelope.setup_starts_at < presence.starts_at
    assert normalized.envelope.teardown_ends_at > presence.ends_at


def test_day_input_normalizes_label_and_exact_window():
    normalized = SchedulingServiceDayInput(
        "  Friday  ", SchedulingWindow(START, START + timedelta(hours=24)), 5
    ).normalized()
    assert normalized.label == "Friday"
    assert normalized.window.ends_at - normalized.window.starts_at == timedelta(
        hours=24
    )


@pytest.mark.parametrize(
    "periods",
    [
        (
            ProgrammeHostAvailabilityPeriod(
                START.replace(tzinfo=None), START + timedelta(hours=1)
            ),
        ),
        (ProgrammeHostAvailabilityPeriod(START, START),),
        (ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1), "hidden"),),
        (
            ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=2)),
            ProgrammeHostAvailabilityPeriod(
                START + timedelta(hours=1), START + timedelta(hours=3)
            ),
        ),
        (ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1)),) * 129,
    ],
)
def test_corrupt_current_owner_periods_never_become_partial_passing_source(periods):
    with pytest.raises(ProgrammeQueryUnavailableError):
        programme_source._current_periods(periods)


def test_adjacent_deliberately_shared_owner_periods_are_preserved():
    first = ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1))
    second = ProgrammeHostAvailabilityPeriod(
        first.ends_at, first.ends_at + timedelta(hours=1), "preferred"
    )
    assert programme_source._current_periods((first, second)) == (first, second)


@pytest.mark.parametrize(
    "values", [(uuid4(),) * 2, (uuid4(), uuid4(), uuid4()), [uuid4()], ("invalid",)]
)
def test_owner_source_selection_rejects_duplicates_bounds_and_untyped_values(values):
    with pytest.raises(ValidationError):
        programme_source._identifiers(values, 2)
