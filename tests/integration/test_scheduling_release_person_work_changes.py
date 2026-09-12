"""Global person-work freshness retains native attribution without foreign keys."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from maru.workforce import shift_commands
from maru.workforce.models import ShiftCommitment
from maru.workforce.shift_commands import (
    cancel_shift_demand,
    claim_shift,
    withdraw_shift_claim,
)
from tests.factories import AccountFactory
from tests.integration import test_workforce_shifts as shifts

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _track(person):
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind="workforce_person_obligations",
            source_id=person.id,
        )


def _claim_request(world, demand):
    return {
        "actor": world.person,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "demand_id": demand.id,
        "expected_version": demand.command_version,
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def test_claim_and_withdraw_roundtrip_still_stales_captured_person_work():
    world = shifts._shift_world()
    key = _track(world.person)
    other_key = _track(world.planner)
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    key.refresh_from_db()
    assert key.generation == 1  # Demand publication alone creates no person work.
    request = _claim_request(world, demand)
    first = claim_shift(**request)
    retried = claim_shift(**request)
    assert retried.replayed
    assert retried.receipt_id == first.receipt_id
    withdraw_shift_claim(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        commitment_id=first.commitment_id,
        expected_version=first.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert not ShiftCommitment.objects.filter(
        account=world.person, status__in=("claimed", "confirmed")
    ).exists()
    key.refresh_from_db()
    other_key.refresh_from_db()
    assert (key.generation, other_key.generation) == (3, 1)
    changes = list(
        SchedulingReleaseDependencyChange.objects.filter(dependency=key).order_by(
            "generation"
        )
    )
    assert [row.generation for row in changes] == [2, 3]
    assert all(
        row.organization_id is None and row.edition_id is None for row in changes
    )
    assert all(
        row.source_audit.organization_id == world.edition.organization_id
        and row.source_audit.event_edition_id == world.edition.id
        for row in changes
    )
    assert {row.source_audit.operation for row in changes} == {
        "workforce.shift_commitment.claimed",
        "workforce.shift_commitment.withdrawn",
    }


def test_native_confirmation_and_bulk_cancellation_advance_exact_person_source():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    key = _track(world.person)
    claim = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    shifts._confirm(world, commitment)
    demand.refresh_from_db()
    cancel_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        reason="Synthetic bulk cancellation",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    key.refresh_from_db()
    assert key.generation == 4
    assert set(
        SchedulingReleaseDependencyChange.objects.filter(dependency=key).values_list(
            "source_audit__operation", flat=True
        )
    ) == {
        "workforce.shift_commitment.claimed",
        "workforce.shift_commitment.confirmed",
        "workforce.shift_commitment.cancelled",
    }


def test_missing_global_join_rolls_back_native_claim_and_all_its_evidence():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    key = _track(world.person)
    with (
        patch("maru.workforce.shift_commands.record_workforce_release_change"),
        pytest.raises(
            IntegrityError,
            match="person change requires its native release invalidation",
        ),
    ):
        shifts._claim(world, demand)
    key.refresh_from_db()
    assert key.generation == 1
    assert not ShiftCommitment.objects.filter(demand=demand).exists()
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_a_native_commitment_cannot_invalidate_a_different_person():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    _track(world.person)
    unrelated = _track(AccountFactory())
    original = shift_commands.record_workforce_release_change

    def wrong_person(evidence):
        original(evidence)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.maru_scheduling_record_native_release_change"
                "(%s, %s, %s)",
                [unrelated.kind, unrelated.source_id, evidence.audit_id],
            )

    with (
        patch(
            "maru.workforce.shift_commands.record_workforce_release_change",
            side_effect=wrong_person,
        ),
        pytest.raises(IntegrityError, match="exact current native mutation"),
    ):
        shifts._claim(world, demand)
    assert not ShiftCommitment.objects.filter(demand=demand).exists()
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_global_person_work_key_rejects_a_tenant_scope_and_identity_rebinding():
    world = shifts._shift_world()
    with pytest.raises(IntegrityError), transaction.atomic(), scheduling_writer():
        SchedulingReleaseDependencyKey.objects.create(
            kind="workforce_person_obligations",
            source_id=world.person.id,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
        )
    key = _track(world.person)
    with (
        pytest.raises(IntegrityError, match="immutable-identity"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE public.scheduling_schedulingreleasedependencykey "
            "SET source_id=%s WHERE id=%s",
            [world.planner.id, key.id],
        )


def test_another_editions_native_work_advances_the_same_opaque_person_generation():
    world = shifts._shift_world()
    other = shifts._shift_world()
    assert world.edition.organization_id != other.edition.organization_id
    shifts._activate_person(
        edition=other.edition,
        planner=other.planner,
        reviewer=other.reviewer,
        position=other.position,
        person=world.person,
    )
    key = _track(world.person)
    demand = shifts._create_demand(other)
    shifts._open(other, demand)
    claim = shifts._claim(other, demand, person=world.person)
    key.refresh_from_db()
    assert key.generation == 2
    assert key.organization_id is None
    assert key.edition_id is None
    change = SchedulingReleaseDependencyChange.objects.get(dependency=key)
    assert change.organization_id is None
    assert change.edition_id is None
    assert change.source_audit.target_id == claim.commitment_id
    assert change.source_audit.event_edition_id == other.edition.id
