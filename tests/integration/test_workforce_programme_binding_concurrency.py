"""Committed competing owner commands preserve exact source and volunteer work."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, transaction

from maru.programme.commands import revise_programme_working
from maru.programme.models import ProgrammeItem
from maru.programme.staffing_sources import ProgrammeStaffingSourceConflictError
from maru.scheduling.planning_queries import load_scheduling_planning
from maru.workforce.assignment_commands import end_position_assignment
from maru.workforce.availability_commands import withdraw_person_availability
from maru.workforce.models import (
    EditionStructureControl,
    PersonAvailabilityPlan,
    Position,
    ProgrammeShiftBinding,
    ProgrammeShiftBindingRevision,
    ShiftCommitment,
    ShiftDemand,
)
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.programme_staffing_queries import ProgrammeStaffingUnavailableError
from maru.workforce.shift_commands import (
    ShiftCommandError,
    cancel_shift_demand,
    create_shift_demand,
    open_shift_demand,
)
from maru.workforce.shift_queries import load_my_shift_overview
from maru.workforce.structure_commands import (
    StructureDependencyConflictError,
    close_position,
)
from tests.factories import CapabilityGrantFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import moved, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import (
    apply,
    create,
    person_for,
    preview,
    shift_attribution,
)
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)
from tests.workforce_helpers import retire_department_for_test

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def race(left, right):
    start = Barrier(2)

    def run(command):
        close_old_connections()
        try:
            start.wait(timeout=10)
            return command()
        except (
            ShiftCommandError,
            ProgrammeStaffingSourceConflictError,
            StructureDependencyConflictError,
            ProgrammeStaffingUnavailableError,
        ) as error:
            return error
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        return tuple(workers.map(run, (left, right)))


def test_source_movement_and_first_binding_have_one_serializable_outcome(binding_world):
    scope = binding_world
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)
    bound, movement = race(
        partial(apply, scope, change, planned),
        partial(
            place,
            scope.selection.world,
            intent=moved(scope.selection.world),
            version=scope.selection.placed.version,
        ),
    )
    assert not isinstance(movement, Exception)
    expected = 0 if isinstance(bound, ProgrammeStaffingSourceConflictError) else 1
    assert not isinstance(bound, ShiftCommandError)
    assert (
        ProgrammeShiftBinding.objects.count() == ShiftDemand.objects.count() == expected
    )
    if expected:
        revision = ProgrammeShiftBindingRevision.objects.get()
        assert (
            revision.candidate_revision_id
            == scope.selection.source.candidate_revision_id
        )
        assert ShiftDemand.objects.get().starts_at == scope.selection.terms.starts_at
    assert not ShiftCommitment.objects.exists()


def test_opening_competes_with_link_without_rewriting_published_work(binding_world):
    scope = binding_world
    draft = create_shift_demand(
        **shift_attribution(scope), **asdict(scope.selection.terms)
    )
    intent = ProgrammeStaffingBindingChange(
        Action.LINK,
        scope.selection.source,
        demand_id=draft.demand_id,
        expected_demand_version=1,
    )
    planned = preview(scope, intent)
    bound, opened = race(
        partial(apply, scope, intent, planned),
        partial(
            open_shift_demand,
            **shift_attribution(scope),
            demand_id=draft.demand_id,
            expected_version=1,
        ),
    )
    assert not isinstance(opened, Exception)
    demand = ShiftDemand.objects.get()
    assert (demand.id, demand.status, demand.command_version) == (
        draft.demand_id,
        "open",
        2,
    )
    assert ProgrammeShiftBinding.objects.count() == (
        0 if isinstance(bound, ShiftCommandError) else 1
    )
    assert demand.briefing == scope.selection.terms.briefing


@pytest.mark.parametrize("source_action", ["programme_revision", "planning_read"])
def test_source_owner_and_staffing_binding_share_parent_order(
    binding_world, source_action
):
    scope = binding_world
    intent = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, intent)
    if source_action == "planning_read":
        other = partial(
            load_scheduling_planning,
            scope.selection.world.request,
            candidate_id=scope.selection.source.candidate_id,
            authorizer=scope.selection.world.policy,
        )
    else:
        item = ProgrammeItem.objects.get(id=scope.selection.request.item_id)
        other = partial(
            revise_programme_working,
            **scope.selection.common,
            item_id=item.id,
            internal_title="Concurrent private working title",
            expected_version=item.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
    bound, source = race(partial(apply, scope, intent, planned), other)
    assert not isinstance(source, Exception)
    assert (
        ProgrammeShiftBinding.objects.count()
        == ShiftDemand.objects.count()
        == (
            0
            if isinstance(
                bound, ShiftCommandError | ProgrammeStaffingSourceConflictError
            )
            else 1
        )
    )
    if source_action == "planning_read":
        assert not isinstance(bound, Exception)
    if ShiftDemand.objects.exists():
        assert ShiftDemand.objects.get().title == scope.selection.terms.title


def test_claim_competes_with_successor_without_transferring_a_decision(
    binding_world, monkeypatch
):
    scope = binding_world
    person = person_for(scope, monkeypatch)
    original = create(scope)
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    demand = ShiftDemand.objects.get(id=original.demand_id)
    intent = ProgrammeStaffingBindingChange(
        Action.SUCCESSOR,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        opened.resulting_version,
    )
    planned = preview(scope, intent)
    successor, claim = race(
        partial(apply, scope, intent, planned), partial(shifts._claim, person, demand)
    )
    demand.refresh_from_db()
    if isinstance(successor, ShiftCommandError):
        assert not isinstance(claim, Exception)
        assert demand.status == "open"
        assert ShiftCommitment.objects.get().status == "claimed"
        assert (
            ShiftDemand.objects.count()
            == ProgrammeShiftBindingRevision.objects.count()
            == 1
        )
    else:
        assert isinstance(claim, ShiftCommandError)
        assert demand.status == "cancelled"
        assert (
            ShiftDemand.objects.count()
            == ProgrammeShiftBindingRevision.objects.count()
            == 2
        )
        assert not ShiftCommitment.objects.exists()


def test_cancellation_competes_with_reconciliation_without_resurrecting_work(
    binding_world,
):
    scope = binding_world
    original = create(scope)
    intent = ProgrammeStaffingBindingChange(
        Action.RECONCILE,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        1,
    )
    planned = preview(scope, intent)
    reconciled, cancelled = race(
        partial(apply, scope, intent, planned),
        partial(
            cancel_shift_demand,
            **shift_attribution(scope),
            demand_id=original.demand_id,
            expected_version=1,
        ),
    )
    demand = ShiftDemand.objects.get()
    if isinstance(cancelled, ShiftCommandError):
        assert not isinstance(reconciled, Exception)
        assert demand.status == "draft"
    else:
        assert demand.status == "cancelled"
    assert demand.briefing == scope.selection.terms.briefing
    assert ProgrammeShiftBindingRevision.objects.count() == (
        1 if isinstance(reconciled, ShiftCommandError) else 2
    )
    assert not ShiftCommitment.objects.exists()


@pytest.mark.parametrize("change_kind", ["assignment_end", "availability_withdrawal"])
def test_person_eligibility_change_and_claim_cannot_produce_current_coverage(
    binding_world, monkeypatch, change_kind
):
    scope = binding_world
    person = person_for(scope, monkeypatch)
    original = create(scope)
    open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    demand = ShiftDemand.objects.get(id=original.demand_id)
    if change_kind == "assignment_end":
        change = partial(
            end_position_assignment,
            **{**shift_attribution(scope), "actor": person.planner},
            assignment_id=person.assignment.id,
            expected_version=person.assignment.command_version,
        )
    else:
        plan = PersonAvailabilityPlan.objects.get(
            account=person.person, edition=scope.edition
        )
        change = partial(
            withdraw_person_availability,
            actor=person.person,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            expected_version=plan.command_version,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    claim, changed = race(partial(shifts._claim, person, demand), change)
    assert not isinstance(changed, Exception)
    personal = load_my_shift_overview(account=person.person, edition=scope.edition)
    assert personal.suitable == ()
    assert all(row.commitment.status != "confirmed" for row in personal.commitments)
    assert ShiftCommitment.objects.count() == (
        0 if isinstance(claim, ShiftCommandError) else 1
    )
    assert ProgrammeShiftBindingRevision.objects.count() == 1


def test_department_retirement_and_binding_preserve_live_work_ownership(
    binding_world,
):
    scope = binding_world
    for code in ("workforce.view_structure", "workforce.manage_structure"):
        CapabilityGrantFactory(
            principal=scope.actor,
            organization=scope.edition.organization,
            edition=scope.edition,
            capability_code=code,
        )
    position = Position.objects.select_related("department").get(
        id=scope.selection.terms.position_id
    )
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)

    def retire():
        with transaction.atomic():
            lock_programme_staffing_scope(
                organization_id=scope.edition.organization_id,
                edition_id=scope.edition.id,
            )
            version = EditionStructureControl.objects.get(
                edition=scope.edition
            ).aggregate_version
            close_position(
                actor=scope.actor,
                organization_id=scope.edition.organization_id,
                series_id=scope.edition.series_id,
                edition_id=scope.edition.id,
                position_id=position.id,
                expected_version=version,
                confirmation_name=position.title,
                reason="Synthetic retirement race",
                correlation_id=uuid4(),
                source_channel="test",
            )
            return retire_department_for_test(
                department=position.department, actor=scope.actor
            )

    bound, retired = race(partial(apply, scope, change, planned), retire)
    position.department.refresh_from_db()
    if isinstance(retired, StructureDependencyConflictError):
        assert not isinstance(bound, Exception)
        assert position.department.retired_at is None
        assert ShiftDemand.objects.count() == 1
    else:
        assert isinstance(bound, ProgrammeStaffingUnavailableError)
        assert position.department.retired_at is not None
        assert not ShiftDemand.objects.exists()
