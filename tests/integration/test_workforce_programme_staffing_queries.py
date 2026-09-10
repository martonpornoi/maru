"""Real owner authority, work impact and retained decision privacy for staffing."""

from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.events.adoption import profile_allows_adapter
from maru.workforce import programme_staffing_queries as queries
from maru.workforce.models import ShiftCommitment
from maru.workforce.shift_commands import cancel_shift_demand
from tests.integration.test_workforce_shifts import (
    _claim,
    _confirm,
    _create_demand,
    _open,
    _shift_world,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    fixture = _shift_world()
    monkeypatch.setattr(queries, "profile_allows_adapter", lambda *_args: True)
    return fixture


def arguments(world, demand):
    return {
        "actor_id": world.planner.id,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "demand_id": demand.id,
        "correlation_id": uuid4(),
    }


def test_exact_work_counts_track_lifecycle_without_releasing_private_decisions(world):
    demand = _create_demand(world)
    scope = arguments(world, demand)
    draft = queries.load_programme_staffing_demand(**scope)
    assert draft.status == "draft"
    assert draft.retained_commitments == draft.claimed == draft.confirmed == 0
    assert draft.expectation.briefing == demand.briefing
    _open(world, demand)
    claim = _claim(world, demand)
    claimed = queries.load_programme_staffing_demand(**scope)
    assert (claimed.retained_commitments, claimed.claimed, claimed.confirmed) == (
        1,
        1,
        0,
    )
    _confirm(world, ShiftCommitment.objects.get(id=claim.commitment_id))
    with CaptureQueriesContext(connection) as captured:
        confirmed = queries.load_programme_staffing_demand(**scope)
    assert (confirmed.retained_commitments, confirmed.claimed, confirmed.confirmed) == (
        1,
        0,
        1,
    )
    assert confirmed.expectation == draft.expectation
    assert confirmed.version > draft.version
    selects = " ".join(
        q["sql"] for q in captured if q["sql"].lstrip().upper().startswith("SELECT")
    )
    assert '"confirmation_reason"' not in selects
    assert '"removal_reason"' not in selects
    assert '"cancellation_reason"' not in selects
    demand.refresh_from_db()
    cancel_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        reason="Explicit synthetic cancellation",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    cancelled = queries.load_programme_staffing_demand(**scope)
    assert (
        cancelled.status,
        cancelled.retained_commitments,
        cancelled.claimed,
        cancelled.confirmed,
    ) == ("cancelled", 1, 0, 0)
    assert cancelled.expectation == draft.expectation
    assert (
        AuditEvent.objects.filter(
            operation="workforce.programme_staffing_demand.read"
        ).count()
        == 4
    )


def test_exact_adapter_remains_dormant_even_for_real_authorized_workforce_planner(
    world, monkeypatch
):
    monkeypatch.setattr(queries, "profile_allows_adapter", profile_allows_adapter)
    with pytest.raises(queries.ProgrammeStaffingDeniedError):
        queries.load_programme_staffing_demand(
            **arguments(world, _create_demand(world))
        )
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_staffing_demand.read"
    ).exists()


def test_personal_relationship_does_not_grant_organizer_work_impact(world):
    scope = arguments(world, _create_demand(world))
    scope["actor_id"] = world.person.id
    scope["demand_id"] = "invalid selection"
    with pytest.raises(queries.ProgrammeStaffingDeniedError):
        queries.load_programme_staffing_demand(**scope)


def test_missing_or_cross_scope_demands_never_return_partial_work(world):
    demand = _create_demand(world)
    scope = arguments(world, demand)
    with pytest.raises(queries.ProgrammeStaffingUnavailableError):
        queries.load_programme_staffing_demand(**{**scope, "demand_id": uuid4()})
    for field in ("organization_id", "edition_id"):
        target = {
            key: scope[key] for key in ("organization_id", "edition_id", "demand_id")
        }
        target[field] = uuid4()
        with pytest.raises(queries.ProgrammeStaffingUnavailableError):
            queries._load_demand(**target)


def test_audit_failure_withholds_read_and_preserves_demand(world, monkeypatch):
    demand = _create_demand(world)

    def failed_audit(*_args, **_kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(queries, "append_audit", failed_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        queries.load_programme_staffing_demand(**arguments(world, demand))
    demand.refresh_from_db()
    assert demand.status == "draft"
    assert demand.command_version == 1
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_staffing_demand.read"
    ).exists()
