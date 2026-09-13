"""Pure format checks avoid database cost while exercising real transport contracts."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from maru.programme.output_queries import ReleasedProgrammeCopy
from maru.scheduling import output_rendering as rendering
from maru.scheduling.output_queries import (
    PublicProgrammeTimetable,
    PublicTimetableEntry,
)
from maru.scheduling.release_queries import ProgrammeReleaseState
from maru.venues.programme_output_queries import ReleasedRoomWayfinding

START = datetime(2030, 8, 2, 22, tzinfo=UTC)


@pytest.fixture
def snapshot():
    entry = PublicTimetableEntry(
        UUID(int=1),
        ReleasedProgrammeCopy(UUID(int=2), "Opening", "Summary", "Note"),
        ReleasedRoomWayfinding(UUID(int=3), 2, 3, "Stage", "Hall"),
        UUID(int=4),
        START - timedelta(hours=8),
        START + timedelta(hours=4),
        START,
        START + timedelta(hours=1),
    )
    return PublicProgrammeTimetable(
        ProgrammeReleaseState.AVAILABLE,
        1,
        UUID(int=5),
        START - timedelta(days=1),
        START - timedelta(hours=1),
        "Europe/Budapest",
        (entry,),
    )


def test_json_has_closed_public_contract_and_retains_overnight_geometry(snapshot):
    encoded = rendering.render_public_timetable_json(snapshot)
    assert encoded == rendering.render_public_timetable_json(snapshot)
    data = json.loads(encoded)
    assert data["audience"] == "public"
    assert data["contract"] == "scheduling.public-timetable@1"
    assert data["room_label_source"] == "current_venue_wayfinding"
    assert data["zone_name"] == "Europe/Budapest"
    assert data["release_id"] == str(snapshot.release_id)
    (entry,) = data["entries"]
    assert entry["starts_at"] == "2030-08-02T22:00:00+00:00"
    assert entry["day_ends_at"] == "2030-08-03T02:00:00+00:00"
    assert entry["public_rendition_id"] == str(UUID(int=2))
    assert (
        not {"actor_id", "person_id", "item_id", "reason", "candidate_id"}
        & entry.keys()
    )


@pytest.mark.parametrize(
    "renderer",
    [
        rendering.render_public_timetable_json,
        rendering.render_public_timetable_calendar,
    ],
)
def test_deterministic_order_does_not_depend_on_owner_input_order(snapshot, renderer):
    first = snapshot.entries[0]
    second = replace(first, occurrence_id=UUID(int=6))
    assert renderer(replace(snapshot, entries=(first, second))) == renderer(
        replace(snapshot, entries=(second, first))
    )


def test_calendar_uses_stable_uids_explicit_release_and_no_personal_busy_claim(
    snapshot,
):
    first = rendering.render_public_timetable_calendar(snapshot)
    assert first == rendering.render_public_timetable_calendar(snapshot)
    lines = first.decode().split("\r\n")
    assert lines[:3] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Maru//Programme timetable//EN",
    ]
    assert "DTSTART:20300802T220000Z" in lines
    assert "DTEND:20300802T230000Z" in lines
    assert "TRANSP:TRANSPARENT" in lines
    assert "CLASS:PUBLIC" in lines
    assert f"UID:programme-{UUID(int=1)}@maru.invalid" in lines
    assert not any(
        line.startswith(
            ("ATTENDEE:", "ORGANIZER:", "METHOD:", "URL:", "RRULE:", "BEGIN:VALARM")
        )
        for line in lines
    )
    revised = rendering.render_public_timetable_calendar(
        replace(snapshot, release_id=UUID(int=7), pointer_version=2**32)
    ).decode()
    assert f"UID:programme-{UUID(int=1)}@maru.invalid" in revised
    assert "X-MARU-POINTER-VERSION:4294967296" in revised
    assert first.endswith(b"END:VCALENDAR\r\n")


def test_calendar_escapes_injection_and_folds_utf8_without_splitting_characters(
    snapshot,
):
    original = snapshot.entries[0]
    title = "猫🙂" * 80 + "\\,;"
    hostile = "A\r\nBEGIN:VEVENT\nATTENDEE:mailto:nobody@example.invalid\rEND:VEVENT"
    entry = replace(original, copy=replace(original.copy, title=title, summary=hostile))
    encoded = rendering.render_public_timetable_calendar(
        replace(snapshot, entries=(entry,))
    )
    for line in encoded.split(b"\r\n"):
        assert len(line) <= 75
        line.decode("utf-8")
    unfolded = encoded.decode().replace("\r\n ", "")
    assert unfolded.count("\r\nBEGIN:VEVENT\r\n") == 1
    assert unfolded.count("\r\nEND:VEVENT\r\n") == 1
    assert "\r\nATTENDEE:" not in unfolded
    assert (
        "\\nBEGIN:VEVENT\\nATTENDEE:mailto:nobody@example.invalid\\nEND:VEVENT"
        in unfolded
    )
    assert "猫🙂" * 80 + "\\\\\\,\\;" in unfolded


def test_equivalent_offset_instants_have_identical_outputs(snapshot):
    offset = timezone(timedelta(hours=2))
    original = snapshot.entries[0]
    changed = replace(
        original,
        starts_at=original.starts_at.astimezone(offset),
        ends_at=original.ends_at.astimezone(offset),
    )
    for renderer in (
        rendering.render_public_timetable_json,
        rendering.render_public_timetable_calendar,
    ):
        assert renderer(snapshot) == renderer(replace(snapshot, entries=(changed,)))


@pytest.mark.parametrize(
    "state",
    [
        ProgrammeReleaseState.ABSENT,
        ProgrammeReleaseState.WITHDRAWN,
        ProgrammeReleaseState.INVALIDATED,
    ],
)
def test_unavailable_state_is_json_without_rows_but_not_a_calendar_download(
    snapshot, state
):
    current = replace(snapshot, state=state, entries=())
    if state is not ProgrammeReleaseState.INVALIDATED:
        current = replace(
            current,
            release_id=None,
            published_at=None,
            pointer_version=0 if state is ProgrammeReleaseState.ABSENT else 2,
        )
    assert json.loads(rendering.render_public_timetable_json(current))["entries"] == []
    with pytest.raises(rendering.TimetableOutputUnavailableError):
        rendering.render_public_timetable_calendar(current)


@pytest.mark.parametrize(
    "changes",
    [
        {"entries": ()},
        {"entries": []},
        {"release_id": None},
        {"release_id": UUID(int=0)},
        {"state": "available"},
        {"state": ProgrammeReleaseState.WITHDRAWN},
        {"pointer_version": True},
        {"pointer_version": -1},
        {"pointer_version": 0},
        {"published_at": None},
        {"checked_at": START.replace(tzinfo=None)},
        {"checked_at": START - timedelta(days=2)},
        {"zone_name": "../UTC"},
        {"zone_name": "Not/AZone"},
    ],
)
def test_invalid_envelope_is_rejected_in_all_formats(snapshot, changes):
    for renderer in (
        rendering.render_public_timetable_json,
        rendering.render_public_timetable_calendar,
    ):
        with pytest.raises(rendering.TimetableOutputInvalidError):
            renderer(replace(snapshot, **changes))


def test_no_generic_dict_or_other_audience_can_be_serialized(snapshot):
    with pytest.raises(rendering.TimetableOutputInvalidError):
        rendering.render_public_timetable_json(asdict(snapshot))


@pytest.mark.parametrize(
    "changes",
    [
        {"occurrence_id": UUID(int=0)},
        {"occurrence_id": "private-id"},
        {"starts_at": START.replace(tzinfo=None)},
        {"ends_at": START},
        {"day_ends_at": START - timedelta(hours=1)},
        {"copy": {"private": "secret"}},
        {"room": None},
    ],
)
def test_invalid_row_shape_and_geometry_is_rejected(snapshot, changes):
    current = replace(snapshot, entries=(replace(snapshot.entries[0], **changes),))
    for renderer in (
        rendering.render_public_timetable_json,
        rendering.render_public_timetable_calendar,
    ):
        with pytest.raises(rendering.TimetableOutputInvalidError):
            renderer(current)


@pytest.mark.parametrize(
    "text", ["", " ", "x" * 241, "private\x00text", "private\x7ftext", "\ud800"]
)
def test_invalid_public_text_is_rejected_without_echoing_content(snapshot, text):
    row = snapshot.entries[0]
    current = replace(
        snapshot, entries=(replace(row, copy=replace(row.copy, title=text)),)
    )
    with pytest.raises(rendering.TimetableOutputInvalidError) as caught:
        rendering.render_public_timetable_calendar(current)
    assert (
        str(caught.value)
        == "A complete bounded audience-specific timetable is required."
    )


def test_duplicate_and_overflow_rows_are_not_silently_truncated(snapshot, monkeypatch):
    with pytest.raises(rendering.TimetableOutputInvalidError):
        rendering.render_public_timetable_json(
            replace(snapshot, entries=snapshot.entries * 2)
        )
    monkeypatch.setattr(rendering, "MAX_OCCURRENCES", 0)
    with pytest.raises(rendering.TimetableOutputInvalidError):
        rendering.render_public_timetable_json(snapshot)


@pytest.mark.parametrize(
    "renderer",
    [
        rendering.render_public_timetable_json,
        rendering.render_public_timetable_calendar,
    ],
)
def test_exact_byte_bound_is_inclusive_and_never_returns_partial_bytes(
    snapshot, monkeypatch, renderer
):
    complete = renderer(snapshot)
    monkeypatch.setattr(rendering, "MAX_TIMETABLE_OUTPUT_BYTES", len(complete))
    assert renderer(snapshot) == complete
    monkeypatch.setattr(rendering, "MAX_TIMETABLE_OUTPUT_BYTES", len(complete) - 1)
    with pytest.raises(rendering.TimetableOutputInvalidError):
        renderer(snapshot)


def test_calendar_does_not_silently_round_event_instants(snapshot):
    entry = replace(snapshot.entries[0], starts_at=START.replace(microsecond=1))
    with pytest.raises(rendering.TimetableOutputInvalidError):
        rendering.render_public_timetable_calendar(replace(snapshot, entries=(entry,)))
