"""Fresh personal acceptance and retained lineage under actual owner signatures."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.programme import staffing_commands, staffing_queries
from maru.programme.staffing_inputs import (
    ProgrammeStaffingExpectation,
    ProgrammeStaffingSource,
)
from maru.programme.staffing_queries import (
    ProgrammeStaffingOverview,
    ProgrammeStaffingRequirementView,
)
from maru.programme.staffing_sources import ProgrammeStaffingSelection
from maru.scheduling import planning_queries, release_queries
from maru.scheduling.release_queries import (
    ProgrammeReleaseManifest,
    ProgrammeReleaseState,
)
from maru.workforce import (
    programme_binding,
    programme_binding_queries,
    programme_staffing_queries,
)
from maru.workforce.programme_binding import (
    ProgrammeStaffingBindingPreview,
    ProgrammeStaffingBindingResult,
)
from maru.workforce.programme_binding_queries import ProgrammeBindingView
from maru.workforce.programme_impact import (
    ProgrammeStaffingAction,
    ProgrammeStaffingDemandState,
    ProgrammeStaffingImpact,
)
from maru.workforce.shift_commands import ShiftVersionConflictError
from tests.rehearsals import programme_successor_work as preparation
from tests.unit.test_programme_change_scenario import _sources
from tests.unit.test_programme_physical_preparation import _snapshot
from tests.unit.test_programme_release_preparation import _stub
from tests.unit.test_programme_review_scenario import _authentication


def _owner_data(sources):
    _, _, _, items, planning, _, staffing, _ = sources
    original = staffing.work[0]
    terms = ProgrammeStaffingExpectation(
        staffing.position_id,
        "Fictional work",
        "Fictional room",
        "Earlier wording",
        "Ask the organizer",
        items.availability_starts_at + timedelta(minutes=15),
        items.availability_starts_at + timedelta(minutes=105),
        1,
        10,
        0,
    )
    requirement = ProgrammeStaffingRequirementView(
        original.requirement_id,
        planning.occurrence_ids[0],
        1,
        original.requirement_revision_id,
        20,
        1,
        "active",
        terms,
    )
    source = ProgrammeStaffingSource(
        original.requirement_id,
        original.requirement_revision_id,
        1,
        planning.occurrence_ids[0],
        1,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids[0],
    )
    binding = ProgrammeBindingView(
        original.binding_id,
        1,
        uuid4(),
        source,
        original.demand_id,
        1,
        "a" * 64,
        "b" * 64,
        "create",
        None,
    )
    old = ProgrammeStaffingDemandState(
        original.demand_id, original.demand_version, "locked", terms, 1, 0, 1
    )
    changed = staffing_commands.ProgrammeStaffingCommandResult(
        uuid4(),
        items.ceremony.item_id,
        original.requirement_id,
        uuid4(),
        21,
        2,
        replayed=False,
    )
    desired = replace(
        terms,
        starts_at=terms.starts_at - timedelta(minutes=15),
        briefing=(
            "Inspect the fictional aisle fifteen minutes earlier, "
            "then support the host."
        ),
    )
    selection = ProgrammeStaffingSelection(
        items.ceremony.item_id,
        replace(
            source, requirement_revision_id=changed.revision_id, requirement_version=2
        ),
        21,
        planning.candidate_version,
        3,
        desired,
        "c" * 64,
    )
    preview = ProgrammeStaffingBindingPreview(
        selection,
        old,
        ProgrammeStaffingImpact(
            ProgrammeStaffingAction.SUCCESSOR,
            ("briefing", "starts_at"),
            cancel_predecessor=True,
            retained_commitments=1,
            claims_affected=0,
            confirmations_affected=1,
        ),
        "d" * 64,
    )
    bound = ProgrammeStaffingBindingResult(
        original.binding_id, uuid4(), 2, uuid4(), 1, replayed=False
    )
    return requirement, binding, old, changed, preview, bound


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "rewritten",
        "release_not_invalidated",
        "impact",
        "stale_preview",
        "copied",
        "erased",
        "retry",
        "same_acceptance",
        "old_interval",
        "unrelated",
    ],
)
def test_successor_preserves_old_work_requires_preview_and_new_own_claim(
    monkeypatch, fault
):
    _authentication(monkeypatch)
    sources = _sources()
    setup, _, _, items, planning, _, staffing, release = sources
    requirement, binding, old, changed, preview, bound = _owner_data(sources)
    snapshot = _snapshot(planning, items)
    snapshot.edition_version = 3
    _stub(
        monkeypatch, planning_queries, "load_scheduling_planning", return_value=snapshot
    )
    _stub(
        monkeypatch,
        staffing_queries,
        "load_programme_staffing_requirements",
        return_value=ProgrammeStaffingOverview(
            items.ceremony.item_id, 20, (requirement,), "active"
        ),
    )
    _stub(
        monkeypatch,
        programme_binding_queries,
        "load_programme_bindings",
        return_value=(binding,),
    )
    old_after_edit = (
        replace(old, expectation=preview.selection.expectation)
        if fault == "rewritten"
        else old
    )
    predecessor = replace(
        old,
        status="cancelled",
        version=old.version + 1,
        confirmed=0,
        retained_commitments=0 if fault == "erased" else 1,
    )
    draft = ProgrammeStaffingDemandState(
        bound.demand_id,
        1,
        "draft",
        preview.selection.expectation,
        1 if fault == "copied" else 0,
        0,
        0,
    )
    _stub(
        monkeypatch,
        programme_staffing_queries,
        "load_programme_staffing_demand",
        side_effect=[old, old_after_edit, old, predecessor, draft],
    )
    revise = _stub(
        monkeypatch,
        staffing_commands,
        "change_programme_staffing_requirement",
        return_value=changed,
    )
    _stub(
        monkeypatch,
        release_queries,
        "load_programme_release_manifest",
        return_value=ProgrammeReleaseManifest(
            ProgrammeReleaseState.AVAILABLE
            if fault == "release_not_invalidated"
            else ProgrammeReleaseState.INVALIDATED,
            1,
            release.release_id,
            is_active=True,
            selections=(),
        ),
    )
    _stub(
        monkeypatch,
        programme_binding,
        "preview_programme_staffing_binding",
        return_value=replace(
            preview, impact=replace(preview.impact, confirmations_affected=0)
        )
        if fault == "impact"
        else preview,
    )
    apply = _stub(
        monkeypatch,
        programme_binding,
        "apply_programme_staffing_binding",
        side_effect=[
            bound if fault == "stale_preview" else ShiftVersionConflictError(),
            bound,
            replace(
                bound,
                replayed=True,
                demand_id=uuid4() if fault == "retry" else bound.demand_id,
            ),
        ],
    )
    original = staffing.work[0]
    commitment = original.commitment_id if fault == "same_acceptance" else uuid4()
    claim = _stub(
        monkeypatch, preparation, "_claim_confirm_lock", return_value=(commitment, 2, 4)
    )
    own_before = {
        row.commitment_id: SimpleNamespace(
            status="confirmed",
            starts_at=old.expectation.starts_at,
            ends_at=old.expectation.ends_at,
        )
        for row in staffing.work
    }
    own_after = dict(own_before)
    own_after[original.commitment_id] = SimpleNamespace(
        status="removed",
        instructions=SimpleNamespace(status="cancelled"),
        starts_at=preview.selection.expectation.starts_at
        if fault == "old_interval"
        else old.expectation.starts_at,
        ends_at=old.expectation.ends_at,
    )
    own_after[commitment] = SimpleNamespace(
        status="confirmed",
        starts_at=preview.selection.expectation.starts_at,
        ends_at=preview.selection.expectation.ends_at,
    )
    if fault == "unrelated":
        own_after[staffing.work[1].commitment_id] = SimpleNamespace(status="removed")
    _stub(
        monkeypatch,
        preparation,
        "_own_work",
        side_effect=[own_before, own_before, own_after],
    )
    if fault:
        with pytest.raises(RuntimeError):
            preparation.prepare_successor_work(
                setup, items, planning, staffing, release
            )
    else:
        result = preparation.prepare_successor_work(
            setup, items, planning, staffing, release
        )
        assert result.commitment_id == commitment != original.commitment_id
        assert result.binding_id == original.binding_id
        assert result.demand_id == bound.demand_id != original.demand_id
        change = revise.call_args.kwargs["change"]
        assert change.expected_item_version == 20
        assert change.expected_requirement_version == 1
        assert change.expectation == preview.selection.expectation
        assert apply.call_args.args[0].id == planning.planner.account_id
        assert apply.call_args.kwargs["change"].source == preview.selection.source
        assert claim.call_args.args == (
            setup,
            planning.planner,
            staffing.volunteer,
            bound.demand_id,
        )
