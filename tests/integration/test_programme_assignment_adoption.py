"""Native exact-pair assignment preparation, not integrated profile activation."""

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from maru.participation.models import Participation, ParticipationCapacity
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    end_position_assignment,
)
from maru.workforce.models import PositionAssignment
from tests.factories import (
    AccountFactory,
    OrganizationMembershipFactory,
    RoleBundleFactory,
)
from tests.integration.test_workforce_assignment_commands import (
    _assignment_world,
    _propose,
)
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.integration, pytest.mark.django_db]
_MIGRATION = import_module(
    "maru.workforce.migrations.0029_programme_assignment_adoption"
)


@pytest.fixture
def programme_world(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    world = _assignment_world(adoption_profile_code="programme_operations")
    candidate = AccountFactory()
    OrganizationMembershipFactory(
        organization=world.edition.organization,
        account=candidate,
        relationship_label="Synthetic Programme volunteer",
    )
    return world, candidate


def test_exact_programme_assignment_approves_replays_and_ends_without_participation(
    programme_world,
):
    world, candidate = programme_world
    proposed = _propose(world, candidate=candidate)
    args = {
        "organization_id": world.edition.organization_id,
        "series_id": world.edition.series_id,
        "edition_id": world.edition.id,
        "assignment_id": proposed.assignment_id,
        "reason": "Independently approve this fictional responsibility.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    approved = approve_position_assignment(
        actor=world.approver, expected_version=1, **args
    )
    replay = approve_position_assignment(
        actor=world.approver, expected_version=1, **args
    )
    assert replay.replayed
    assert replay.assignment_id == approved.assignment_id
    assignment = PositionAssignment.objects.get(id=approved.assignment_id)
    assert assignment.status == "active"
    assert assignment.role_assignment_id is not None
    assert assignment.participation_capacity_id is None
    assert not Participation.objects.exists()
    assert not ParticipationCapacity.objects.exists()
    ended = end_position_assignment(
        actor=world.proposer,
        expected_version=2,
        **{**args, "retry_key": uuid4(), "reason": "End fictional responsibility."},
    )
    assignment.refresh_from_db()
    assert ended.status == "ended"
    assert assignment.role_assignment.revoked_at is not None
    assert assignment.participation_capacity_id is None
    assert not Participation.objects.exists()
    assert not ParticipationCapacity.objects.exists()


@pytest.mark.parametrize("attempt", ["participation", "self_approval"])
def test_programme_pair_keeps_native_participation_and_independence_guards(
    programme_world, attempt
):
    world, candidate = programme_world
    proposed = _propose(world, candidate=candidate)
    values, message = (
        ({"participation_capacity_id": uuid4()}, "cannot create Participation evidence")
        if attempt == "participation"
        else ({"approved_by_id": world.proposer.id}, "requires independent approval")
    )
    with pytest.raises(IntegrityError, match=message), transaction.atomic():
        PositionAssignment.objects.filter(id=proposed.assignment_id).update(**values)
    assignment = PositionAssignment.objects.get(id=proposed.assignment_id)
    assert assignment.status == "proposed"
    assert assignment.command_version == 1
    assert assignment.participation_capacity_id is None
    assert assignment.approved_by_id is None


def test_unused_assignment_guard_reverse_reapply_preserves_native_identity():
    with connection.cursor() as cursor:
        original = _MIGRATION._state(cursor)
    MigrationExecutor(connection).migrate(
        [("workforce", "0028_programme_starter_execution_fence")]
    )
    with connection.cursor() as cursor:
        previous = _MIGRATION._state(cursor)
    assert previous[:3] == original[:3]
    assert previous[4:] == original[4:]
    assert previous[3] == _MIGRATION.function_source(programme=False)
    MigrationExecutor(connection).migrate(
        [("workforce", "0029_programme_assignment_adoption")]
    )
    with connection.cursor() as cursor:
        assert _MIGRATION._state(cursor) == original


def test_any_retained_programme_edition_fences_assignment_downgrade(programme_world):
    recorded = set(MigrationExecutor(connection).loader.applied_migrations)
    with connection.cursor() as cursor:
        original = _MIGRATION._state(cursor)
    with pytest.raises(RuntimeError, match=r"fix[- ]forward"), transaction.atomic():
        MigrationExecutor(connection).migrate(
            [("workforce", "0028_programme_starter_execution_fence")]
        )
    with connection.cursor() as cursor:
        assert _MIGRATION._state(cursor) == original
    assert set(MigrationExecutor(connection).loader.applied_migrations) == recorded


def test_shared_non_programme_authority_also_fences_before_successor_removal():
    world = _assignment_world()
    RoleBundleFactory(
        organization=world.edition.organization,
        capability_codes=["scheduling.prepare_change_notices"],
    )
    with connection.cursor() as cursor:
        original = _MIGRATION._state(cursor)
    with pytest.raises(RuntimeError, match=r"fix[- ]forward"), transaction.atomic():
        MigrationExecutor(connection).migrate(
            [("workforce", "0027_programme_starter_downgrade_fence")]
        )
    with connection.cursor() as cursor:
        assert _MIGRATION._state(cursor) == original
    assert ("workforce", "0029_programme_assignment_adoption") in (
        MigrationExecutor(connection).loader.applied_migrations
    )


def test_changed_native_metadata_is_not_normalized_during_reversal():
    with connection.cursor() as cursor:
        original = _MIGRATION._state(cursor)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER FUNCTION public.maru_guard_workforce_assignment() IMMUTABLE"
            )
        with pytest.raises(RuntimeError, match="metadata"), transaction.atomic():
            _MIGRATION._replace(SimpleNamespace(connection=connection), programme=False)
        transaction.set_rollback(True)
    with connection.cursor() as cursor:
        assert _MIGRATION._state(cursor) == original
