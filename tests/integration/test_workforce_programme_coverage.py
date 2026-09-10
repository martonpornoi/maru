"""Real owner reads preserve source versions, independent policy and privacy."""

from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.workforce import programme_queries as queries
from maru.workforce.availability_commands import withdraw_person_availability
from maru.workforce.models import PersonAvailabilityPlan, ShiftCommitment
from maru.workforce.programme_coverage import StaffingCoverageIntegrityError
from tests.integration.test_workforce_shifts import (
    _claim,
    _confirm,
    _create_demand,
    _open,
    _shift_world,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_real_coverage_lifecycle_and_withdrawal_preserve_accepted_work(monkeypatch):
    world = _shift_world()
    demand = _create_demand(world)
    arguments = {
        "actor_id": world.planner.id,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "demand_ids": (demand.id,),
        "correlation_id": uuid4(),
    }
    # The real current profile stays closed even for an authorized planner.
    with pytest.raises(queries.ProgrammeCoverageDeniedError):
        queries.load_programme_shift_coverage(**arguments)
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_coverage.read"
    ).exists()
    # Isolated source rehearsal only: retain real identity, capability, field,
    # scope and audit checks while admitting the dormant adapter for this test.
    monkeypatch.setattr(queries, "profile_allows_adapter", lambda *_args: True)
    draft = queries.load_programme_shift_coverage(**arguments)[0]
    assert draft.coverage.state == "draft"
    assert draft.coverage.draft_reconcilable
    _open(world, demand)
    claim = _claim(world, demand)
    claimed = queries.load_programme_shift_coverage(**arguments)[0]
    assert claimed.coverage.state == "awaiting_confirmation"
    assert claimed.coverage.current_confirmed == 0
    assert claimed.coverage.uncovered == 1
    assert claimed.evidence_digest != draft.evidence_digest
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    _confirm(world, commitment)
    with CaptureQueriesContext(connection) as captured:
        confirmed = queries.load_programme_shift_coverage(**arguments)[0]
    assert confirmed.coverage.state == "covered"
    assert confirmed.coverage.uncovered == 0
    assert confirmed.evidence_digest != claimed.evidence_digest
    assert confirmed.position_id == world.position.id
    assert (confirmed.starts_at, confirmed.ends_at) == (
        demand.starts_at,
        demand.ends_at,
    )
    selects = " ".join(
        q["sql"] for q in captured if q["sql"].lstrip().upper().startswith("SELECT")
    )
    assert '"confirmation_reason"' not in selects
    assert '"removal_reason"' not in selects
    assert '"briefing"' not in selects
    commitment.refresh_from_db()
    accepted_version = commitment.command_version
    plan = PersonAvailabilityPlan.objects.get(
        account=world.person, edition=world.edition
    )
    withdraw_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=plan.command_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    stale = queries.load_programme_shift_coverage(**arguments)[0]
    assert stale.coverage.state == "review_required"
    assert stale.coverage.current_confirmed == 0
    assert stale.coverage.uncovered == 1
    assert stale.evidence_digest != confirmed.evidence_digest
    commitment.refresh_from_db()
    assert commitment.command_version == accepted_version
    assert commitment.status == ShiftCommitment.Status.CONFIRMED
    assert (commitment.starts_at, commitment.ends_at) == (
        demand.starts_at,
        demand.ends_at,
    )
    assert (
        AuditEvent.objects.filter(operation="workforce.programme_coverage.read").count()
        == 4
    )
    with pytest.raises(StaffingCoverageIntegrityError):
        queries.load_programme_shift_coverage(
            **{**arguments, "demand_ids": (demand.id, uuid4())}
        )
    assert (
        AuditEvent.objects.filter(operation="workforce.programme_coverage.read").count()
        == 4
    )


def test_workforce_coverage_rejects_foreign_scope_and_overflow(monkeypatch):
    world = _shift_world()
    demand = _create_demand(world)
    _open(world, demand)
    _claim(world, demand)
    scope = {
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "demand_ids": (demand.id,),
    }
    for field in ("organization_id", "edition_id"):
        with pytest.raises(StaffingCoverageIntegrityError):
            queries._load_counts(**{**scope, field: uuid4()})
    monkeypatch.setattr(queries, "MAX_SHIFT_COMMITMENTS", 0)
    with pytest.raises(StaffingCoverageIntegrityError):
        queries._load_counts(**scope)
