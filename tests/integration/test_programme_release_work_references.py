"""Release work capture resolves exact native references without foreign disclosure."""

from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.programme.placement_queries import ProgrammePlacementReadRequest
from maru.scheduling import release_candidate_queries
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.models import SchedulingReleaseDependencyKey
from maru.workforce import programme_release_queries
from maru.workforce import programme_release_references as sources
from maru.workforce.models import ShiftCommitment, ShiftDemand
from maru.workforce.programme_release_queries import ProgrammeReleaseSourceDeniedError
from maru.workforce.programme_staffing_queries import ProgrammeStaffingUnavailableError
from maru.workforce.shift_commands import cancel_shift_demand, open_shift_demand
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
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
def references_scope(binding_world, monkeypatch):
    monkeypatch.setattr(
        programme_release_queries, "profile_allows_adapter", lambda *_args: True
    )
    monkeypatch.setattr(
        release_candidate_queries, "profile_allows_adapter", lambda *_args: True
    )
    return binding_world


def collect(scope, **overrides):
    selection = scope.selection
    request = ProgrammePlacementReadRequest(
        selection.request.actor_id,
        selection.request.organization_id,
        selection.request.edition_id,
        uuid4(),
    )
    return sources.collect_programme_release_work_references(
        request,
        **(
            {
                "candidate_id": selection.source.candidate_id,
                "candidate_revision_id": selection.source.candidate_revision_id,
                "expected_candidate_version": selection.placed.version,
                **scope.policies,
            }
            | overrides
        ),
    )


def native_work_references(scope):
    selection = scope.selection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT kind, source_id, placement_id, horizon, operational_ends_at "
            "FROM public.maru_scheduling_expected_release_dependencies"
            "(%s, %s, %s, %s) WHERE kind LIKE 'workforce_%%'",
            [
                selection.source.candidate_revision_id,
                selection.request.actor_id,
                selection.request.organization_id,
                selection.request.edition_id,
            ],
        )
        return set(cursor.fetchall())


def test_query_needs_enclosing_transaction(references_scope):
    with pytest.raises(ProgrammeStaffingUnavailableError):
        collect(references_scope)


def test_unbound_inventory_is_audited_without_person_locks_or_key_writes(
    references_scope,
):
    with transaction.atomic(), CaptureQueriesContext(connection) as captured:
        result = collect(references_scope)
    assert result.candidate_revision_id == (
        references_scope.selection.source.candidate_revision_id
    )
    assert result.demand_occurrences == result.commitments == ()
    assert not SchedulingReleaseDependencyKey.objects.exists()
    assert not any(
        'FROM "identity_account"' in row["sql"] and "FOR UPDATE" in row["sql"]
        for row in captured
    )
    assert (
        AuditEvent.objects.filter(
            operation="workforce.programme_release.work_references", outcome="allow"
        ).count()
        == 1
    )


def test_complete_work_lifecycle_retains_closed_demand_but_not_future_coverage(
    references_scope, monkeypatch
):
    scope = references_scope
    person = person_for(scope, monkeypatch)
    created = create(scope)
    open_shift_demand(
        **shift_attribution(scope), demand_id=created.demand_id, expected_version=1
    )
    demand = ShiftDemand.objects.get(id=created.demand_id)
    without_commitment = native_work_references(scope)
    claimed = shifts._claim(person, demand)
    commitment = ShiftCommitment.objects.get(id=claimed.commitment_id)
    with transaction.atomic():
        pending = collect(scope)
        pending_native = native_work_references(scope)
    assert {(row[0], row[1]) for row in pending_native} == {
        *((row[0], row[1]) for row in without_commitment),
        ("workforce_demand", demand.id),
        ("workforce_assignment", commitment.position_assignment_id),
        ("workforce_availability", commitment.availability_plan_id),
        ("workforce_person_obligations", person.person.id),
    }
    assert all(
        row[4] == commitment.ends_at
        for row in pending_native
        if row[0] in {"workforce_assignment", "workforce_availability"}
    )
    assert pending.demand_occurrences == (
        (demand.id, (scope.selection.source.occurrence_id,)),
    )
    assert pending.commitments == (
        sources.ProgrammeReleaseWorkReference(
            commitment.id,
            demand.id,
            person.person.id,
            commitment.position_assignment_id,
            commitment.availability_plan_id,
            commitment.ends_at,
            commitment.command_version,
            "claimed",
        ),
    )
    shifts._confirm(person, commitment)
    with transaction.atomic():
        confirmed = collect(scope)
        assert native_work_references(scope) == pending_native
    assert confirmed.commitments[0].status == "confirmed"
    assert confirmed.commitments[0].version == pending.commitments[0].version + 1
    demand.refresh_from_db()
    cancel_shift_demand(
        **shift_attribution(scope),
        demand_id=demand.id,
        expected_version=demand.command_version,
    )
    with transaction.atomic():
        cancelled = collect(scope)
        assert native_work_references(scope) == without_commitment
    assert cancelled.demand_occurrences == pending.demand_occurrences
    assert cancelled.commitments == ()
    assert all(
        private not in str(asdict(confirmed))
        for private in ("Prepare stage safely", "Stage preparation", "East stage")
    )


def test_additional_reference_field_is_required_before_candidate_selection(
    references_scope,
):
    original = programme_release_queries.decide_verified_principal_exact_edition

    def ceiling(**arguments):
        decision = original(**arguments)
        return replace(
            decision, fields=decision.fields - {"release_dependency_references"}
        )

    with (
        transaction.atomic(),
        patch.object(
            programme_release_queries,
            "decide_verified_principal_exact_edition",
            ceiling,
        ),
        patch.object(sources, "load_release_candidate_source") as candidate_source,
        pytest.raises(ProgrammeReleaseSourceDeniedError),
    ):
        collect(references_scope, candidate_id="invalid selection")
    candidate_source.assert_not_called()


@pytest.mark.parametrize("identity", ["candidate_id", "candidate_revision_id"])
def test_missing_selected_candidate_cannot_return_partial_work(
    references_scope, identity
):
    with transaction.atomic(), pytest.raises(SchedulingUnavailableError):
        collect(references_scope, **{identity: uuid4()})


def test_candidate_permission_is_independent_of_workforce_authority(references_scope):
    with transaction.atomic(), pytest.raises(SchedulingAuthorizationDeniedError):
        collect(references_scope, scheduling_authorizer=DEFAULT_SCHEDULING_AUTHORIZER)


def test_bounded_commitments_never_return_partial_references(
    references_scope, monkeypatch
):
    scope = references_scope
    person = person_for(scope, monkeypatch)
    created = create(scope)
    open_shift_demand(
        **shift_attribution(scope), demand_id=created.demand_id, expected_version=1
    )
    shifts._claim(person, ShiftDemand.objects.get(id=created.demand_id))
    monkeypatch.setattr(sources, "MAX_SHIFT_COMMITMENTS", 0)
    with transaction.atomic(), pytest.raises(ProgrammeStaffingUnavailableError):
        collect(scope)
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_release.work_references"
    ).exists()


def test_late_audit_failure_discards_all_nested_read_audits(references_scope):
    with (
        transaction.atomic(),
        patch.object(
            sources, "append_audit", side_effect=RuntimeError("Synthetic audit")
        ),
        pytest.raises(RuntimeError, match="Synthetic audit"),
    ):
        collect(references_scope)
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_release.retained_work"
    ).exists()
    assert not SchedulingReleaseDependencyKey.objects.exists()
