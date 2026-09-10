"""Real independently authorized Programme and Scheduling staffing selection."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.programme.models import ProgrammeItem
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.programme.staffing_inputs import (
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
    ProgrammeStaffingSource,
)
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest
from maru.programme.staffing_sources import (
    ProgrammeStaffingSourceConflictError,
    load_programme_staffing_selection,
)
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.candidate_commands import copy_scheduling_candidate
from maru.scheduling.day_commands import revise_scheduling_service_day
from maru.scheduling.inputs import SchedulingServiceDayInput
from maru.scheduling.models import SchedulingOccurrence
from maru.scheduling.time_rules import SchedulingWindow
from maru.workforce.models import ShiftDemand
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
from tests.integration.test_programme_staffing_commands import staffing_position
from tests.integration.test_scheduling_placements import (
    candidate_revision,
    member,
    moved,
    next_request,
    place,
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def selection(world):
    placed = place(world)
    edition = EventEdition.objects.get(id=world.request.edition_id)
    actor = Account.objects.get(id=world.request.actor_id)
    occurrence = SchedulingOccurrence.objects.get(id=world.occurrence.object_id)
    item = ProgrammeItem.objects.get(id=occurrence.programme_item_id)
    position = staffing_position(actor, edition)
    terms = ProgrammeStaffingExpectation(
        position.id,
        "Stage preparation",
        "East stage",
        "Prepare stage safely",
        "",
        world.placement.envelope.setup_starts_at,
        world.placement.envelope.teardown_ends_at,
        2,
        5,
        30,
    )
    policy = _TrustedProgrammeAuthorizer()
    change = ProgrammeStaffingChange(
        item.id,
        occurrence.id,
        None,
        item.aggregate_version,
        0,
        occurrence.aggregate_version,
        edition.aggregate_version,
        terms,
    )
    common = {
        "actor_id": actor.id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "authorizer": policy,
        "reason": "Explicit synthetic source selection",
        "source_channel": "test",
    }
    result = change_programme_staffing_requirement(
        **common, change=change, idempotency_key=uuid4(), correlation_id=uuid4()
    )
    source = ProgrammeStaffingSource(
        result.requirement_id,
        result.revision_id,
        1,
        occurrence.id,
        occurrence.aggregate_version,
        placed.object_id,
        candidate_revision(placed).id,
        member(placed).placement_id,
    )
    request = ProgrammeStaffingReadRequest(
        actor.id, edition.organization_id, edition.id, item.id, uuid4(), "test"
    )
    return SimpleNamespace(
        world=world,
        request=request,
        source=source,
        result=result,
        terms=terms,
        policy=policy,
        placed=placed,
        change=change,
        common=common,
    )


def load(selection):
    return load_programme_staffing_selection(
        selection.request,
        source=selection.source,
        programme_authorizer=selection.policy,
        scheduling_authorizer=selection.world.policy,
    )


def test_real_source_ignores_copy_but_rejects_movement_of_the_selected_alternative(
    selection,
):
    original = load(selection)
    assert original.expectation == selection.terms
    copy_scheduling_candidate(
        next_request(selection.world),
        source_revision_id=selection.source.candidate_revision_id,
        label="Independent staffing alternative",
        expected_control_version=selection.placed.control_version,
        authorizer=selection.world.policy,
    )
    assert load(selection) == original
    place(
        selection.world, intent=moved(selection.world), version=selection.placed.version
    )
    with pytest.raises(ProgrammeStaffingSourceConflictError):
        load(selection)
    assert not ShiftDemand.objects.exists()


def test_real_programme_authority_never_substitutes_for_scheduling_authority(selection):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_programme_staffing_selection(
            selection.request,
            source=selection.source,
            programme_authorizer=selection.policy,
        )


def test_current_day_revision_is_required_even_when_candidate_did_not_move(selection):
    world = selection.world
    original = load(selection)
    revise_scheduling_service_day(
        next_request(world),
        day_id=world.day.object_id,
        day=SchedulingServiceDayInput(
            "Corrected service day",
            SchedulingWindow(
                world.placement.envelope.setup_starts_at,
                world.placement.envelope.teardown_ends_at,
            ),
            5,
        ),
        expected_version=1,
        authorizer=world.policy,
    )
    with pytest.raises(ProgrammeStaffingSourceConflictError):
        load(selection)
    assert original.source == selection.source


def test_retiring_requirement_invalidates_selection_without_cancelling_work(selection):
    load(selection)
    change_programme_staffing_requirement(
        **selection.common,
        change=replace(
            selection.change,
            requirement_id=selection.result.requirement_id,
            expected_requirement_version=1,
            expected_item_version=selection.result.resulting_item_version,
            expectation=None,
            retire=True,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    with pytest.raises(ProgrammeStaffingSourceConflictError):
        load(selection)
    assert not ShiftDemand.objects.exists()
