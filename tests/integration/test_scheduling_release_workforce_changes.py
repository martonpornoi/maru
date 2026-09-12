from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from maru.workforce.assignment_commands import end_position_assignment
from maru.workforce.availability_commands import (
    save_person_availability,
    withdraw_person_availability,
)
from maru.workforce.models import PersonAvailabilityPlan, ShiftCommitment
from maru.workforce.shift_commands import withdraw_shift_claim
from tests.integration import test_workforce_shifts as shifts

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world():
    return shifts._shift_world()


def _track(world, kind, source_id):
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind=kind,
            source_id=source_id,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
        )


def _personal(world):
    return {
        "actor": world.person,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _availability_plan(world):
    return PersonAvailabilityPlan.objects.get(
        account=world.person, edition=world.edition
    )


def test_demand_and_commitment_commands_share_only_their_exact_demand_generation(world):
    demand = shifts._create_demand(world)
    key = _track(world, "workforce_demand", demand.id)
    shifts._open(world, demand)
    claimed = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    shifts._confirm(world, commitment)
    commitment.refresh_from_db()
    withdraw_shift_claim(
        **_personal(world),
        commitment_id=commitment.id,
        expected_version=commitment.command_version,
    )
    key.refresh_from_db()
    assert key.generation == 5
    changes = list(SchedulingReleaseDependencyChange.objects.filter(dependency=key))
    assert {change.generation for change in changes} == {2, 3, 4, 5}
    assert {change.source_audit.target_type for change in changes} == {
        "workforce.shift_demand",
        "workforce.shift_commitment",
    }
    assert len({change.source_audit_id for change in changes}) == 4


def test_availability_withdrawal_advances_tracked_plan_without_editing_shift(world):
    plan = _availability_plan(world)
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    shifts._claim(world, demand)
    plan_key = _track(world, "workforce_availability", plan.id)
    demand_key = _track(world, "workforce_demand", demand.id)
    withdraw_person_availability(
        **_personal(world), expected_version=plan.command_version
    )
    plan.refresh_from_db()
    plan_key.refresh_from_db()
    demand_key.refresh_from_db()
    assert plan.status == "withdrawn"
    assert plan_key.generation == 2
    assert demand_key.generation == 1
    assert SchedulingReleaseDependencyChange.objects.get().dependency_id == plan_key.id


def test_saving_formerly_shared_availability_as_private_draft_invalidates_coverage(
    world,
):
    plan = _availability_plan(world)
    key = _track(world, "workforce_availability", plan.id)
    save_person_availability(
        **_personal(world),
        expected_version=plan.command_version,
        status="draft",
        windows=shifts._windows(),
    )
    key.refresh_from_db()
    assert key.generation == 2
    assert SchedulingReleaseDependencyChange.objects.get().source_audit.operation == (
        "workforce.person_availability.draft_saved"
    )


def test_assignment_end_invalidates_qualification_without_silently_changing_shifts(
    world,
):
    key = _track(world, "workforce_assignment", world.assignment.id)
    result = end_position_assignment(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=world.assignment.id,
        expected_version=world.assignment.command_version,
        reason="Synthetic responsibility ends",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    key.refresh_from_db()
    assert result.status == "ended"
    assert key.generation == 2
    change = SchedulingReleaseDependencyChange.objects.get()
    assert change.source_audit.target_id == world.assignment.id
    assert change.source_audit.operation == "workforce.position_assignment.end"


def test_skipped_availability_join_rolls_back_native_privacy_and_dependency_state(
    world,
):
    plan = _availability_plan(world)
    key = _track(world, "workforce_availability", plan.id)
    with (
        patch("maru.workforce.availability_commands.record_workforce_release_change"),
        pytest.raises(IntegrityError, match="native release invalidation"),
    ):
        withdraw_person_availability(
            **_personal(world), expected_version=plan.command_version
        )
    key.refresh_from_db()
    plan.refresh_from_db()
    assert key.generation == 1
    assert plan.status == "submitted"
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_skipped_assignment_join_rolls_back_native_authority_revocation(world):
    key = _track(world, "workforce_assignment", world.assignment.id)
    with (
        patch("maru.workforce.assignment_commands.record_workforce_release_change"),
        pytest.raises(IntegrityError, match="native release invalidation"),
    ):
        end_position_assignment(
            actor=world.reviewer,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=world.assignment.id,
            expected_version=world.assignment.command_version,
            reason="Synthetic must roll back",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    key.refresh_from_db()
    world.assignment.refresh_from_db()
    assert key.generation == 1
    assert world.assignment.status == "active"
    assert world.assignment.role_assignment.revoked_at is None
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_exact_availability_retry_does_not_append_another_change(world):
    plan = _availability_plan(world)
    key = _track(world, "workforce_availability", plan.id)
    request = {**_personal(world), "expected_version": plan.command_version}
    first = withdraw_person_availability(**request)
    replay = withdraw_person_availability(**request)
    assert replay.replayed
    assert replay.receipt_id == first.receipt_id
    key.refresh_from_db()
    assert key.generation == 2
    assert SchedulingReleaseDependencyChange.objects.count() == 1
