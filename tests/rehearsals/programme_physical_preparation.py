"""Actual owner commands for reciprocal holds and explicit synthetic fit decisions."""

from dataclasses import asdict, replace
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _request, _selected, _snapshot
from tests.rehearsals.programme_room_preparation import ACCESS_BARRIERS, ACCESS_FEATURES
from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role

REASON = "Synthetic exact physical hold; not Programme approval or publication."


class ProgrammePhysicalPreparationError(RuntimeError):
    """Expose a bounded fixture failure, never private owner facts."""


def _require(condition, code):
    if not condition:
        raise ProgrammePhysicalPreparationError(code)


def approve_room_roles(setup, planning, reviewer):
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415
    from maru.authorization.programme_role_scope_choices import (  # noqa: PLC0415
        load_programme_role_scope_choices,
    )
    from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

    choices = load_programme_role_scope_choices(
        actor=setup.controllers[0].authenticate(),
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )
    grants = []
    for room in planning.room_ids:
        matches = [
            c.scope
            for c in choices.choices
            if c.scope.level == ScopeLevel.RESOURCE
            and c.scope.department_id == setup.department_id
            and c.scope.resource_kind == "venue.edition_space"
            and c.scope.resource_binding_id == edition_space_binding_id(room)
        ]
        _require(len(matches) == 1, "physical_room_scope_unavailable")
        scope = matches[0]
        grants.append(
            approve_synthetic_role(
                setup,
                people=setup.controllers,
                recipient=reviewer,
                code="room-operations",
                level=scope.level,
                department_id=scope.department_id,
                resource_binding_id=scope.resource_binding_id,
                resource_kind=scope.resource_kind,
            )
        )
    grants.append(
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=planning.planner,
            code="delivery",
            level=ScopeLevel.EDITION,
        )
    )
    return tuple(grants)


def _hold(setup, planning, occurrence):
    from maru.scheduling.planning_reservations import (  # noqa: PLC0415
        load_scheduling_reservation_review,
    )

    return load_scheduling_reservation_review(
        _request(setup, planning.planner, read=True), occurrence_id=occurrence
    )


def _approve(setup, person, hold, *, version=None):
    from maru.venues.services import approve_venue_booking  # noqa: PLC0415

    return approve_venue_booking(
        actor=person.authenticate(),
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        space_selection_id=hold.space_selection_id,
        booking_id=hold.booking_id,
        expected_version=hold.booking_version if version is None else version,
        reason="Reviewed exact fictional room use independently of its author.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="programme_rehearsal",
    )


def reserve_and_approve(setup, planning, reviewer):
    from maru.scheduling.catalogs import SchedulingOperation  # noqa: PLC0415
    from maru.scheduling.reservation_commands import (  # noqa: PLC0415
        SchedulingReservationInput,
        change_scheduling_reservation,
    )
    from maru.venues.services import (  # noqa: PLC0415
        VenueIndependentApprovalError,
        VenueVersionConflictError,
    )

    snapshot = _snapshot(setup, planning.planner, planning.candidate_id)
    candidate = _selected(snapshot, planning.candidate_id)
    _require(
        (candidate.revision_id, candidate.version)
        == (planning.candidate_revision_id, planning.candidate_version),
        "physical_candidate_changed",
    )
    placements = {p.id: p for p in snapshot.placements}
    _require(
        set(placements) == set(planning.placement_ids), "physical_manifest_changed"
    )
    intents, bookings, versions = [], [], []
    for occurrence, placement in zip(
        planning.occurrence_ids, planning.placement_ids, strict=True
    ):
        selected = placements[placement]
        _require(
            selected.occurrence_id == occurrence
            and selected.space_id in planning.room_ids,
            "physical_placement_changed",
        )
        before = _hold(setup, planning, occurrence)
        _require(
            before.state == "not_requested" and before.active is None,
            "physical_unexpected_prior_hold",
        )
        request = replace(_request(setup, planning.planner), reason=REASON)
        intent = SchedulingReservationInput(
            planning.candidate_id, planning.candidate_version, placement
        )
        result = change_scheduling_reservation(
            request,
            reservation=intent,
            operation=SchedulingOperation.RESERVATION_REPLACE,
        )
        replay = change_scheduling_reservation(
            request,
            reservation=intent,
            operation=SchedulingOperation.RESERVATION_REPLACE,
        )
        _require(
            replay.replayed and replace(replay, replayed=False) == result,
            "physical_retry_changed",
        )
        current = _hold(setup, planning, occurrence)
        hold = current.active
        _require(
            current.state == "active"
            and hold is not None
            and hold.candidate_id == planning.candidate_id
            and hold.candidate_version == planning.candidate_version
            and hold.placement_id == placement
            and hold.space_selection_id == selected.space_id
            and hold.envelope == selected.envelope
            and hold.review_state == "draft",
            "physical_reciprocal_hold_missing",
        )
        try:
            _approve(setup, planning.planner, hold)
        except VenueIndependentApprovalError:
            pass
        else:
            raise ProgrammePhysicalPreparationError("physical_self_approval_accepted")
        _require(
            _hold(setup, planning, occurrence) == current, "physical_denial_mutated"
        )
        approved = _approve(setup, reviewer, hold)
        try:
            _approve(setup, reviewer, hold)
        except VenueVersionConflictError:
            pass
        else:
            raise ProgrammePhysicalPreparationError("physical_stale_approval_accepted")
        after = _hold(setup, planning, occurrence)
        _require(
            approved.object_id == hold.booking_id
            and approved.resulting_version == hold.booking_version + 1
            and after.state == "active"
            and after.active
            == replace(
                hold,
                booking_version=approved.resulting_version,
                review_state="approved",
            ),
            "physical_independent_approval_missing",
        )
        intents.append(result.object_id)
        bookings.append(approved.object_id)
        versions.append(approved.resulting_version)
    final = _snapshot(setup, planning.planner, planning.candidate_id)
    _require(
        _selected(final, planning.candidate_id) == candidate
        and final.placements == snapshot.placements,
        "physical_hold_edited_candidate",
    )
    return tuple(intents), tuple(bookings), tuple(versions)


