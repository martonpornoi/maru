"""Real selected-room, occurrence and private-alternative timetable composition."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

from tests.rehearsals.programme_items_scenario import items_from_document
from tests.rehearsals.programme_proposal_scenario import proposal_from_document
from tests.rehearsals.programme_review_scenario import review_from_document
from tests.rehearsals.programme_room_preparation import prepare_rooms
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    SyntheticProgrammePerson,
    _create_person,
    approve_synthetic_role,
    person_from_document,
    scenario_from_document,
)

REASON = "Synthetic private timetable comparison; no reservation or release approval."


class ProgrammePlanningScenarioError(RuntimeError):
    """Expose stable bounded stage failures without source data or credentials."""


@dataclass(frozen=True, slots=True)
class ProgrammePlanningScenario:
    """Retain exact private draft/source handles, not a release or room booking."""

    organization_id: UUID
    edition_id: UUID
    item_ids: tuple[UUID, UUID]
    room_ids: tuple[UUID, UUID]
    day_id: UUID
    occurrence_ids: tuple[UUID, UUID, UUID]
    conflicted_candidate_id: UUID
    conflicted_revision_id: UUID
    candidate_id: UUID
    candidate_revision_id: UUID
    candidate_version: int
    placement_ids: tuple[UUID, UUID, UUID]
    evaluation_id: UUID
    planner: SyntheticProgrammePerson = field(repr=False)
    catalog_person: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]


def _request(setup, person, *, read=False):
    from maru.scheduling.inputs import SchedulingCommandRequest  # noqa: PLC0415
    from maru.scheduling.planning_queries import SchedulingReadRequest  # noqa: PLC0415

    common = (person.authenticate().id, setup.organization_id, setup.edition_id)
    if read:
        return SchedulingReadRequest(*common, uuid4())
    return SchedulingCommandRequest(
        *common, uuid4(), uuid4(), REASON, "programme_rehearsal"
    )


def _snapshot(setup, planner, candidate=None):
    from maru.scheduling.planning_queries import (  # noqa: PLC0415
        load_scheduling_planning,
    )

    return load_scheduling_planning(
        _request(setup, planner, read=True), candidate_id=candidate
    )


def _selected(snapshot, candidate_id):
    matching = [c for c in snapshot.candidates if c.id == candidate_id]
    if len(matching) != 1 or snapshot.selected_candidate_id != candidate_id:
        raise ProgrammePlanningScenarioError("planning_candidate_unavailable")
    return matching[0]


def _placement(items, *, occurrence, day, room, host_id, minute, attendance=30):
    from maru.scheduling.inputs import SchedulingPlacementInput  # noqa: PLC0415
    from maru.scheduling.time_rules import (  # noqa: PLC0415
        SchedulingEnvelope,
        SchedulingHostPresence,
    )

    start = items.availability_starts_at + timedelta(minutes=minute)
    end = start + timedelta(hours=1)
    return SchedulingPlacementInput(
        occurrence.object_id,
        occurrence.version,
        day.object_id,
        day.version,
        room,
        SchedulingEnvelope(
            start - timedelta(minutes=15), start, end, end + timedelta(minutes=15)
        ),
        "seated",
        attendance,
        (SchedulingHostPresence(host_id, start, end),),
    ).normalized()


def _evaluate(setup, planner, candidate_id, version, *, conflicted):
    from maru.scheduling.evaluation_commands import (  # noqa: PLC0415
        evaluate_scheduling_candidate,
    )
    from maru.scheduling.planning_review import (  # noqa: PLC0415
        load_scheduling_candidate_review,
    )

    evaluation = evaluate_scheduling_candidate(
        _request(setup, planner), candidate_id=candidate_id, expected_version=version
    )
    report = load_scheduling_candidate_review(
        _request(setup, planner, read=True),
        candidate_id=candidate_id,
        expected_version=version,
    )
    if (
        report.state != "current"
        or report.evaluation_id != evaluation.object_id
        or report.saved_complete is not True
        or not report.current.complete
        or not report.current.sources
        or any(not s.available for s in report.current.sources)
    ):
        raise ProgrammePlanningScenarioError("planning_evaluation_unavailable")
    blockers = {f.code for f in report.current.findings if f.severity == "blocker"}
    if conflicted:
        if not {"candidate_room_overlap", "host_overlap", "venue_capacity"} <= blockers:
            raise ProgrammePlanningScenarioError("planning_conflicts_not_detected")
    elif blockers or any(f.severity == "unavailable" for f in report.current.findings):
        raise ProgrammePlanningScenarioError("planning_corrected_draft_still_blocked")
    # Do not acknowledge warnings or claim deferred staffing/accessibility checks.
    return evaluation.object_id


def _compose_plan(setup, items, planner, rooms):
    from maru.scheduling.candidate_commands import (  # noqa: PLC0415
        copy_scheduling_candidate,
        create_scheduling_candidate,
    )
    from maru.scheduling.command_support import (  # noqa: PLC0415
        SchedulingVersionConflictError,
    )
    from maru.scheduling.day_commands import (  # noqa: PLC0415
        create_scheduling_service_day,
    )
    from maru.scheduling.inputs import (  # noqa: PLC0415
        SchedulingOccurrenceInput,
        SchedulingServiceDayInput,
    )
    from maru.scheduling.occurrence_commands import (  # noqa: PLC0415
        create_scheduling_occurrence,
    )
    from maru.scheduling.placement_commands import (  # noqa: PLC0415
        set_scheduling_placement,
    )
    from maru.scheduling.time_rules import SchedulingWindow  # noqa: PLC0415

    original = _snapshot(setup, planner)
    if (
        original.days
        or original.occurrences
        or original.candidates
        or not original.accepts_writes
    ):
        raise ProgrammePlanningScenarioError("planning_requires_unplanned_edition")
    day = create_scheduling_service_day(
        _request(setup, planner),
        day=SchedulingServiceDayInput(
            "Fictional first service day",
            SchedulingWindow(items.availability_starts_at, items.availability_ends_at),
            15,
        ),
        expected_control_version=original.control_version,
    )
    group = uuid4()
    occurrences = []
    control = day.control_version
    for item, sequence in (
        (items.ceremony, None),
        (items.accepted, 1),
        (items.accepted, 2),
    ):
        occurrence = create_scheduling_occurrence(
            _request(setup, planner),
            occurrence=SchedulingOccurrenceInput(
                item.item_id, group if sequence else None, sequence
            ),
            expected_control_version=control,
        )
        occurrences.append(occurrence)
        control = occurrence.control_version
    draft = create_scheduling_candidate(
        _request(setup, planner),
        label="Fictional comparison - conflicts retained",
        expected_control_version=control,
    )
    version = draft.version
    for index, occurrence in enumerate(occurrences):
        result = set_scheduling_placement(
            _request(setup, planner),
            candidate_id=draft.object_id,
            expected_version=version,
            placement=_placement(
                items,
                occurrence=occurrence,
                day=day,
                room=rooms[index == 2],
                host_id=(items.ceremony if index == 0 else items.accepted).host_id,
                minute=30,
                attendance=120 if index == 1 else 30,
            ),
        )
        version = result.version
    _evaluate(setup, planner, draft.object_id, version, conflicted=True)
    before = _snapshot(setup, planner, draft.object_id)
    original_candidate = _selected(before, draft.object_id)
    alternative = copy_scheduling_candidate(
        _request(setup, planner),
        source_revision_id=original_candidate.revision_id,
        label="Fictional workable alternative",
        expected_control_version=before.control_version,
    )
    copied = _snapshot(setup, planner, alternative.object_id)
    if copied.placements != before.placements:
        raise ProgrammePlanningScenarioError("planning_copy_changed_source")
    version = alternative.version
    for index, minute in ((1, 120), (2, 210)):
        placement = _placement(
            items,
            occurrence=occurrences[index],
            day=day,
            room=rooms[index == 2],
            host_id=items.accepted.host_id,
            minute=minute,
        )
        previous_version = version
        result = set_scheduling_placement(
            _request(setup, planner),
            candidate_id=alternative.object_id,
            expected_version=version,
            placement=placement,
        )
        version = result.version
        if index == 1:
            # An older editing cursor must not overwrite the fresh manifest.
            try:
                set_scheduling_placement(
                    _request(setup, planner),
                    candidate_id=alternative.object_id,
                    expected_version=previous_version,
                    placement=placement,
                )
            except SchedulingVersionConflictError:
                pass
            else:
                raise ProgrammePlanningScenarioError("planning_stale_write_accepted")
    evaluation_id = _evaluate(
        setup, planner, alternative.object_id, version, conflicted=False
    )
    unchanged = _snapshot(setup, planner, draft.object_id)
    if (
        _selected(unchanged, draft.object_id) != original_candidate
        or unchanged.placements != before.placements
    ):
        raise ProgrammePlanningScenarioError("planning_source_draft_changed")
    final = _snapshot(setup, planner, alternative.object_id)
    candidate = _selected(final, alternative.object_id)
    by_occurrence = {p.occurrence_id: p.id for p in final.placements}
    if len(by_occurrence) != 3 or set(by_occurrence) != {
        o.object_id for o in occurrences
    }:
        raise ProgrammePlanningScenarioError("planning_manifest_incomplete")
    return (
        day.object_id,
        tuple(o.object_id for o in occurrences),
        draft.object_id,
        original_candidate.revision_id,
        candidate.id,
        candidate.revision_id,
        candidate.version,
        tuple(by_occurrence[o.object_id] for o in occurrences),
        evaluation_id,
    )


def prepare_planning_scenario(setup, proposal, review, items):
    """Compose exact-room planning with ordinary authorization and native guards."""
    environment = require_programme_runtime_environment()
    proposal = proposal_from_document(
        json.loads(json.dumps(asdict(proposal), default=str)), setup=setup
    )
    review = review_from_document(
        json.loads(json.dumps(asdict(review), default=str)),
        setup=setup,
        proposal=proposal,
    )
    items = items_from_document(
        json.loads(json.dumps(asdict(items), default=str)),
        setup=setup,
        proposal=proposal,
        review=review,
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415

    planner = _create_person("timetable-planner", run_id=environment.run_id)
    catalog_person = _create_person("venue-catalog", run_id=environment.run_id)
    grants = tuple(
        approve_synthetic_role(
            setup, people=setup.controllers, recipient=person, code=code, level=level
        )
        for person, code, level in (
            (planner, "planner", ScopeLevel.EDITION),
            (catalog_person, "venue-catalog", ScopeLevel.ORGANIZATION),
            (catalog_person, "venue-selection", ScopeLevel.EDITION),
        )
    )
    rooms, room_grants = prepare_rooms(setup, items, catalog_person, planner)
    plan = _compose_plan(setup, items, planner, rooms)
    return ProgrammePlanningScenario(
        setup.organization_id,
        setup.edition_id,
        (items.accepted.item_id, items.ceremony.item_id),
        rooms,
        *plan,
        planner,
        catalog_person,
        (*grants, *room_grants),
    )


def _decode_planning(document, *, setup, proposal, review, items):
    values = dict(document)
    for key in ("planner", "catalog_person"):
        values[key] = person_from_document(values[key])
    for key in (
        "item_ids",
        "room_ids",
        "occurrence_ids",
        "placement_ids",
        "role_assignment_ids",
    ):
        values[key] = tuple(UUID(value) for value in values[key])
    for key in tuple(values):
        if key.endswith("_id"):
            values[key] = UUID(values[key])
    result = ProgrammePlanningScenario(**values)
    people = (
        *setup.controllers,
        setup.intake_person,
        proposal.lead,
        proposal.collaborator,
        *review.people,
        items.public_reviewer,
        items.ceremony_host,
        result.planner,
        result.catalog_person,
    )
    if (
        (result.organization_id, result.edition_id)
        != (setup.organization_id, setup.edition_id)
        or result.item_ids != (items.accepted.item_id, items.ceremony.item_id)
        or type(result.candidate_version) is not int
        or result.candidate_version < 1
        or any(
            len(values[key]) != size or len(set(values[key])) != size
            for key, size in (
                ("room_ids", 2),
                ("occurrence_ids", 3),
                ("placement_ids", 3),
                ("role_assignment_ids", 5),
            )
        )
        or len({p.account_id for p in people}) != 15
        or result.candidate_id == result.conflicted_candidate_id
        or result.candidate_revision_id == result.conflicted_revision_id
        or any(isinstance(v, UUID) and not v.int for v in values.values())
        or any(
            not v.int
            for key in (
                "item_ids",
                "room_ids",
                "occurrence_ids",
                "placement_ids",
                "role_assignment_ids",
            )
            for v in values[key]
        )
    ):
        raise ValueError
    return result


def planning_from_document(document, *, setup, proposal, review, items):
    """Validate the private same-source handoff without granting authority."""
    try:
        return _decode_planning(
            document, setup=setup, proposal=proposal, review=review, items=items
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProgrammePlanningScenarioError(
            "synthetic_planning_result_invalid"
        ) from None


def _read_input():
    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError
    document = json.loads(raw)
    if set(document) != {"setup", "proposal", "review", "items"}:
        raise ValueError
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    proposal = proposal_from_document(document["proposal"], setup=setup)
    review = review_from_document(document["review"], setup=setup, proposal=proposal)
    items = items_from_document(
        document["items"], setup=setup, proposal=proposal, review=review
    )
    return setup, proposal, review, items


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_planning_scenario(*_read_input())
    except Exception:  # noqa: BLE001 - fixed private child boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
