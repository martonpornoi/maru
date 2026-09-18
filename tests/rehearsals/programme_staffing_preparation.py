"""Actual owner commands from accountable starter to independently locked work."""

from datetime import timedelta
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _selected, _snapshot
from tests.rehearsals.programme_setup_scenarios import approve_synthetic_role

CHANNEL = "programme_rehearsal"
REASON = "Explicit fictional Programme staffing; no real convention commitment."


class ProgrammeStaffingPreparationError(RuntimeError):
    """Expose a stable stage failure without private people or owner contents."""


def _require(condition, code):
    if not condition:
        raise ProgrammeStaffingPreparationError(code)


def _route(setup):
    return {
        "organization_id": setup.organization_id,
        "series_id": setup.series_id,
        "edition_id": setup.edition_id,
    }


def _trace():
    return {"correlation_id": uuid4(), "source_channel": CHANNEL}


def approve_starter(setup):
    """Preview actual people, retain intent and obtain only the other own decision."""
    from maru.authorization.services import AuthorizationDenied  # noqa: PLC0415
    from maru.workforce.programme_starter_commands import (  # noqa: PLC0415
        decide_programme_starter,
        request_programme_starter,
    )
    from maru.workforce.programme_starter_creation import (  # noqa: PLC0415
        prepare_programme_starter_creation,
    )
    from maru.workforce.programme_starter_inputs import (  # noqa: PLC0415
        ProgrammeStarterAction,
        ProgrammeStarterScope,
    )
    from maru.workforce.programme_starter_queries import (  # noqa: PLC0415
        load_programme_starter_workspace,
    )
    from maru.workforce.programme_starter_selection import (  # noqa: PLC0415
        ProgrammeStarterDraft,
        verify_programme_starter_selection,
    )

    author, approver = setup.controllers
    scope = ProgrammeStarterScope(**_route(setup))
    draft = ProgrammeStarterDraft(approver.email, REASON, uuid4())
    preview = prepare_programme_starter_creation(
        actor=author.authenticate(), scope=scope, draft=draft, **_trace()
    )
    _require(preview.selection is not None, "staffing_starter_preview_unavailable")
    selected = verify_programme_starter_selection(
        actor_id=author.authenticate().id,
        scope=scope,
        draft=draft,
        proof=preview.selection.proof,
    )
    intent = {
        "scope": scope,
        "details": selected.details,
        "idempotency_key": draft.idempotency_key,
    }
    original = request_programme_starter(
        actor=author.authenticate(), **intent, **_trace()
    )
    retried = request_programme_starter(
        actor=author.authenticate(), **intent, **_trace()
    )
    _require(
        retried.replayed and retried.request_id == original.request_id,
        "staffing_starter_retry_changed",
    )
    decision = {
        "scope": scope,
        "request_id": original.request_id,
        "action": ProgrammeStarterAction.APPROVE,
        "reason": REASON,
        "idempotency_key": uuid4(),
    }
    try:
        decide_programme_starter(actor=author.authenticate(), **decision, **_trace())
    except AuthorizationDenied:
        pass
    else:
        raise ProgrammeStaffingPreparationError("staffing_starter_self_approval")
    own = load_programme_starter_workspace(
        actor=approver.authenticate(),
        scope=scope,
        request_id=original.request_id,
        **_trace(),
    )
    _require(
        len(own.requests) == 1 and own.requests[0].can_approve,
        "staffing_starter_own_review_unavailable",
    )
    result = decide_programme_starter(
        actor=approver.authenticate(), **decision, **_trace()
    )
    retry = decide_programme_starter(
        actor=approver.authenticate(), **decision, **_trace()
    )
    _require(
        retry.replayed
        and retry.template_id == result.template_id
        and result.template_id is not None,
        "staffing_starter_decision_retry_changed",
    )
    return original.request_id, result.template_id