def _assess_fictional_facts(preview, room):
    physical = preview.physical_source
    _require(
        preview.accessibility_delivery
        == "Keep clear wheelchair access and a quiet exit; check seating before entry."
        and preview.delivery_revision_id is not None
        and physical is not None
        and physical.selection_id == room
        and physical.configuration_features == ACCESS_FEATURES
        and physical.public_access_info
        == "Fictional level entry; keep the aisle clear."
        and len(physical.members) == 1
        and physical.members[0].features == ACCESS_FEATURES
        and physical.members[0].barriers == ACCESS_BARRIERS,
        "physical_fit_facts_unexpected",
    )


def assess_accessibility(setup, items, planning):
    from maru.programme.commands import ProgrammeVersionConflictError  # noqa: PLC0415
    from maru.programme.placement_commands import (  # noqa: PLC0415
        record_programme_placement_decision,
    )
    from maru.programme.placement_queries import (  # noqa: PLC0415
        ProgrammePlacementReadRequest,
        preview_programme_placement_decision,
    )
    from maru.programme.release_inputs import (  # noqa: PLC0415
        ProgrammePlacementDecisionIntent,
        ProgrammePlacementDecisionKind,
        ProgrammePlacementDecisionState,
        ProgrammePlacementSelection,
    )

    snapshot = _snapshot(setup, planning.planner, planning.candidate_id)
    placements = {p.id: p for p in snapshot.placements}
    blocked, satisfied, digests = [], [], []
    for item, occurrence, placement in zip(
        (items.ceremony, items.accepted, items.accepted),
        planning.occurrence_ids,
        planning.placement_ids,
        strict=True,
    ):
        selection = ProgrammePlacementSelection(
            item.item_id,
            occurrence,
            planning.candidate_id,
            planning.candidate_revision_id,
            placement,
            item.version,
            planning.candidate_version,
            ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT,
        )

        def preview(selection=selection):
            return preview_programme_placement_decision(
                ProgrammePlacementReadRequest(
                    planning.planner.authenticate().id,
                    setup.organization_id,
                    setup.edition_id,
                    uuid4(),
                ),
                selection=selection,
            )

        original = preview()
        _require(
            original.decision_state == "absent" and original.decision_sequence == 0,
            "physical_fit_prior_decision",
        )
        intent = ProgrammePlacementDecisionIntent(
            **asdict(selection),
            expected_decision_sequence=0,
            source_digest=original.source_digest,
            state=ProgrammePlacementDecisionState.BLOCKED,
        )

        def record(intent, reason, key):
            return record_programme_placement_decision(
                actor_id=planning.planner.authenticate().id,
                organization_id=setup.organization_id,
                edition_id=setup.edition_id,
                intent=intent,
                reason=reason,
                idempotency_key=key,
                correlation_id=uuid4(),
                source_channel="programme_rehearsal",
            )

        pending = record(
            intent, "Fictional seating/access inspection not yet accepted.", uuid4()
        )
        current = preview()
        _require(
            current.decision_sequence == 1
            and current.decision_state == "blocked"
            and current.source_digest == original.source_digest,
            "physical_fit_block_not_retained",
        )
        _assess_fictional_facts(current, placements[placement].space_id)
        reason = (
            "Synthetic inspection accepts this declared level entry, wheelchair aisle, "
            "quiet exit and checked seating against the exact fictional delivery needs."
        )
        try:
            record(
                replace(intent, state=ProgrammePlacementDecisionState.SATISFIED),
                reason,
                uuid4(),
            )
        except ProgrammeVersionConflictError:
            pass
        else:
            raise ProgrammePhysicalPreparationError(
                "physical_fit_stale_decision_accepted"
            )
        accepted = replace(
            intent,
            expected_decision_sequence=current.decision_sequence,
            state=ProgrammePlacementDecisionState.SATISFIED,
        )
        key = uuid4()
        result = record(accepted, reason, key)
        replay = record(accepted, reason, key)
        after = preview()
        _require(
            pending.decision_sequence == 1
            and result.decision_sequence == 2
            and result.item_version == item.version
            and replay.replayed
            and replace(replay, replayed=False) == result
            and after.decision_state == "satisfied"
            and after.decision_sequence == 2
            and after.source_digest == current.source_digest,
            "physical_fit_current_decision_missing",
        )
        blocked.append(pending.decision_id)
        satisfied.append(result.decision_id)
        digests.append(after.source_digest)
    return tuple(blocked), tuple(satisfied), tuple(digests)
