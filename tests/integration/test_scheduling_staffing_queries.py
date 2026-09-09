"""Real candidate coverage never silently follows source movement or accepted work."""

from dataclasses import asdict, replace
from uuid import uuid4

import pytest

from maru.audit.models import AuditEvent
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.scheduling import staffing_queries as queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.candidate_commands import copy_scheduling_candidate
from maru.workforce import programme_queries as coverage_queries
from maru.workforce.models import ShiftCommitment, ShiftDemand
from maru.workforce.shift_commands import (
    lock_shift_demand,
    open_shift_demand,
    update_shift_demand,
)
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import moved, next_request, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)
from tests.integration.test_workforce_programme_binding import (
    create,
    person_for,
    shift_attribution,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def staffing_world(binding_world, monkeypatch):
    monkeypatch.setattr(coverage_queries, "profile_allows_adapter", lambda *_args: True)
    return binding_world


def load(scope, **kwargs):
    return queries.load_planning_staffing(
        scope.selection.world.request,
        item_id=scope.selection.request.item_id,
        candidate_id=kwargs.pop("candidate_id", scope.selection.source.candidate_id),
        **{**scope.policies, **kwargs},
    )


def test_real_claim_confirmation_and_lock_preserve_current_source(
    staffing_world, monkeypatch
):
    scope = staffing_world
    person = person_for(scope, monkeypatch)
    (row,) = load(scope)
    assert row.source_state == "unbound"
    assert row.coverage.state == "unrequested"
    assert row.coverage.current_confirmed is None
    created = create(scope)
    (row,) = load(scope)
    assert row.source_state == "current"
    assert row.coverage.state == "draft"
    opened = open_shift_demand(
        **shift_attribution(scope), demand_id=created.demand_id, expected_version=1
    )
    (row,) = load(scope)
    assert row.source_state == "current"
    assert row.coverage.state == "open_gap"
    demand = ShiftDemand.objects.get(id=created.demand_id)
    claim = shifts._claim(person, demand)
    (row,) = load(scope)
    assert (
        row.coverage.state,
        row.coverage.pending_claims,
        row.coverage.current_confirmed,
    ) == ("awaiting_confirmation", 1, 0)
    shifts._confirm(person, ShiftCommitment.objects.get(id=claim.commitment_id))
    (row,) = load(scope)
    assert (row.coverage.current_confirmed, row.coverage.uncovered) == (1, 1)
    lock_shift_demand(
        **shift_attribution(scope),
        demand_id=created.demand_id,
        expected_version=opened.resulting_version,
        allow_understaffed=True,
    )
    (row,) = load(scope)
    assert row.source_state == "current"
    assert (row.coverage.state, row.coverage.uncovered) == ("locked_underfilled", 1)
    assert "actor_id" not in asdict(row)
    assert "reason" not in str(asdict(row))


def test_copy_does_not_rebind_and_movement_makes_coverage_stale(staffing_world):
    scope = staffing_world
    created = create(scope)
    original = load(scope)
    copied = copy_scheduling_candidate(
        next_request(scope.selection.world),
        source_revision_id=scope.selection.source.candidate_revision_id,
        label="Independent staffing alternative",
        expected_control_version=scope.selection.placed.control_version,
        authorizer=scope.selection.world.policy,
    )
    assert load(scope) == original
    (other,) = load(scope, candidate_id=copied.object_id)
    assert other.source_state == "stale"
    assert other.coverage.current_confirmed is None
    place(
        scope.selection.world,
        intent=moved(scope.selection.world),
        version=scope.selection.placed.version,
    )
    (row,) = load(scope)
    assert row.source_state == "stale"
    assert row.coverage.current_confirmed is row.coverage.uncovered is None
    demand = ShiftDemand.objects.get(id=created.demand_id)
    assert demand.command_version == 1
    assert demand.starts_at == scope.selection.terms.starts_at


def test_explicit_work_change_requires_reconciliation_not_a_false_current_badge(
    staffing_world,
):
    scope = staffing_world
    created = create(scope)
    terms = asdict(
        replace(scope.selection.terms, briefing="Changed standalone work instructions")
    )
    terms.pop("position_id")
    update_shift_demand(
        **shift_attribution(scope),
        demand_id=created.demand_id,
        expected_version=1,
        **terms,
    )
    (row,) = load(scope)
    assert row.source_state == "stale"
    assert row.coverage.pending_claims is row.coverage.current_confirmed is None


@pytest.mark.parametrize("retire", [False, True])
def test_changed_or_retired_requirement_keeps_original_work_and_nulls_coverage(
    staffing_world, retire
):
    scope = staffing_world
    created = create(scope)
    selected = scope.selection
    change_programme_staffing_requirement(
        **selected.common,
        change=replace(
            selected.change,
            requirement_id=selected.source.requirement_id,
            expected_requirement_version=1,
            expected_item_version=selected.result.resulting_item_version,
            expectation=None
            if retire
            else replace(selected.terms, required_headcount=3),
            retire=retire,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    (row,) = load(scope)
    assert row.source_state == "stale"
    assert row.coverage.uncovered is None
    assert ShiftDemand.objects.get(id=created.demand_id).required_headcount == 2


def test_missing_workforce_permission_is_withheld_even_before_a_binding(
    staffing_world, monkeypatch
):
    scope = staffing_world
    monkeypatch.setattr(
        coverage_queries, "profile_allows_adapter", lambda *_args: False
    )
    (row,) = load(scope)
    assert row.source_state == "withheld"
    assert row.coverage.uncovered is row.coverage.current_confirmed is None


def test_incomplete_dependency_is_unavailable_not_a_partial_layer(
    staffing_world, monkeypatch
):
    scope = staffing_world
    create(scope)
    monkeypatch.setattr(
        queries, "load_programme_bound_demand_coverage", lambda **_kwargs: ()
    )
    (row,) = load(scope)
    assert row.source_state == "unavailable"
    assert row.coverage.uncovered is None


def test_coverage_audit_failure_releases_no_counts_or_partial_audits(
    staffing_world, monkeypatch
):
    scope = staffing_world
    create(scope)
    before = AuditEvent.objects.count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic mandatory coverage audit failure")

    monkeypatch.setattr(coverage_queries, "append_audit", fail)
    with pytest.raises(
        RuntimeError, match="Synthetic mandatory coverage audit failure"
    ):
        load(scope)
    assert AuditEvent.objects.count() == before


@pytest.mark.parametrize("owner", ["programme", "scheduling"])
def test_owner_field_denial_prevents_the_entire_layer(
    staffing_world, monkeypatch, owner
):
    scope = staffing_world
    policy = scope.policies[f"{owner}_authorizer"]
    original = policy.authorize
    monkeypatch.setattr(
        policy,
        "authorize",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset()),
    )
    denied = (
        ProgrammeAuthorizationDeniedError
        if owner == "programme"
        else SchedulingAuthorizationDeniedError
    )
    with pytest.raises(denied):
        load(scope)