def prepare_position_and_assignment(setup, items, volunteer, template_id):
    """Publish one real Position opportunity and independently assign its applicant."""
    from django.utils import timezone  # noqa: PLC0415

    from maru.workforce.assignment_commands import (  # noqa: PLC0415
        approve_position_assignment,
        propose_position_assignment,
    )
    from maru.workforce.availability_commands import (  # noqa: PLC0415
        save_person_availability,
    )
    from maru.workforce.availability_inputs import (  # noqa: PLC0415
        AvailabilityWindowInput,
    )
    from maru.workforce.models import VolunteerOpportunity  # noqa: PLC0415
    from maru.workforce.queries import project_edition_structure  # noqa: PLC0415
    from maru.workforce.services import submit_volunteer_application  # noqa: PLC0415
    from maru.workforce.structure_commands import (  # noqa: PLC0415
        create_position,
        update_position_opportunity,
    )

    author, approver = setup.controllers
    structure = project_edition_structure(
        organization_id=setup.organization_id, edition_id=setup.edition_id
    )
    _require(structure.state == "complete", "staffing_structure_unavailable")
    create = {
        **_route(setup),
        "template_id": template_id,
        "department_id": setup.department_id,
        "reports_to_id": None,
        "title": "Fictional Programme room volunteer",
        "description": "Prepare the fictional room and support its scheduled session.",
        "headcount": 1,
        "expected_version": structure.aggregate_version,
        "reason": REASON,
        "retry_key": uuid4(),
    }
    position = create_position(actor=author.authenticate(), **create, **_trace())
    retry = create_position(actor=author.authenticate(), **create, **_trace())
    _require(
        retry.replayed and retry.position_id == position.position_id,
        "staffing_position_retry_changed",
    )
    update_position_opportunity(
        actor=author.authenticate(),
        **_route(setup),
        position_id=position.position_id,
        status="published",
        headline="Support fictional Programme sessions",
        description="Apply for this isolated synthetic responsibility only.",
        applications_open_at=None,
        applications_close_at=None,
        visible_when_filled=False,
        expected_version=position.resulting_version,
        reason=REASON,
        **_trace(),
    )
    # Read only the exact public opportunity created by the authorized owner command.
    opportunity = VolunteerOpportunity.objects.get(
        position_id=position.position_id,
        position__organization_id=setup.organization_id,
        position__edition_id=setup.edition_id,
    )
    submit_volunteer_application(
        actor=volunteer.authenticate(),
        opportunity_id=opportunity.id,
        motivation="I choose to help with this fictional rehearsal.",
        correlation_id=uuid4(),
    )
    proposed = propose_position_assignment(
        actor=author.authenticate(),
        **_route(setup),
        position_id=position.position_id,
        account_id=volunteer.account_id,
        effective_from=timezone.now(),
        expires_at=items.availability_ends_at + timedelta(hours=1),
        reason=REASON,
        retry_key=uuid4(),
        **_trace(),
    )
    assignment = approve_position_assignment(
        actor=approver.authenticate(),
        **_route(setup),
        assignment_id=proposed.assignment_id,
        expected_version=proposed.resulting_version,
        reason=REASON,
        retry_key=uuid4(),
        **_trace(),
    )
    _require(assignment.status == "active", "staffing_assignment_not_active")
    save_person_availability(
        actor=volunteer.authenticate(),
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        expected_version=0,
        status="submitted",
        windows=(
            AvailabilityWindowInput(
                items.availability_starts_at, items.availability_ends_at, "available"
            ),
        ),
        retry_key=uuid4(),
        **_trace(),
    )
    return position.position_id, assignment.assignment_id


def approve_staffing_roles(setup, planner):
    """Add only the two existing exact-edition staffing and Workforce recipes."""
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415

    return tuple(
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=planner,
            code=code,
            level=ScopeLevel.EDITION,
        )
        for code in ("staffing", "workforce")
    )


