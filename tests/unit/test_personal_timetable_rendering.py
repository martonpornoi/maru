"""Closed private serialization preserves personal state without audience mixing."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from maru.events.personal_timetable_queries import PersonalTimetableEditionLabel
from maru.programme.timetable_queries import PersonalHostPurpose
from maru.scheduling import output_rendering as public_formats
from maru.scheduling import personal_output_rendering as formats
from maru.scheduling.output_rendering import TimetableOutputInvalidError
from maru.scheduling.personal_output_queries import (
    PersonalHostingLayer,
    PersonalTimetable,
)
from maru.scheduling.personal_release_references import (
    PersonalHostPresence,
    PersonalHostReleaseReference,
)
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from maru.scheduling.time_rules import SchedulingEnvelope
from maru.venues.programme_output_queries import ReleasedRoomWayfinding
from maru.workforce.timetable_queries import (
    PersonalShiftInstructions,
    PersonalShiftTimetableEntry,
)


@pytest.fixture
def personal():
    day = datetime(2030, 8, 2, 8, tzinfo=UTC)
    purpose = PersonalHostPurpose(
        UUID(int=5),
        UUID(int=6),
        "host",
        "confirmed",
        2,
        1,
        "Host-only session",
        "Private host instructions",
    )
    presence = PersonalHostPresence(
        UUID(int=5),
        UUID(int=7),
        UUID(int=8),
        UUID(int=9),
        UUID(int=10),
        day,
        day + timedelta(hours=12),
        day + timedelta(minutes=45),
        day + timedelta(hours=2, minutes=15),
        SchedulingEnvelope(
            day + timedelta(minutes=30),
            day + timedelta(hours=1),
            day + timedelta(hours=2),
            day + timedelta(hours=2, minutes=30),
        ),
    )
    reference = PersonalHostReleaseReference(
        State.AVAILABLE,
        1,
        UUID(int=4),
        day - timedelta(days=1),
        "Europe/Budapest",
        (purpose,),
        (presence,),
    )
    room = ReleasedRoomWayfinding(UUID(int=9), 2, 1, "Main Stage", "Convention Hotel")
    instructions = PersonalShiftInstructions(
        UUID(int=11),
        3,
        "open",
        "Operations work",
        "Current desk label",
        "Private handover instructions",
        "Ask the lead",
        UUID(int=12),
        "Events",
        "Stage team",
    )
    shift = PersonalShiftTimetableEntry(
        UUID(int=13),
        2,
        "confirmed",
        day + timedelta(hours=4),
        day + timedelta(hours=8),
        day + timedelta(hours=9),
        instructions,
    )
    return PersonalTimetable(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        day,
        "Europe/Budapest",
        PersonalHostingLayer(reference, (room,)),
        (shift,),
    )


def document(personal):
    return json.loads(formats.render_personal_timetable_json(personal))


def test_current_edition_context_is_closed_versioned_and_calendar_escaped(personal):
    label = PersonalTimetableEditionLabel("Synthetic Con; edition", 3)
    changed = replace(personal, edition_label=label)
    assert document(changed)["edition_label"] == {"name": label.name, "version": 3}
    assert b"X-MARU-EDITION-NAME:Synthetic Con\\; edition" in (
        formats.render_personal_timetable_calendar(changed)
    )
    with pytest.raises(TimetableOutputInvalidError):
        document(replace(changed, hosting=None, shifts=()))
    with pytest.raises(TimetableOutputInvalidError):
        document(replace(changed, edition_label={"name": "untrusted"}))
    with pytest.raises(TimetableOutputInvalidError):
        document(replace(changed, hosting=object(), shifts=()))


def test_private_document_retains_separate_host_and_work_source_meaning(personal):
    data = document(personal)
    assert data["contract"] == "scheduling.personal-timetable@1"
    assert data["audience"] == "exact_person"
    assert data["attendance_evidence"] is False
    assert data["hosting"]["release_id"] == str(personal.hosting.reference.release_id)
    assert data["hosting"]["purposes"][0]["briefing"] == "Private host instructions"
    assert (
        data["hosting"]["presences"][0]["starts_at"]
        != data["hosting"]["presences"][0]["envelope"]["setup_starts_at"]
    )
    assert data["shifts"][0]["starts_at"] == personal.shifts[0].starts_at.isoformat()
    assert data["shifts"][0]["instructions"]["version"] == 3
    assert data["shifts"][0]["version"] == 2
    assert data["work_time_source"] == "retained_shift_commitment"
    assert set(data["hosting"]["purposes"][0]) == {
        "host_id",
        "item_id",
        "role",
        "state",
        "version",
        "invitation_sequence",
        "title",
        "briefing",
    }


@pytest.mark.parametrize("state", ["claimed", "confirmed", "removed", "completed"])
def test_retained_work_states_and_intervals_are_not_changed_by_serialization(
    personal, state
):
    changed = replace(personal, shifts=(replace(personal.shifts[0], status=state),))
    data = document(changed)
    assert data["shifts"][0]["status"] == state
    assert data["shifts"][0]["ends_at"] == personal.shifts[0].ends_at.isoformat()


def test_unadopted_layer_and_empty_adopted_layer_are_distinct(personal):
    assert document(replace(personal, hosting=None))["hosting"] is None
    assert document(replace(personal, shifts=()))["shifts"] == []
    assert document(replace(personal, shifts=None))["shifts"] is None
    with pytest.raises(TimetableOutputInvalidError):
        document(replace(personal, hosting=None, shifts=None))


def test_pending_host_has_no_invented_release_identity_or_presence(personal):
    reference = personal.hosting.reference
    pending = replace(
        reference,
        state=None,
        pointer_version=None,
        release_id=None,
        published_at=None,
        presences=(),
        purposes=(replace(reference.purposes[0], state="invited"),),
    )
    data = document(replace(personal, hosting=PersonalHostingLayer(pending, ())))
    assert data["hosting"]["state"] is None
    assert data["hosting"]["presences"] == []
    assert data["hosting"]["purposes"][0]["state"] == "invited"


@pytest.mark.parametrize("state", [State.ABSENT, State.WITHDRAWN, State.INVALIDATED])
def test_unavailable_host_release_preserves_work_without_room_or_presence(
    personal, state
):
    reference = replace(personal.hosting.reference, state=state, presences=())
    if state is not State.INVALIDATED:
        reference = replace(
            reference,
            release_id=None,
            published_at=None,
            pointer_version=0 if state is State.ABSENT else 2,
        )
    changed = replace(personal, hosting=PersonalHostingLayer(reference, ()))
    data = document(changed)
    assert data["hosting"]["presences"] == data["hosting"]["rooms"] == []
    assert data["shifts"] == document(personal)["shifts"]


@pytest.mark.parametrize(
    "broken",
    [
        "dictionary",
        "no_actor",
        "bad_zone",
        "naive",
        "wrong_work",
        "duplicate_work",
        "no_room",
        "pending_presence",
        "withdrawn_presence",
    ],
)
def test_malformed_or_cross_audience_sources_fail_closed(personal, broken):
    row = personal.shifts[0]
    layer = personal.hosting
    cases = {
        "dictionary": asdict(personal),
        "no_actor": replace(personal, actor_id=UUID(int=0)),
        "bad_zone": replace(personal, zone_name="Not/AZone"),
        "naive": replace(personal, checked_at=personal.checked_at.replace(tzinfo=None)),
        "wrong_work": replace(personal, shifts=({"status": "confirmed"},)),
        "duplicate_work": replace(personal, shifts=(row, row)),
        "no_room": replace(personal, hosting=replace(layer, rooms=())),
        "pending_presence": replace(
            personal,
            hosting=replace(
                layer,
                reference=replace(
                    layer.reference,
                    purposes=(replace(layer.reference.purposes[0], state="invited"),),
                ),
            ),
        ),
        "withdrawn_presence": replace(
            personal,
            hosting=replace(
                layer, reference=replace(layer.reference, state=State.WITHDRAWN)
            ),
        ),
    }
    with pytest.raises(TimetableOutputInvalidError):
        document(cases[broken])


def test_private_projection_cannot_enter_public_serializer(personal):
    with pytest.raises(TimetableOutputInvalidError):
        public_formats.render_public_timetable_json(personal)


def test_document_is_deterministic_and_bounded(personal, monkeypatch):
    second = replace(personal.shifts[0], commitment_id=UUID(int=14))
    a = replace(personal, shifts=(*personal.shifts, second))
    b = replace(a, shifts=tuple(reversed(a.shifts)))
    assert formats.render_personal_timetable_json(
        a
    ) == formats.render_personal_timetable_json(b)
    monkeypatch.setattr(public_formats, "MAX_TIMETABLE_OUTPUT_BYTES", 10)
    with pytest.raises(TimetableOutputInvalidError):
        document(personal)


def test_private_calendar_separates_host_presence_and_current_work_instructions(
    personal,
):
    payload = formats.render_personal_timetable_calendar(personal)
    text = payload.decode().replace("\r\n ", "")
    events = text.split("BEGIN:VEVENT\r\n")[1:]
    assert len(events) == 2
    host, work = events
    assert "DTSTART:20300802T084500Z" in host
    assert "DTEND:20300802T101500Z" in host
    assert "LOCATION:Convention Hotel / Main Stage" in host
    assert "LOCATION:" not in work
    assert "Current location label: Current desk label" in work
    assert "not a snapshot of accepted location" in work
    assert "DTSTART:20300802T120000Z" in work
    assert "CLASS:PRIVATE" in host
    assert "CLASS:PRIVATE" in work
    for forbidden in ("METHOD:", "ATTENDEE", "ORGANIZER", "BEGIN:VALARM", "RRULE:"):
        assert forbidden not in text
    assert all(len(line) <= 75 for line in payload.split(b"\r\n"))


@pytest.mark.parametrize(
    ("state", "status", "transparency"),
    [
        ("claimed", "TENTATIVE", "OPAQUE"),
        ("confirmed", "CONFIRMED", "OPAQUE"),
        ("removed", "CANCELLED", "TRANSPARENT"),
        ("completed", "CONFIRMED", "TRANSPARENT"),
    ],
)
def test_calendar_keeps_work_lifecycle_and_stable_identity(
    personal, state, status, transparency
):
    snapshot = replace(
        personal, hosting=None, shifts=(replace(personal.shifts[0], status=state),)
    )
    text = (
        formats.render_personal_timetable_calendar(snapshot)
        .decode()
        .replace("\r\n ", "")
    )
    assert f"STATUS:{status}\r\n" in text
    assert f"TRANSP:{transparency}\r\n" in text
    assert f"X-MARU-WORK-STATE:{state}" in text
    assert f"UID:shift-{personal.shifts[0].commitment_id}@maru.invalid" in text
    assert "not attendance evidence" in text


@pytest.mark.parametrize("state", [State.WITHDRAWN, State.INVALIDATED])
def test_combined_calendar_does_not_hide_broken_hosting_behind_valid_work(
    personal, state
):
    reference = replace(personal.hosting.reference, state=state, presences=())
    if state is State.WITHDRAWN:
        reference = replace(
            reference, release_id=None, published_at=None, pointer_version=2
        )
    snapshot = replace(personal, hosting=PersonalHostingLayer(reference, ()))
    assert document(snapshot)["shifts"]
    with pytest.raises(formats.PersonalCalendarUnavailableError):
        formats.render_personal_timetable_calendar(snapshot)


def test_private_calendar_escapes_unicode_and_property_injection(personal):
    row = personal.shifts[0]
    hostile = "猫,;\\" * 80 + "\r\nATTENDEE:synthetic@example.invalid"
    snapshot = replace(
        personal,
        hosting=None,
        shifts=(
            replace(row, instructions=replace(row.instructions, briefing=hostile)),
        ),
    )
    payload = formats.render_personal_timetable_calendar(snapshot)
    text = payload.decode().replace("\r\n ", "")
    assert "\r\nATTENDEE:" not in text
    assert "\\nATTENDEE:" in text
    assert "猫\\,\\;\\\\" in text
    assert all(len(line) <= 75 for line in payload.split(b"\r\n"))
