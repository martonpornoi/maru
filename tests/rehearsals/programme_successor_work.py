"""Actual retained-work succession, never a copied volunteer acceptance."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from tests.rehearsals.programme_planning_scenario import _selected, _snapshot
from tests.rehearsals.programme_release_preparation import _manifest, _require
from tests.rehearsals.programme_staffing_preparation import (
    _claim_confirm_lock,
    _demand,
    _read_request,
    _trace,
)
from tests.rehearsals.programme_staffing_scenario import PreparedProgrammeWork

REASON = (
    "Synthetic earlier aisle inspection requires a separate shift; retain the old "
    "confirmation and require new personal acceptance. No real work is changed."
)


def _own_work(setup, volunteer):
    from maru.scheduling.personal_output_queries import (  # noqa: PLC0415
        load_personal_timetable,
    )

    result = load_personal_timetable(
        actor_id=volunteer.authenticate().id,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        correlation_id=uuid4(),
    )
    _require(result.shifts is not None, "successor_own_work_unavailable")
    return {row.commitment_id: row for row in result.shifts}


def prepare_successor_work(setup, items, planning, staffing, release):
    """Revise one requirement, preview retained impact and obtain a fresh claim."""
    from maru.programme.staffing_commands import (  # noqa: PLC0415
        change_programme_staffing_requirement,
    )
    from maru.programme.staffing_inputs import (  # noqa: PLC0415
        ProgrammeStaffingChange,
    )
    from maru.programme.staffing_queries import (  # noqa: PLC0415
        load_programme_staffing_requirements,
    )
    from maru.scheduling.release_queries import ProgrammeReleaseState  # noqa: PLC0415
    from maru.workforce.programme_binding import (  # noqa: PLC0415
        preview_programme_staffing_binding,
    )
    from maru.workforce.programme_binding_queries import (  # noqa: PLC0415
        load_programme_bindings,
    )
    from maru.workforce.programme_impact import ProgrammeStaffingAction  # noqa: PLC0415
    from maru.workforce.programme_staffing_inputs import (  # noqa: PLC0415
        ProgrammeStaffingBindingChange,
    )

    planner, original = planning.planner, staffing.work[0]
    snapshot = _snapshot(setup, planner, planning.candidate_id)
    candidate = _selected(snapshot, planning.candidate_id)
    _require(
        (candidate.revision_id, candidate.version)
        == (planning.candidate_revision_id, planning.candidate_version),
        "successor_candidate_changed",
    )
    read = _read_request(setup, planner, items.ceremony.item_id)
    overview = load_programme_staffing_requirements(read)
    bindings = load_programme_bindings(read)
    _require(
        len(overview.requirements) == len(bindings) == 1,
        "successor_original_work_unavailable",
    )
    requirement, binding = overview.requirements[0], bindings[0]
    old = _demand(setup, planner, original.demand_id)
    own_before = _own_work(setup, staffing.volunteer)
    _require(
        requirement.requirement_id == original.requirement_id
        and requirement.revision_id == original.requirement_revision_id
        and binding.binding_id == original.binding_id
        and binding.demand_id == original.demand_id
        and binding.source.requirement_id == requirement.requirement_id
        and binding.source.candidate_revision_id == planning.candidate_revision_id
        and binding.source.placement_id == planning.placement_ids[0]
        and old.version == original.demand_version
        and old.status == "locked"
        and old.retained_commitments == old.confirmed == 1
        and old.claimed == 0
        and old.expectation == requirement.expectation
        and original.commitment_id in own_before
        and own_before[original.commitment_id].status == "confirmed",
        "successor_original_work_changed",
    )
    expectation = replace(
        requirement.expectation,
        starts_at=requirement.expectation.starts_at - timedelta(minutes=15),
        briefing=(
            "Inspect the fictional aisle fifteen minutes earlier, "
            "then support the host."
        ),
    ).normalized()
    _require(
        expectation.starts_at >= items.availability_starts_at,
        "successor_outside_shared_availability",
    )
    changed = change_programme_staffing_requirement(
        actor_id=planner.authenticate().id,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
        change=ProgrammeStaffingChange(
            items.ceremony.item_id,
            planning.occurrence_ids[0],
            requirement.requirement_id,
            overview.item_version,
            requirement.version,
            requirement.occurrence_version,
            snapshot.edition_version,
            expectation,
        ),
        reason=REASON,
        idempotency_key=uuid4(),
        **_trace(),
    )
    # Requirement editing cannot rewrite an already accepted Workforce interval.
    _require(
        _demand(setup, planner, original.demand_id) == old
        and _own_work(setup, staffing.volunteer) == own_before,
        "successor_requirement_rewrote_work",
    )
    stale_release = _manifest(setup, planner)
    _require(
        stale_release.state == ProgrammeReleaseState.INVALIDATED
        and stale_release.release_id == release.release_id
        and stale_release.pointer_version == release.pointer_version
        and stale_release.is_active
        and not stale_release.selections,
        "successor_old_release_not_suppressed",
    )
    source = replace(
        binding.source,
        requirement_revision_id=changed.revision_id,
        requirement_version=changed.resulting_requirement_version,
    )
    intent = ProgrammeStaffingBindingChange(
        ProgrammeStaffingAction.SUCCESSOR,
        source,
        binding.binding_id,
        binding.version,
        old.demand_id,
        old.version,
    )
    preview = preview_programme_staffing_binding(read, change=intent)
    _require(
        preview.demand == old
        and preview.selection.source == source
        and preview.selection.expectation == expectation
        and preview.impact.action == ProgrammeStaffingAction.SUCCESSOR
        and set(preview.impact.changed_fields) == {"starts_at", "briefing"}
        and preview.impact.cancel_predecessor
        and preview.impact.retained_commitments == 1
        and preview.impact.claims_affected == 0
        and preview.impact.confirmations_affected == 1,
        "successor_retained_impact_changed",
    )
    bound = _apply_successor(planner, read, intent, preview)
    predecessor = _demand(setup, planner, old.demand_id)
    draft = _demand(setup, planner, bound.demand_id)
    _require(
        bound.binding_id == original.binding_id
        and bound.demand_id != original.demand_id
        and predecessor.status == "cancelled"
        and predecessor.expectation == old.expectation
        and predecessor.retained_commitments == 1
        and predecessor.claimed == predecessor.confirmed == 0
        and draft.status == "draft"
        and draft.expectation == expectation
        and draft.retained_commitments == draft.claimed == draft.confirmed == 0,
        "successor_copied_or_erased_commitment",
    )
    commitment, commitment_version, demand_version = _claim_confirm_lock(
        setup, planner, staffing.volunteer, bound.demand_id
    )
    _require(commitment != original.commitment_id, "successor_reused_acceptance")
    _verify_own_successor(
        setup, staffing, original, old, expectation, commitment, own_before
    )
    final = _snapshot(setup, planner, planning.candidate_id)
    _require(
        _selected(final, planning.candidate_id) == candidate
        and final.placements == snapshot.placements,
        "successor_work_changed_timetable",
    )
    return PreparedProgrammeWork(
        original.requirement_id,
        changed.revision_id,
        original.binding_id,
        bound.demand_id,
        demand_version,
        commitment,
        commitment_version,
    )


def _apply_successor(planner, read, intent, preview):
    from maru.workforce.programme_binding import (  # noqa: PLC0415
        apply_programme_staffing_binding,
    )
    from maru.workforce.shift_commands import ShiftVersionConflictError  # noqa: PLC0415

    arguments = {"change": intent, "reason": REASON, "retry_key": uuid4()}
    try:
        apply_programme_staffing_binding(
            planner.authenticate(),
            read,
            preview_digest=("0" if preview.digest[0] != "0" else "1")
            + preview.digest[1:],
            **arguments,
        )
    except ShiftVersionConflictError:
        pass
    else:
        raise RuntimeError("successor_stale_preview_accepted")
    from maru.workforce.programme_staffing_queries import (  # noqa: PLC0415
        load_programme_staffing_demand,
    )

    _require(
        load_programme_staffing_demand(
            actor_id=planner.authenticate().id,
            organization_id=read.organization_id,
            edition_id=read.edition_id,
            demand_id=preview.demand.demand_id,
            correlation_id=uuid4(),
        )
        == preview.demand,
        "successor_denial_mutated",
    )
    bound = apply_programme_staffing_binding(
        planner.authenticate(), read, preview_digest=preview.digest, **arguments
    )
    retry = apply_programme_staffing_binding(
        planner.authenticate(), read, preview_digest=preview.digest, **arguments
    )
    _require(
        retry.replayed and replace(retry, replayed=False) == bound,
        "successor_retry_changed",
    )
    return bound


def _verify_own_successor(
    setup, staffing, original, old, expectation, commitment, own_before
):
    own_after = _own_work(setup, staffing.volunteer)
    _require(
        set(own_after) == {*own_before, commitment}
        and own_after[original.commitment_id].status == "removed"
        and own_after[original.commitment_id].instructions.status == "cancelled"
        and own_after[original.commitment_id].starts_at == old.expectation.starts_at
        and own_after[original.commitment_id].ends_at == old.expectation.ends_at
        and own_after[commitment].status == "confirmed"
        and own_after[commitment].starts_at == expectation.starts_at
        and own_after[commitment].ends_at == expectation.ends_at
        and all(
            own_after[row.commitment_id] == own_before[row.commitment_id]
            for row in staffing.work[1:]
        ),
        "successor_personal_history_changed",
    )
