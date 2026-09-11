"""Release coverage follows current accepted work and retains retired obligations."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.programme import placement_queries
from maru.programme.models import ProgrammeItem
from maru.programme.placement_commands import record_programme_placement_decision
from maru.programme.release_inputs import (
    ProgrammePlacementDecisionIntent,
    ProgrammePlacementDecisionKind,
    ProgrammePlacementDecisionState,
    ProgrammePlacementSelection,
)
from maru.scheduling import release_candidate_queries
from maru.scheduling.release_staffing_sources import load_release_staffing_sources
from maru.workforce import programme_release_queries
from maru.workforce.models import ShiftCommitment, ShiftDemand
from maru.workforce.programme_queries import ProgrammeCoverageDeniedError
from maru.workforce.shift_commands import (
    cancel_shift_demand,
    lock_shift_demand,
    open_shift_demand,
)
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import moved, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_staffing_queries import (
    staffing_world as staffing_world,  # noqa: PLC0414
)
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)
from tests.integration.test_workforce_programme_binding import (
    create,
    person_for,
    shift_attribution,
)
from tests.integration.test_workforce_programme_release_sources import retire

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def release_work(staffing_world, monkeypatch):
    for module in (
        programme_release_queries,
        placement_queries,
        release_candidate_queries,
    ):
        monkeypatch.setattr(module, "profile_allows_adapter", lambda *_args: True)
    return staffing_world


def load(scope):
    return load_release_staffing_sources(
        scope.selection.world.request,
        item_id=scope.selection.request.item_id,
        candidate_id=scope.selection.source.candidate_id,
        occurrence_ids=(scope.selection.source.occurrence_id,),
        **scope.policies,
    )[0]


def test_unbound_then_draft_then_real_confirmed_and_locked_coverage(
    release_work, monkeypatch
):
    assert load(release_work).state == "blocked"
    original = create(release_work)
    draft = load(release_work)
    assert draft.state == "blocked"
    opened = open_shift_demand(
        **shift_attribution(release_work),
        demand_id=original.demand_id,
        expected_version=1,
    )
    first = person_for(release_work, monkeypatch)
    second_person, second_assignment = shifts._activate_person(
        edition=first.edition,
        planner=first.planner,
        reviewer=first.reviewer,
        position=first.position,
    )
    second = SimpleNamespace(
        **(
            vars(first)
            | {
                "person": second_person,
                "assignment": second_assignment,
            }
        )
    )
    demand = ShiftDemand.objects.get(id=original.demand_id)
    claim = shifts._claim(first, demand)
    assert load(release_work).state == "blocked"
    shifts._confirm(first, ShiftCommitment.objects.get(id=claim.commitment_id))
    assert load(release_work).state == "blocked"
    claim = shifts._claim(second, demand)
    shifts._confirm(second, ShiftCommitment.objects.get(id=claim.commitment_id))
    covered = load(release_work)
    assert covered.state == "satisfied"
    assert not covered.requires_absence_decision
    assert covered.evidence_digest != draft.evidence_digest
    lock_shift_demand(
        **shift_attribution(release_work),
        demand_id=original.demand_id,
        expected_version=opened.resulting_version,
        allow_understaffed=False,
    )
    assert load(release_work).state == "satisfied"


def test_retired_requirement_keeps_operative_work_until_cancelled(release_work):
    created = create(release_work)
    retire(release_work)
    retained = load(release_work)
    assert retained.state == "blocked"
    assert not retained.requires_absence_decision
    cancel_shift_demand(
        **shift_attribution(release_work),
        demand_id=created.demand_id,
        expected_version=1,
    )
    closed = load(release_work)
    assert closed.state == "not_applicable"
    assert closed.requires_absence_decision  # Still needs explicit Programme decision.
    assert retained.evidence_digest != closed.evidence_digest


def test_moved_candidate_cannot_inherit_old_bound_coverage(release_work):
    create(release_work)
    selected = release_work.selection
    place(selected.world, intent=moved(selected.world), version=selected.placed.version)
    assert load(release_work).state == "stale"


@pytest.mark.parametrize("retired", [False, True])
def test_no_staffing_command_refuses_active_need_or_retired_operative_work(
    release_work, retired
):
    from django.core.exceptions import ValidationError  # noqa: PLC0415

    if retired:
        create(release_work)
        retire(release_work)
    selected = release_work.selection
    item = ProgrammeItem.objects.get(id=selected.request.item_id)
    source = selected.source
    request = placement_queries.ProgrammePlacementReadRequest(
        selected.request.actor_id,
        item.organization_id,
        item.edition_id,
        uuid4(),
        "test",
    )
    selection = ProgrammePlacementSelection(
        item.id,
        source.occurrence_id,
        source.candidate_id,
        source.candidate_revision_id,
        source.placement_id,
        item.aggregate_version,
        selected.placed.version,
        ProgrammePlacementDecisionKind.STAFFING_NOT_REQUIRED,
    )
    planned = placement_queries.preview_programme_placement_decision(
        request,
        selection=selection,
        **release_work.policies,
    )
    assert not planned.staffing_absence_available
    with pytest.raises(ValidationError, match="staffing needs or retained work"):
        record_programme_placement_decision(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            intent=ProgrammePlacementDecisionIntent(
                item.id,
                source.occurrence_id,
                source.candidate_id,
                source.candidate_revision_id,
                source.placement_id,
                item.aggregate_version,
                selected.placed.version,
                0,
                planned.source_digest,
                selection.kind,
                ProgrammePlacementDecisionState.SATISFIED,
            ),
            reason="Synthetic absence must fail",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            **release_work.policies,
        )


def test_independent_coverage_denial_is_not_no_staffing(release_work, monkeypatch):
    from maru.workforce import programme_queries  # noqa: PLC0415

    monkeypatch.setattr(
        programme_queries, "profile_allows_adapter", lambda *_args: False
    )
    with pytest.raises(ProgrammeCoverageDeniedError):
        load(release_work)
