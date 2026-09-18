"""Real-signature composition with mocked owners; native outcomes remain deferred."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.authorization import programme_role_scope_choices
from maru.authorization.catalog import ScopeLevel
from maru.programme import placement_commands, placement_queries
from maru.programme.commands import ProgrammeVersionConflictError
from maru.programme.placement_commands import ProgrammePlacementCommandResult
from maru.scheduling import planning_reservations, reservation_commands
from maru.scheduling.command_support import SchedulingCommandResult
from maru.scheduling.planning_queries import PlanningCandidate, PlanningPlacement
from maru.scheduling.planning_reservations import (
    PlanningActiveReservation,
    SchedulingReservationReview,
)
from maru.scheduling.time_rules import SchedulingEnvelope
from maru.venues import services
from maru.venues.accessibility_queries import (
    VenueAccessibilityMember,
    VenueAccessibilitySource,
)
from maru.venues.bindings import edition_space_binding_id
from tests.rehearsals import programme_physical_preparation as preparation
from tests.unit.test_programme_physical_scenario import _sources
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_programme_setup_scenarios import _person


def _snapshot(planning, items):
    start = items.availability_starts_at
    envelope = SchedulingEnvelope(
        start,
        start + timedelta(minutes=15),
        start + timedelta(minutes=75),
        start + timedelta(minutes=90),
    )
    placements = tuple(
        PlanningPlacement(
            placement,
            occurrence,
            uuid4(),
            uuid4(),
            room,
            "seated",
            30,
            envelope,
            planning.day_id,
        )
        for placement, occurrence, room in zip(
            planning.placement_ids,
            planning.occurrence_ids,
            (planning.room_ids[0], planning.room_ids[0], planning.room_ids[1]),
            strict=True,
        )
    )
    candidate = PlanningCandidate(
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.candidate_version,
        "Private candidate",
        "draft",
        3,
    )
    return SimpleNamespace(
        candidates=(candidate,),
        selected_candidate_id=candidate.id,
        placements=placements,
    )


@pytest.mark.parametrize("bad_scope", [False, True])
def test_original_controllers_grant_only_two_exact_rooms_and_explicit_delivery(
    monkeypatch, bad_scope
):
    _authentication(monkeypatch)
    setup, _, _, _, planning = _sources()
    reviewer = _person("reviewer")
    scopes = [
        SimpleNamespace(
            scope=SimpleNamespace(
                level=ScopeLevel.RESOURCE,
                department_id=setup.department_id,
                resource_kind="venue.edition_space",
                resource_binding_id=edition_space_binding_id(room),
            )
        )
        for room in planning.room_ids
    ]
    if bad_scope:
        scopes[0].scope.department_id = uuid4()
    monkeypatch.setattr(
        programme_role_scope_choices,
        "load_programme_role_scope_choices",
        create_autospec(
            programme_role_scope_choices.load_programme_role_scope_choices,
            return_value=SimpleNamespace(choices=scopes),
        ),
    )
    grant = create_autospec(
        preparation.approve_synthetic_role, side_effect=lambda *_a, **_kw: uuid4()
    )
    monkeypatch.setattr(preparation, "approve_synthetic_role", grant)
    if bad_scope:
        with pytest.raises(
            preparation.ProgrammePhysicalPreparationError, match="scope_unavailable"
        ):
            preparation.approve_room_roles(setup, planning, reviewer)
        grant.assert_not_called()
        return
    assert len(preparation.approve_room_roles(setup, planning, reviewer)) == 3
    calls = [c.kwargs for c in grant.call_args_list]
    assert [c["code"] for c in calls] == [
        "room-operations",
        "room-operations",
        "delivery",
    ]
    assert all(c["people"] == setup.controllers for c in calls)
    assert [c["resource_binding_id"] for c in calls[:2]] == [
        edition_space_binding_id(room) for room in planning.room_ids
    ]
    assert all(
        c["recipient"] == reviewer and c["level"] == ScopeLevel.RESOURCE
        for c in calls[:2]
    )
    assert calls[2]["recipient"] == planning.planner
    assert calls[2]["level"] == ScopeLevel.EDITION


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "manifest",
        "prior",
        "retry",
        "reciprocal",
        "self",
        "denial",
        "stale",
        "approved",
        "candidate",
    ],
)
def test_exact_reservations_retry_independence_stale_denial_and_unchanged_manifest(
    monkeypatch, failure
):
    _authentication(monkeypatch)
    setup, _, _, items, planning = _sources()
    reviewer = _person("reviewer")
    snapshot = _snapshot(planning, items)
    final = snapshot
    if failure == "manifest":
        snapshot.placements = snapshot.placements[:2]
    elif failure == "candidate":
        final = SimpleNamespace(**vars(snapshot))
        final.candidates = (replace(snapshot.candidates[0], version=99),)
    monkeypatch.setattr(preparation, "_snapshot", Mock(side_effect=[snapshot, final]))
    holds, results = {}, {}
    by_placement = {p.id: p for p in snapshot.placements}

    def read(request, *, occurrence_id):
        assert (request.actor_id, request.organization_id, request.edition_id) == (
            planning.planner.account_id,
            setup.organization_id,
            setup.edition_id,
        )
        hold = holds.get(occurrence_id)
        return SchedulingReservationReview(
            occurrence_id,
            "active" if hold or failure == "prior" else "not_requested",
            hold,
        )

    def reserve(request, *, reservation, operation):
        assert operation.value == "reservation_replace"
        assert reservation.normalized() is reservation
        if reservation.placement_id in results:
            return replace(
                results[reservation.placement_id], replayed=failure != "retry"
            )
        placement = by_placement[reservation.placement_id]
        holds[placement.occurrence_id] = PlanningActiveReservation(
            planning.candidate_id,
            planning.candidate_version,
            placement.id,
            uuid4() if failure == "reciprocal" else placement.space_id,
            placement.envelope,
            uuid4(),
            1,
            "draft",
        )
        results[placement.id] = SchedulingCommandResult(uuid4(), uuid4(), 1, 10)
        return results[placement.id]

    def approve(**kw):
        occurrence, hold = next(
            (o, h) for o, h in holds.items() if h.booking_id == kw["booking_id"]
        )
        assert kw["organization_id"] == setup.organization_id
        assert kw["edition_id"] == setup.edition_id
        assert kw["space_selection_id"] == hold.space_selection_id
        if kw["actor"].id == planning.planner.account_id and failure != "self":
            if failure == "denial":
                holds[occurrence] = replace(hold, booking_version=2)
            raise services.VenueIndependentApprovalError
        if kw["expected_version"] != hold.booking_version and failure != "stale":
            raise services.VenueVersionConflictError
        holds[occurrence] = replace(hold, booking_version=2, review_state="approved")
        return services.VenueCommandResult(
            hold.booking_id, uuid4(), 9 if failure == "approved" else 2, replayed=False
        )

    reserve_mock = create_autospec(
        reservation_commands.change_scheduling_reservation, side_effect=reserve
    )
    approve_mock = create_autospec(services.approve_venue_booking, side_effect=approve)
    monkeypatch.setattr(
        reservation_commands, "change_scheduling_reservation", reserve_mock
    )
    monkeypatch.setattr(services, "approve_venue_booking", approve_mock)
    monkeypatch.setattr(
        planning_reservations,
        "load_scheduling_reservation_review",
        create_autospec(
            planning_reservations.load_scheduling_reservation_review, side_effect=read
        ),
    )
    if failure:
        with pytest.raises(preparation.ProgrammePhysicalPreparationError):
            preparation.reserve_and_approve(setup, planning, reviewer)
    else:
        intents, bookings, versions = preparation.reserve_and_approve(
            setup, planning, reviewer
        )
        assert len(set(intents)) == len(set(bookings)) == 3
        assert versions == (2, 2, 2)
        assert reserve_mock.call_count == 6
        assert approve_mock.call_count == 9


@pytest.mark.parametrize(
    "failure",
    [None, "needs", "features", "barriers", "missing", "stale", "replay", "final"],
)
def test_explicit_fit_retains_blocked_then_reviewed_decisions_and_rejects_stale_intent(
    monkeypatch, failure
):
    _authentication(monkeypatch)
    setup, _, _, items, planning = _sources()
    snapshot = _snapshot(planning, items)
    monkeypatch.setattr(preparation, "_snapshot", Mock(return_value=snapshot))
    placements = {p.id: p for p in snapshot.placements}
    decisions, retries = {}, {}

    def preview(request, *, selection):
        assert request.actor_id == planning.planner.account_id
        assert selection.validated() is selection
        physical = VenueAccessibilitySource(
            placements[selection.placement_id].space_id,
            1,
            "Seated",
            "unknown" if failure == "features" else preparation.ACCESS_FEATURES,
            "Fictional level entry; keep the aisle clear.",
            (
                VenueAccessibilityMember(
                    uuid4(),
                    1,
                    "Room",
                    preparation.ACCESS_FEATURES,
                    "unverified"
                    if failure == "barriers"
                    else preparation.ACCESS_BARRIERS,
                ),
            ),
            "e" * 64,
        )
        prior = decisions.get(selection.placement_id)
        sequence = 0 if prior is None else prior.decision_sequence
        state = ("absent", "blocked", "satisfied")[sequence]
        return placement_queries.ProgrammePlacementPreview(
            selection,
            "d" * 64,
            sequence,
            "stale" if failure == "final" and sequence == 2 else state,
            uuid4(),
            "unknown"
            if failure == "needs"
            else (
                "Keep clear wheelchair access and a quiet exit; "
                "check seating before entry."
            ),
            None if failure == "missing" else physical,
            staffing_absence_available=False,
        )

    def record(**kw):
        intent = kw["intent"]
        assert intent.validated() is intent
        assert kw["actor_id"] == planning.planner.account_id
        assert (kw["organization_id"], kw["edition_id"]) == (
            setup.organization_id,
            setup.edition_id,
        )
        key = kw["idempotency_key"]
        if key in retries:
            return replace(retries[key], replayed=failure != "replay")
        previous = decisions.get(intent.placement_id)
        sequence = 0 if previous is None else previous.decision_sequence
        if sequence != intent.expected_decision_sequence and failure != "stale":
            raise ProgrammeVersionConflictError
        result = ProgrammePlacementCommandResult(
            uuid4(),
            uuid4(),
            intent.item_id,
            intent.expected_item_version,
            sequence + 1,
            replayed=False,
        )
        decisions[intent.placement_id] = retries[key] = result
        return result

    monkeypatch.setattr(
        placement_queries,
        "preview_programme_placement_decision",
        create_autospec(
            placement_queries.preview_programme_placement_decision, side_effect=preview
        ),
    )
    command = create_autospec(
        placement_commands.record_programme_placement_decision, side_effect=record
    )
    monkeypatch.setattr(
        placement_commands, "record_programme_placement_decision", command
    )
    if failure:
        with pytest.raises(preparation.ProgrammePhysicalPreparationError):
            preparation.assess_accessibility(setup, items, planning)
    else:
        blocked, satisfied, digests = preparation.assess_accessibility(
            setup, items, planning
        )
        assert len(set(blocked + satisfied)) == 6
        assert digests == ("d" * 64,) * 3
        assert command.call_count == 12
        assert all(
            c.kwargs["intent"].kind.value == "accessibility_fit"
            for c in command.call_args_list
        )
