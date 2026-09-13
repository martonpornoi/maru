"""Fast closed-graph tests keep operator privacy failures out of slow DB loops."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from maru.programme.operator_queries import OperatorDeliveryInstructions
from maru.programme.output_queries import ReleasedProgrammeCopy
from maru.scheduling import operator_output_rendering as rendering
from maru.scheduling import output_rendering as common
from maru.scheduling.continuity_operator_source import operator_continuity_projection
from maru.scheduling.continuity_protocol import ContinuityInvalidError, ContinuityScope
from maru.scheduling.operator_output_queries import (
    OperatorRunSheet,
    OperatorRunSheetEntry,
)
from maru.scheduling.operator_release_references import (
    OperatorReleaseOccurrence,
    OperatorReleaseReference,
)
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.output_rendering import (
    TimetableOutputInvalidError,
    TimetableOutputUnavailableError,
)
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from maru.scheduling.time_rules import SchedulingEnvelope
from maru.venues.programme_output_queries import ReleasedRoomWayfinding
from maru.workforce.operator_links import OperatorWorkLink
from maru.workforce.operator_queries import (
    OperatorRetainedWork,
    OperatorStaffingDemand,
    OperatorStaffingSnapshot,
)

START = datetime(2030, 8, 2, 22, tzinfo=UTC)
RENDERERS = (
    rendering.render_operator_run_sheet_json,
    rendering.render_operator_run_sheet_calendar,
)


@pytest.fixture
def sheet():
    placement = OperatorReleaseOccurrence(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=5),
        UUID(int=6),
        START - timedelta(hours=8),
        START + timedelta(hours=4),
        SchedulingEnvelope(
            START - timedelta(minutes=30),
            START,
            START + timedelta(hours=1),
            START + timedelta(hours=2),
        ),
    )
    entry = OperatorRunSheetEntry(
        placement,
        ReleasedProgrammeCopy(
            UUID(int=4), "Opening", "Reviewed summary", "Reviewed note"
        ),
        ReleasedRoomWayfinding(UUID(int=5), 2, 3, "Main Stage", "Convention Hall"),
        None,
    )
    reference = OperatorReleaseReference(
        State.AVAILABLE,
        1,
        UUID(int=7),
        START - timedelta(days=1),
        "Europe/Budapest",
        staffing_adopted=False,
        occurrences=(placement,),
    )
    return OperatorRunSheet(
        UUID(int=8),
        UUID(int=9),
        OperatorScopeKind.ROOM,
        UUID(int=5),
        frozenset(),
        START - timedelta(hours=1),
        reference,
        (entry,),
        None,
    )


@pytest.fixture
def full_sheet(sheet):
    row = sheet.entries[0]
    delivery = OperatorDeliveryInstructions(
        row.placement.item_id,
        UUID(int=10),
        2,
        START - timedelta(hours=2),
        "Technical secret",
        "Accessibility secret",
        "Media secret",
    )
    work = OperatorRetainedWork(
        START - timedelta(hours=2), START, START + timedelta(hours=8), "confirmed", 2
    )
    demand = OperatorStaffingDemand(
        UUID(int=11),
        3,
        "open",
        "Stage handover",
        "Backstage",
        "Current work briefing",
        "Current supervision",
        START,
        START + timedelta(hours=1),
        4,
        (work,),
    )
    link = OperatorWorkLink(
        row.placement.occurrence_id,
        UUID(int=12),
        2,
        demand.demand_id,
        demand.version,
        current=False,
    )
    return replace(
        sheet,
        layers=frozenset({"technical", "accessibility", "media", "staffing"}),
        reference=replace(sheet.reference, staffing_adopted=True),
        entries=(replace(row, delivery=delivery),),
        staffing=OperatorStaffingSnapshot(
            adopted=True, links=(link,), demands=(demand,)
        ),
    )


def continuity(sheet, **changes):
    scope = ContinuityScope(
        sheet.organization_id,
        sheet.edition_id,
        "private_operator",
        UUID(int=19),
        sheet.kind.value,
        sheet.target_id,
        tuple(sorted(sheet.layers)),
    )
    return operator_continuity_projection(sheet, scope=replace(scope, **changes))


def test_operator_continuity_preserves_envelope_and_private_layer_choice(sheet):
    result = continuity(sheet)
    entry = result.entries[0]
    assert entry.starts_at == sheet.entries[0].placement.envelope.setup_starts_at
    assert entry.ends_at == sheet.entries[0].placement.envelope.teardown_ends_at
    assert entry.context[1] == START
    assert result.work_status == "unrequested"
    assert "technical" not in {fact.code for fact in entry.facts}


def test_operator_continuity_retains_predecessors_without_inventing_attendance(
    full_sheet,
):
    result = continuity(full_sheet)
    event, demand = result.entries
    facts = {fact.code: fact.value for fact in event.facts}
    assert facts["technical"] == "Technical secret"
    assert facts["accessibility"] == "Accessibility secret"
    assert facts["media"] == "Media secret"
    assert "version 2" in facts["delivery_version"]
    work = {fact.code: fact.value for fact in demand.facts}
    assert demand.starts_at == START
    assert "retained predecessor, not cancelled" in work["programme_link"]
    assert (START - timedelta(hours=2)).isoformat() in work["retained_work"]
    assert "2 confirmed" in work["retained_work"]
    assert "Not attendance evidence" in work["retained_work"]
    assert work["required_headcount"] == "4"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", UUID(int=20)),
        ("edition_id", UUID(int=20)),
        ("target_id", UUID(int=20)),
        ("kind", "department"),
        ("layers", ("technical",)),
    ],
)
def test_operator_continuity_rejects_scope_or_field_mismatch(sheet, field, value):
    with pytest.raises(ContinuityInvalidError):
        continuity(sheet, **{field: value})


def test_operator_continuity_never_omits_a_broken_requested_layer(full_sheet):
    with pytest.raises(TimetableOutputInvalidError):
        continuity(replace(full_sheet, staffing=None))


def test_base_graph_is_closed_private_and_contains_no_unrequested_fields(sheet):
    data = json.loads(rendering.render_operator_run_sheet_json(sheet))
    assert data["audience"] == "private_operator"
    assert data["contract"] == "scheduling.operator-run-sheet@1"
    assert data["requested_layers"] == []
    assert data["staffing"] is None
    entry = data["entries"][0]
    assert entry["delivery"] is None
    assert set(entry) == {"placement", "copy", "wayfinding", "delivery"}
    assert set(entry["copy"]) == {"rendition_id", "title", "summary", "content_note"}
    assert "technical" not in json.dumps(data)
    assert "account_id" not in json.dumps(data)
    assert "reason" not in json.dumps(data)
    assert data["scope_id"] == str(sheet.target_id)
    assert entry["placement"]["effective_ends_at"] == "2030-08-02T23:00:00+00:00"


def test_owner_versions_and_predecessor_work_terms_remain_independent(full_sheet):
    data = json.loads(rendering.render_operator_run_sheet_json(full_sheet))
    assert data["entries"][0]["delivery"]["technical"] == "Technical secret"
    assert data["entries"][0]["delivery"]["version"] == 2
    assert data["entries"][0]["wayfinding"]["space_version"] == 2
    assert data["entries"][0]["wayfinding"]["venue_version"] == 3
    assert data["staffing"]["links"][0]["current"] is False
    demand = data["staffing"]["demands"][0]
    assert demand["starts_at"] != demand["retained_work"][0]["starts_at"]
    assert demand["required_headcount"] == 4
    assert demand["retained_work"][0]["count"] == 2
    assert "account_id" not in json.dumps(data)
    assert "commitment_id" not in json.dumps(data)


def test_calendar_is_private_context_not_a_personal_assignment_or_invitation(
    full_sheet,
):
    encoded = rendering.render_operator_run_sheet_calendar(full_sheet)
    assert encoded == rendering.render_operator_run_sheet_calendar(full_sheet)
    unfolded = encoded.decode().replace("\r\n ", "")
    assert "CLASS:PRIVATE\r\nTRANSP:TRANSPARENT" in unfolded
    assert "DTSTART:20300802T213000Z" in unfolded
    assert "DTEND:20300803T000000Z" in unfolded
    assert "UID:programme-operator-room-" in unfolded
    assert "Retained predecessor" in unfolded
    assert "Retained confirmed count 2: 2030-08-02T20:00:00+00:00" in unfolded
    for forbidden in (
        "ATTENDEE:",
        "ORGANIZER:",
        "METHOD:",
        "URL:",
        "RRULE:",
        "BEGIN:VALARM",
    ):
        assert forbidden not in unfolded
    for line in encoded.split(b"\r\n"):
        assert len(line) <= 75


def test_calendar_escapes_injection_and_folds_multibyte_text(sheet):
    row = sheet.entries[0]
    hostile = "日" * 70 + "\nATTENDEE:evil;one,two\\three"
    changed = replace(
        sheet, entries=(replace(row, copy=replace(row.copy, summary=hostile)),)
    )
    encoded = rendering.render_operator_run_sheet_calendar(changed)
    unfolded = encoded.decode().replace("\r\n ", "")
    assert "\r\nATTENDEE:" not in unfolded
    assert "\\nATTENDEE:evil\\;one\\,two\\\\three" in unfolded
    for line in encoded.split(b"\r\n"):
        assert len(line) <= 75
        line.decode("utf-8")


@pytest.mark.parametrize("state", [State.ABSENT, State.WITHDRAWN, State.INVALIDATED])
def test_nonavailable_states_are_empty_and_never_download_calendars(sheet, state):
    reference = replace(
        sheet.reference,
        state=state,
        occurrences=(),
        pointer_version=0 if state is State.ABSENT else 2,
        release_id=sheet.reference.release_id if state is State.INVALIDATED else None,
        published_at=sheet.reference.published_at
        if state is State.INVALIDATED
        else None,
    )
    changed = replace(sheet, reference=reference, entries=())
    assert (
        json.loads(rendering.render_operator_run_sheet_json(changed))["entries"] == []
    )
    with pytest.raises(TimetableOutputUnavailableError):
        rendering.render_operator_run_sheet_calendar(changed)


def test_empty_available_scope_is_not_an_absent_or_unadopted_release(sheet):
    empty = replace(
        sheet, reference=replace(sheet.reference, occurrences=()), entries=()
    )
    data = json.loads(rendering.render_operator_run_sheet_json(empty))
    assert data["release_state"] == "available"
    assert data["entries"] == []
    assert b"BEGIN:VEVENT" not in rendering.render_operator_run_sheet_calendar(empty)


@pytest.mark.parametrize(
    "change",
    [
        asdict,
        lambda s: replace(s, organization_id=UUID(int=0)),
        lambda s: replace(s, kind="room"),
        lambda s: replace(s, kind=OperatorScopeKind.EDITION),
        lambda s: replace(s, target_id=UUID(int=99)),
        lambda s: replace(s, layers={"staffing"}),
        lambda s: replace(s, layers=frozenset({"private_roster"})),
        lambda s: replace(s, checked_at=START.replace(tzinfo=None)),
        lambda s: replace(s, reference=replace(s.reference, pointer_version=True)),
        lambda s: replace(s, reference=replace(s.reference, zone_name="not/a/zone")),
        lambda s: replace(s, reference=replace(s.reference, release_id=None)),
        lambda s: replace(s, reference=replace(s.reference, published_at=START)),
        lambda s: replace(s, reference=replace(s.reference, state="available")),
        lambda s: replace(s, reference=replace(s.reference, staffing_adopted=1)),
        lambda s: replace(s, reference=replace(s.reference, occurrences=())),
        lambda s: replace(s, entries=[]),
        lambda s: replace(
            s,
            entries=(s.entries[0], s.entries[0]),
            reference=replace(
                s.reference,
                occurrences=(s.entries[0].placement, s.entries[0].placement),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(
                    s.entries[0], room=replace(s.entries[0].room, space_id=UUID(int=90))
                ),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(
                    s.entries[0],
                    copy=replace(s.entries[0].copy, rendition_id=UUID(int=90)),
                ),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(s.entries[0], copy=replace(s.entries[0].copy, title="\x00")),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(s.entries[0], copy=replace(s.entries[0].copy, title="x" * 241)),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(s.entries[0], room=replace(s.entries[0].room, space_version=0)),
            ),
        ),
        lambda s: replace(s, layers=frozenset({"technical"})),
        lambda s: replace(s, layers=frozenset({"staffing"})),
    ],
)
@pytest.mark.parametrize("renderer", RENDERERS)
def test_malformed_cross_audience_or_incomplete_graphs_never_render(
    sheet, change, renderer
):
    with pytest.raises(TimetableOutputInvalidError):
        renderer(change(sheet))


@pytest.mark.parametrize(
    "change",
    [
        lambda s: replace(s, layers=frozenset()),
        lambda s: replace(s, staffing=None),
        lambda s: replace(s, staffing=replace(s.staffing, adopted=False)),
        lambda s: replace(s, staffing=replace(s.staffing, links=())),
        lambda s: replace(s, staffing=replace(s.staffing, demands=())),
        lambda s: replace(
            s, staffing=replace(s.staffing, demands=s.staffing.demands * 2)
        ),
        lambda s: replace(s, staffing=replace(s.staffing, links=s.staffing.links * 2)),
        lambda s: replace(
            s,
            staffing=replace(
                s.staffing,
                links=(replace(s.staffing.links[0], occurrence_id=UUID(int=99)),),
            ),
        ),
        lambda s: replace(
            s,
            staffing=replace(
                s.staffing, links=(replace(s.staffing.links[0], demand_version=10),)
            ),
        ),
        lambda s: replace(
            s,
            staffing=replace(
                s.staffing,
                demands=(replace(s.staffing.demands[0], required_headcount=True),),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(
                    s.entries[0],
                    delivery=replace(s.entries[0].delivery, item_id=UUID(int=99)),
                ),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(
                    s.entries[0],
                    delivery=replace(s.entries[0].delivery, revision_id=None),
                ),
            ),
        ),
        lambda s: replace(
            s,
            entries=(
                replace(
                    s.entries[0],
                    delivery=replace(s.entries[0].delivery, occurred_at=START),
                ),
            ),
        ),
        lambda s: replace(s, layers=frozenset({"technical", "staffing"})),
    ],
)
def test_requested_layer_corruption_never_becomes_a_partial_success(full_sheet, change):
    with pytest.raises(TimetableOutputInvalidError):
        rendering.render_operator_run_sheet_json(change(full_sheet))


@pytest.mark.parametrize("renderer", RENDERERS)
def test_incremental_output_budget_rejects_whole_export_without_truncation(
    sheet, monkeypatch, renderer
):
    monkeypatch.setattr(common, "MAX_TIMETABLE_OUTPUT_BYTES", 100)
    with pytest.raises(TimetableOutputInvalidError):
        renderer(sheet)