def _read_request(setup, planner, item_id):
    from maru.programme.staffing_queries import (  # noqa: PLC0415
        ProgrammeStaffingReadRequest,
    )

    return ProgrammeStaffingReadRequest(
        planner.authenticate().id,
        setup.organization_id,
        setup.edition_id,
        item_id,
        uuid4(),
        CHANNEL,
    )


def _demand(setup, planner, demand_id):
    from maru.workforce.programme_staffing_queries import (  # noqa: PLC0415
        load_programme_staffing_demand,
    )

    return load_programme_staffing_demand(
        actor_id=planner.authenticate().id,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        demand_id=demand_id,
        correlation_id=uuid4(),
    )


def _create_bound_work(setup, planning, position_id, snapshot, occurrence, placement):
    from maru.programme.staffing_commands import (  # noqa: PLC0415
        change_programme_staffing_requirement,
    )
    from maru.programme.staffing_inputs import (  # noqa: PLC0415
        ProgrammeStaffingChange,
        ProgrammeStaffingExpectation,
        ProgrammeStaffingSource,
    )
    from maru.programme.staffing_queries import (  # noqa: PLC0415
        load_programme_staffing_requirements,
    )
    from maru.workforce.programme_binding import (  # noqa: PLC0415
        apply_programme_staffing_binding,
        preview_programme_staffing_binding,
    )
    from maru.workforce.programme_impact import ProgrammeStaffingAction  # noqa: PLC0415
    from maru.workforce.programme_staffing_inputs import (  # noqa: PLC0415
        ProgrammeStaffingBindingChange,
    )

    planner = planning.planner
    overview = load_programme_staffing_requirements(
        _read_request(setup, planner, occurrence.item_id)
    )
    expectation = ProgrammeStaffingExpectation(
        position_id,
        "Fictional room preparation and session support",
        "Report at the assigned fictional session room",
        "Check the clear aisle before delivery; help the host, then reset the room.",
        "Ask the fictional Programme organizer for support.",
        placement.envelope.setup_starts_at,
        placement.envelope.teardown_ends_at,
        required_headcount=1,
        break_minutes=10,
        minimum_rest_minutes=0,
    )
    requirement = change_programme_staffing_requirement(
        actor_id=planner.authenticate().id,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        change=ProgrammeStaffingChange(
            occurrence.item_id,
            occurrence.id,
            None,
            overview.item_version,
            0,
            occurrence.version,
            snapshot.edition_version,
            expectation,
        ),
        reason=REASON,
        idempotency_key=uuid4(),
        **_trace(),
    )
    source = ProgrammeStaffingSource(
        requirement.requirement_id,
        requirement.revision_id,
        requirement.resulting_requirement_version,
        occurrence.id,
        occurrence.version,
        planning.candidate_id,
        planning.candidate_revision_id,
        placement.id,
    )
    change = ProgrammeStaffingBindingChange(ProgrammeStaffingAction.CREATE, source)
    preview = preview_programme_staffing_binding(
        _read_request(setup, planner, occurrence.item_id), change=change
    )
    _require(
        preview.demand is None and preview.impact.retained_commitments == 0,
        "staffing_creation_has_retained_work",
    )
    bound = apply_programme_staffing_binding(
        planner.authenticate(),
        _read_request(setup, planner, occurrence.item_id),
        change=change,
        preview_digest=preview.digest,
        reason=REASON,
        retry_key=uuid4(),
    )
    draft = _demand(setup, planner, bound.demand_id)
    _require(
        draft.status == "draft" and draft.retained_commitments == 0,
        "staffing_binding_created_commitment",
    )
    return requirement, bound


