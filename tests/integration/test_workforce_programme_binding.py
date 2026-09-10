"""Real exact-source binding commands preserve existing owner lifecycles."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.programme.staffing_sources import ProgrammeStaffingSourceConflictError
from maru.workforce import programme_binding as bindings
from maru.workforce import programme_staffing_queries as work_queries
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.models import (
    Position,
    ProgrammeShiftBinding,
    ProgrammeShiftBindingRevision,
    ShiftCommitment,
    ShiftDemand,
    ShiftDemandCommandReceipt,
)
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.shift_commands import (
    ShiftRetryConflictError,
    ShiftVersionConflictError,
    create_shift_demand,
    open_shift_demand,
)
from tests.factories import CapabilityGrantFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import moved, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.support.authority import grant_board_controllers_edition_capability

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def binding_world(selection, monkeypatch):
    actor = Account.objects.get(id=selection.request.actor_id)
    edition = EventEdition.objects.get(id=selection.request.edition_id)
    for capability in ("workforce.view_shifts", "workforce.manage_shifts"):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=actor,
            capability_code=capability,
        )
    monkeypatch.setattr(work_queries, "profile_allows_adapter", lambda *_args: True)
    return SimpleNamespace(
        selection=selection,
        actor=actor,
        edition=edition,
        policies={
            "programme_authorizer": selection.policy,
            "scheduling_authorizer": selection.world.policy,
        },
    )


def preview(scope, change):
    return bindings.preview_programme_staffing_binding(
        scope.selection.request, change=change, **scope.policies
    )


def apply(scope, change, planned=None, retry_key=None):
    planned = planned or preview(scope, change)
    return bindings.apply_programme_staffing_binding(
        scope.actor,
        scope.selection.request,
        change=change,
        preview_digest=planned.digest,
        reason="Explicit synthetic staffing request",
        retry_key=retry_key or uuid4(),
        **scope.policies,
    )


def create(scope):
    return apply(
        scope, ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    )


def shift_attribution(scope):
    return {
        "actor": scope.actor,
        "organization_id": scope.edition.organization_id,
        "series_id": scope.edition.series_id,
        "edition_id": scope.edition.id,
        "reason": "Explicit standalone synthetic draft",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def test_preview_creates_no_work_and_exact_retry_retains_original_lineage(
    binding_world,
):
    scope = binding_world
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)
    assert not ShiftDemand.objects.exists()
    retry = uuid4()
    result = apply(scope, change, planned, retry)
    binding = ProgrammeShiftBinding.objects.get(id=result.binding_id)
    revision = ProgrammeShiftBindingRevision.objects.get(id=result.revision_id)
    demand = ShiftDemand.objects.get(id=result.demand_id)
    assert (binding.version, demand.command_version, demand.status) == (1, 1, "draft")
    assert (
        revision.requirement_revision_id
        == scope.selection.source.requirement_revision_id
    )
    assert (
        revision.candidate_revision_id == scope.selection.source.candidate_revision_id
    )
    assert revision.shift_receipt_id is not None
    assert not ShiftCommitment.objects.exists()
    place(
        scope.selection.world,
        intent=moved(scope.selection.world),
        version=scope.selection.placed.version,
    )
    replay = apply(scope, change, planned, retry)
    assert replay == replace(result, replayed=True)
    assert (
        ProgrammeShiftBindingRevision.objects.count()
        == ShiftDemand.objects.count()
        == 1
    )
    with pytest.raises(ShiftRetryConflictError):
        apply(scope, change, replace(planned, digest="0" * 64), retry)


def test_linking_identical_existing_draft_does_not_rewrite_it(binding_world):
    scope = binding_world
    draft = create_shift_demand(
        **shift_attribution(scope), **asdict(scope.selection.terms)
    )
    before = ShiftDemandCommandReceipt.objects.count()
    result = apply(
        scope,
        ProgrammeStaffingBindingChange(
            Action.LINK,
            scope.selection.source,
            demand_id=draft.demand_id,
            expected_demand_version=draft.resulting_version,
        ),
    )
    assert result.demand_id == draft.demand_id
    assert result.demand_version == draft.resulting_version
    assert ShiftDemandCommandReceipt.objects.count() == before
    assert (
        ProgrammeShiftBindingRevision.objects.get(
            id=result.revision_id
        ).shift_receipt_id
        is None
    )


def test_reconciliation_retains_original_source_and_workforce_receipts(binding_world):
    scope = binding_world
    original = create(scope)
    selected = scope.selection
    revised = change_programme_staffing_requirement(
        **selected.common,
        change=replace(
            selected.change,
            requirement_id=selected.source.requirement_id,
            expected_requirement_version=1,
            expected_item_version=selected.result.resulting_item_version,
            expectation=replace(
                selected.terms, briefing="Revised explicit preparation work"
            ),
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    source = replace(
        selected.source,
        requirement_revision_id=revised.revision_id,
        requirement_version=2,
    )
    intent = ProgrammeStaffingBindingChange(
        Action.RECONCILE, source, original.binding_id, 1, original.demand_id, 1
    )
    result = apply(scope, intent)
    assert (result.binding_version, result.demand_version, result.demand_id) == (
        2,
        2,
        original.demand_id,
    )
    assert (
        ShiftDemand.objects.get(id=result.demand_id).briefing
        == "Revised explicit preparation work"
    )
    assert (
        ProgrammeShiftBindingRevision.objects.get(
            id=original.revision_id
        ).requirement_revision_id
        == selected.source.requirement_revision_id
    )
    assert (
        ProgrammeShiftBindingRevision.objects.count()
        == ShiftDemandCommandReceipt.objects.count()
        == 2
    )


def test_selected_candidate_movement_invalidates_a_previously_successful_preview(
    binding_world,
):
    scope = binding_world
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)
    place(
        scope.selection.world,
        intent=moved(scope.selection.world),
        version=scope.selection.placed.version,
    )
    with pytest.raises(ProgrammeStaffingSourceConflictError):
        apply(scope, change, planned)
    assert not ShiftDemand.objects.exists()
    assert not ProgrammeShiftBinding.objects.exists()


def test_late_binding_failure_rolls_back_existing_workforce_command_effects(
    binding_world, monkeypatch
):
    scope = binding_world
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)
    models = (
        AuditEvent,
        DomainEvent,
        OutboxMessage,
        ShiftDemand,
        ShiftDemandCommandReceipt,
    )
    before = tuple(model.objects.count() for model in models)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic binding evidence failure")

    monkeypatch.setattr(bindings, "_record", fail)
    with pytest.raises(RuntimeError, match="Synthetic binding evidence failure"):
        apply(scope, change, planned)
    assert tuple(model.objects.count() for model in models) == before


def test_explicit_successor_cancels_open_predecessor_and_creates_separate_draft(
    binding_world,
):
    scope = binding_world
    original = create(scope)
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    intent = ProgrammeStaffingBindingChange(
        Action.SUCCESSOR,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        opened.resulting_version,
    )
    planned = preview(scope, intent)
    assert planned.impact.cancel_predecessor
    result = apply(scope, intent, planned)
    assert result.demand_id != original.demand_id
    assert ShiftDemand.objects.get(id=original.demand_id).status == "cancelled"
    assert ShiftDemand.objects.get(id=result.demand_id).status == "draft"
    revision = ProgrammeShiftBindingRevision.objects.get(id=result.revision_id)
    assert revision.predecessor_id == original.demand_id
    assert revision.cancellation_receipt_id is not None
    assert not ShiftCommitment.objects.exists()


def person_for(scope, monkeypatch):
    for capability in (
        "workforce.view_structure",
        "workforce.manage_assignments",
        "authorization.manage_roles",
        "authorization.revoke",
        "workforce.manage_shifts",
        "workforce.view_shifts",
    ):
        planner, reviewer = grant_board_controllers_edition_capability(
            scope.edition, capability
        )
    terms = scope.selection.terms
    monkeypatch.setattr(
        shifts,
        "_windows",
        lambda: (AvailabilityWindowInput(terms.starts_at, terms.ends_at, "preferred"),),
    )
    position = Position.objects.get(id=terms.position_id)
    # This is explicitly the existing full-convention fixture, not evidence of
    # Programme-only activation or an unrelated-module exclusion rehearsal.
    person, assignment = shifts._activate_person(
        edition=scope.edition, planner=planner, reviewer=reviewer, position=position
    )
    return SimpleNamespace(
        edition=scope.edition,
        planner=planner,
        reviewer=reviewer,
        person=person,
        position=position,
        assignment=assignment,
    )


@pytest.mark.parametrize("confirmed", [False, True])
def test_successor_preserves_real_volunteer_decisions_without_copy_or_reconfirmation(
    binding_world, monkeypatch, confirmed
):
    scope = binding_world
    person = person_for(scope, monkeypatch)
    original = create(scope)
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    demand = ShiftDemand.objects.get(id=original.demand_id)
    claim = shifts._claim(person, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    if confirmed:
        shifts._confirm(person, commitment)
    intent = ProgrammeStaffingBindingChange(
        Action.SUCCESSOR,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        opened.resulting_version,
    )
    planned = preview(scope, intent)
    assert planned.impact.retained_commitments == 1
    assert (planned.impact.claims_affected, planned.impact.confirmations_affected) == (
        (0, 1) if confirmed else (1, 0)
    )
    result = apply(scope, intent, planned)
    commitment.refresh_from_db()
    assert commitment.status == "removed"
    assert commitment.removal_kind == "cancelled"
    assert commitment.demand_id == original.demand_id
    assert not ShiftCommitment.objects.filter(demand_id=result.demand_id).exists()
    assert ShiftCommitment.objects.count() == 1
    assert ShiftDemand.objects.get(id=result.demand_id).status == "draft"
    person.assignment.refresh_from_db()
    assert person.assignment.status == "active"


def test_new_claim_after_preview_is_detected_even_without_a_demand_version_change(
    binding_world, monkeypatch
):
    scope = binding_world
    person = person_for(scope, monkeypatch)
    original = create(scope)
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    intent = ProgrammeStaffingBindingChange(
        Action.SUCCESSOR,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        opened.resulting_version,
    )
    planned = preview(scope, intent)
    demand = ShiftDemand.objects.get(id=original.demand_id)
    claim = shifts._claim(person, demand)
    demand.refresh_from_db()
    assert demand.command_version == opened.resulting_version
    with pytest.raises(ShiftVersionConflictError, match="impact changed"):
        apply(scope, intent, planned)
    assert ShiftCommitment.objects.get(id=claim.commitment_id).status == "claimed"
    assert (
        ShiftDemand.objects.count()
        == ProgrammeShiftBindingRevision.objects.count()
        == 1
    )
    assert demand.status == "open"


def test_late_successor_failure_restores_claims_and_original_demand(
    binding_world, monkeypatch
):
    scope = binding_world
    person = person_for(scope, monkeypatch)
    original = create(scope)
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=original.demand_id, expected_version=1
    )
    demand = ShiftDemand.objects.get(id=original.demand_id)
    claim = shifts._claim(person, demand)
    intent = ProgrammeStaffingBindingChange(
        Action.SUCCESSOR,
        scope.selection.source,
        original.binding_id,
        1,
        original.demand_id,
        opened.resulting_version,
    )
    planned = preview(scope, intent)
    models = (
        ShiftDemand,
        ShiftDemandCommandReceipt,
        ProgrammeShiftBindingRevision,
        AuditEvent,
        DomainEvent,
        OutboxMessage,
    )
    before = tuple(model.objects.count() for model in models)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic successor evidence failure")

    monkeypatch.setattr(bindings, "_record", fail)
    with pytest.raises(RuntimeError, match="Synthetic successor evidence failure"):
        apply(scope, intent, planned)
    assert tuple(model.objects.count() for model in models) == before
    assert ShiftCommitment.objects.get(id=claim.commitment_id).status == "claimed"
    assert ShiftDemand.objects.get(id=original.demand_id).status == "open"


@pytest.mark.parametrize("shared_retry", [False, True])
def test_competing_first_bindings_leave_one_demand_and_one_lineage(
    binding_world, shared_retry
):
    scope = binding_world
    change = ProgrammeStaffingBindingChange(Action.CREATE, scope.selection.source)
    planned = preview(scope, change)
    key = uuid4()
    barrier = Barrier(2)

    def attempt(_index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return apply(scope, change, planned, key if shared_retry else uuid4())
        except ShiftVersionConflictError:
            return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, range(2)))
    assert sum(result is not None for result in results) == (2 if shared_retry else 1)
    if shared_retry:
        assert {result.replayed for result in results} == {False, True}
        assert len({result.revision_id for result in results}) == 1
    assert (
        ShiftDemand.objects.count()
        == ProgrammeShiftBinding.objects.count()
        == ProgrammeShiftBindingRevision.objects.count()
        == 1
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE workforce_programmeshiftbinding SET version = version + 1",
        "UPDATE workforce_programmeshiftbinding SET version = version + 2",
        "DELETE FROM workforce_programmeshiftbinding",
        "TRUNCATE workforce_programmeshiftbinding CASCADE",
        "UPDATE workforce_programmeshiftbindingrevision SET reason = 'rewritten'",
        "DELETE FROM workforce_programmeshiftbindingrevision",
        "TRUNCATE workforce_programmeshiftbindingrevision CASCADE",
    ],
)
def test_raw_dml_cannot_forge_a_revision_or_erase_work_lineage(
    binding_world, statement
):
    created = create(binding_world)

    def execute():
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('maru.authority_provenance_test_reset', 'off', true)"
            )
            cursor.execute(statement)

    with pytest.raises(IntegrityError):
        execute()
    assert ProgrammeShiftBinding.objects.get(id=created.binding_id).version == 1
    assert (
        ProgrammeShiftBindingRevision.objects.get(id=created.revision_id).sequence == 1
    )
