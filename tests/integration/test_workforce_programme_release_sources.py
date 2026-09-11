"""Retained work stays complete through requirement retirement and successors."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.workforce import programme_release_queries as queries
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.programme_staffing_queries import ProgrammeStaffingUnavailableError
from maru.workforce.shift_commands import cancel_shift_demand, open_shift_demand
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import (
    apply,
    create,
    shift_attribution,
)
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def admitted(binding_world, monkeypatch):
    monkeypatch.setattr(queries, "profile_allows_adapter", lambda *_args: True)
    return binding_world


def load(scope, **overrides):
    return queries.load_programme_retained_work_source(
        scope.selection.request,
        **(
            {
                "occurrence_id": scope.selection.source.occurrence_id,
                "authorizer": scope.selection.policy,
            }
            | overrides
        ),
    )


def retire(scope):
    selection = scope.selection
    return change_programme_staffing_requirement(
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


def test_unbound_requirement_is_active_not_zero_work(admitted):
    source = load(admitted)
    assert source.active_requirement_ids == (admitted.selection.result.requirement_id,)
    assert source.demand_ids == ()
    assert source.operative_demand_ids == ()
    assert source == load(admitted)
    assert len(source.evidence_digest) == 64


def test_retirement_does_not_remove_operative_bound_demand(admitted):
    created = create(admitted)
    before = load(admitted)
    retire(admitted)
    after = load(admitted)
    assert after.active_requirement_ids == ()
    assert after.demand_ids == after.operative_demand_ids == (created.demand_id,)
    assert before.evidence_digest != after.evidence_digest
    assert before.item_version + 1 == after.item_version


def test_cancelled_work_remains_in_fingerprint_without_remaining_operative(admitted):
    created = create(admitted)
    retire(admitted)
    before = load(admitted)
    cancel_shift_demand(
        **shift_attribution(admitted), demand_id=created.demand_id, expected_version=1
    )
    after = load(admitted)
    assert after.active_requirement_ids == after.operative_demand_ids == ()
    assert after.demand_ids == before.demand_ids == (created.demand_id,)
    assert after.evidence_digest != before.evidence_digest


def test_successor_includes_complete_retained_predecessor_history(admitted):
    first = create(admitted)
    opened = open_shift_demand(
        **shift_attribution(admitted), demand_id=first.demand_id, expected_version=1
    )
    second = apply(
        admitted,
        ProgrammeStaffingBindingChange(
            Action.SUCCESSOR,
            admitted.selection.source,
            first.binding_id,
            1,
            first.demand_id,
            opened.resulting_version,
        ),
    )
    source = load(admitted)
    assert set(source.demand_ids) == {first.demand_id, second.demand_id}
    assert source.operative_demand_ids == (second.demand_id,)


def test_absent_occurrence_is_unavailable_not_no_staffing(admitted):
    with pytest.raises(ProgrammeStaffingUnavailableError):
        load(admitted, occurrence_id=uuid4())


def test_current_profiles_deny_new_release_source(binding_world):
    with pytest.raises(queries.ProgrammeReleaseSourceDeniedError):
        load(binding_world)


def test_coverage_field_does_not_grant_release_consequences(admitted, monkeypatch):
    original = queries.decide_verified_principal_exact_edition
    monkeypatch.setattr(
        queries,
        "decide_verified_principal_exact_edition",
        lambda **kwargs: replace(
            original(**kwargs), fields=frozenset({"coverage_states"})
        ),
    )
    with pytest.raises(queries.ProgrammeReleaseSourceDeniedError):
        load(admitted, occurrence_id="not parsed")


def test_workforce_authority_does_not_grant_programme_inventory(admitted, monkeypatch):
    policy = admitted.selection.policy
    original = policy.authorize
    monkeypatch.setattr(
        policy,
        "authorize",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset()),
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load(admitted)


@pytest.mark.parametrize(
    "bound", ["MAX_SHIFT_DEMANDS", "MAX_STAFFING_REQUIREMENTS_PER_ITEM"]
)
def test_overflow_is_unavailable_not_partial_work(admitted, monkeypatch, bound):
    create(admitted)
    monkeypatch.setattr(queries, bound, 0)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        load(admitted)


def test_required_audit_failure_withholds_source_and_rolls_back_reads(
    admitted, monkeypatch
):
    before = AuditEvent.objects.count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic release audit unavailable")

    monkeypatch.setattr(queries, "append_audit", fail)
    with pytest.raises(RuntimeError, match="Synthetic release audit unavailable"):
        load(admitted)
    assert AuditEvent.objects.count() == before


def test_source_does_not_select_private_binding_history_or_work_copy(admitted):
    create(admitted)
    with CaptureQueriesContext(connection) as captured:
        load(admitted)
    selects = [
        q["sql"]
        for q in captured
        if q["sql"].startswith("SELECT")
        and (
            '"workforce_programmeshiftbindingrevision"' in q["sql"]
            or '"workforce_shiftdemand"' in q["sql"]
        )
    ]
    assert selects
    for query in selects:
        assert all(
            f'"{field}"' not in query
            for field in ("reason", "briefing", "title", "request_digest", "actor_id")
        )
    assert AuditEvent.objects.filter(
        operation="workforce.programme_release.retained_work"
    ).exists()