def _claim_confirm_lock(setup, planner, volunteer, demand_id):
    from maru.workforce.shift_commands import (  # noqa: PLC0415
        ShiftAuthorizationDeniedError,
        ShiftVersionConflictError,
        claim_shift,
        confirm_shift_commitment,
        lock_shift_demand,
        open_shift_demand,
    )

    draft = _demand(setup, planner, demand_id)
    opened = open_shift_demand(
        actor=planner.authenticate(),
        **_route(setup),
        demand_id=demand_id,
        expected_version=draft.version,
        reason=REASON,
        retry_key=uuid4(),
        **_trace(),
    )
    claim_args = {
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
        "demand_id": demand_id,
        "expected_version": opened.resulting_version,
        "retry_key": uuid4(),
    }
    claimed = claim_shift(actor=volunteer.authenticate(), **claim_args, **_trace())
    retry = claim_shift(actor=volunteer.authenticate(), **claim_args, **_trace())
    _require(
        retry.replayed and retry.commitment_id == claimed.commitment_id,
        "staffing_claim_retry_changed",
    )
    current = _demand(setup, planner, demand_id)
    _require(
        current.claimed == 1 and current.confirmed == 0,
        "staffing_claim_was_confirmation",
    )
    decision = {
        **_route(setup),
        "commitment_id": claimed.commitment_id,
        "expected_version": claimed.resulting_version,
        "reason": REASON,
        "retry_key": uuid4(),
    }
    try:
        confirm_shift_commitment(actor=volunteer.authenticate(), **decision, **_trace())
    except ShiftAuthorizationDeniedError:
        pass
    else:
        raise ProgrammeStaffingPreparationError("staffing_self_confirmation_accepted")
    confirmed = confirm_shift_commitment(
        actor=planner.authenticate(), **decision, **_trace()
    )
    stale = dict(decision, retry_key=uuid4())
    try:
        confirm_shift_commitment(actor=planner.authenticate(), **stale, **_trace())
    except ShiftVersionConflictError:
        pass
    else:
        raise ProgrammeStaffingPreparationError("staffing_stale_confirmation_accepted")
    current = _demand(setup, planner, demand_id)
    _require(
        current.claimed == 0 and current.confirmed == 1,
        "staffing_independent_confirmation_missing",
    )
    locked = lock_shift_demand(
        actor=planner.authenticate(),
        **_route(setup),
        demand_id=demand_id,
        expected_version=current.version,
        allow_understaffed=False,
        reason=REASON,
        retry_key=uuid4(),
        **_trace(),
    )
    final = _demand(setup, planner, demand_id)
    _require(
        final.status == "locked" and final.confirmed == 1 and final.claimed == 0,
        "staffing_current_locked_coverage_missing",
    )
    return claimed.commitment_id, confirmed.resulting_version, locked.resulting_version


def prepare_bound_shifts(setup, planning, volunteer, position_id):
    """Explicitly staff all three exact placements without changing their candidate."""
    snapshot = _snapshot(setup, planning.planner, planning.candidate_id)
    candidate = _selected(snapshot, planning.candidate_id)
    _require(
        candidate.revision_id == planning.candidate_revision_id,
        "staffing_candidate_changed",
    )
    occurrences = {row.id: row for row in snapshot.occurrences}
    placements = {row.id: row for row in snapshot.placements}
    results = []
    for occurrence_id, placement_id in zip(
        planning.occurrence_ids, planning.placement_ids, strict=True
    ):
        occurrence, placement = occurrences[occurrence_id], placements[placement_id]
        _require(placement.occurrence_id == occurrence.id, "staffing_placement_changed")
        requirement, binding = _create_bound_work(
            setup, planning, position_id, snapshot, occurrence, placement
        )
        commitment, commitment_version, demand_version = _claim_confirm_lock(
            setup, planning.planner, volunteer, binding.demand_id
        )
        results.append(
            (
                requirement.requirement_id,
                requirement.revision_id,
                binding.binding_id,
                binding.demand_id,
                demand_version,
                commitment,
                commitment_version,
            )
        )
    final = _snapshot(setup, planning.planner, planning.candidate_id)
    _require(
        _selected(final, planning.candidate_id) == candidate
        and final.placements == snapshot.placements,
        "staffing_edited_candidate",
    )
    return tuple(results)
