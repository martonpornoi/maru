"""Native Shift person locks precede narrower work rows and retain cleanup."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection

from maru.identity.queries import lock_account_references_for_evidence
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.workforce.models import ShiftCommitment
from maru.workforce.shift_commands import cancel_shift_demand
from tests.factories import AccountFactory
from tests.integration import test_workforce_shifts as shifts

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_confirmation_locks_complete_person_union_before_demand_or_commitment():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    claim = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    locked_sql = []

    def observe(execute, sql, params, many, context):
        if "FOR UPDATE" in sql:
            locked_sql.append(sql)
        return execute(sql, params, many, context)

    with (
        patch(
            "maru.workforce.shift_commands.lock_account_references_for_evidence",
            wraps=lock_account_references_for_evidence,
        ) as persons,
        connection.execute_wrapper(observe),
    ):
        shifts._confirm(world, commitment)
    persons.assert_called_once_with(
        account_ids=tuple(sorted((world.reviewer.id, world.person.id)))
    )
    identity_lock = next(
        i for i, sql in enumerate(locked_sql) if '"identity_account"' in sql
    )
    demand_lock = next(
        i for i, sql in enumerate(locked_sql) if '"workforce_shiftdemand"' in sql
    )
    commitment_lock = next(
        i for i, sql in enumerate(locked_sql) if '"workforce_shiftcommitment"' in sql
    )
    assert identity_lock < demand_lock < commitment_lock


def test_native_cancellation_can_lock_an_inactive_retained_worker_for_cleanup():
    world = shifts._shift_world()
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    claim = shifts._claim(world, demand)
    deactivate_person_account_for_platform_emergency(
        actor=AccountFactory(is_superuser=True, is_staff=True),
        account_id=world.person.id,
        reason="Synthetic inactive-worker cleanup exercise",
        correlation_id=uuid4(),
    )
    demand.refresh_from_db()
    with patch(
        "maru.workforce.shift_commands.lock_account_references_for_evidence",
        wraps=lock_account_references_for_evidence,
    ) as persons:
        cancel_shift_demand(
            actor=world.planner,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            demand_id=demand.id,
            expected_version=demand.command_version,
            reason="Release cancelled work without reactivating its person",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    persons.assert_called_once_with(
        account_ids=tuple(sorted((world.planner.id, world.person.id)))
    )
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    assert commitment.status == "removed"
    assert commitment.removal_kind == "cancelled"
