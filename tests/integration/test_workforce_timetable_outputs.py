"""Real Workforce-only personal output excludes candidates and attendee state."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.adoption import AdoptionProfileCode
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.workforce import timetable_queries as queries
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    end_position_assignment,
)
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignment,
    ShiftCommitment,
)
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)
from maru.workforce.shift_queries import ShiftReadLimitExceededError
from tests.factories import AccountFactory, OrganizationMembershipFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_workforce_assignment_commands import (
    _assignment_world,
    _propose,
)
from tests.integration.test_workforce_programme_personal_inputs import excluded_counts
from tests.support.authority import grant_board_controllers_edition_capability

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def scope():
    world = _assignment_world(adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY)
    person = AccountFactory()
    OrganizationMembershipFactory(
        organization=world.edition.organization, account=person
    )
    for code in ("workforce.manage_shifts", "workforce.view_shifts"):
        grant_board_controllers_edition_capability(world.edition, code)
    proposed = _propose(world, candidate=person)
    attribution = {
        "actor": world.approver,
        "organization_id": world.edition.organization_id,
        "series_id": world.edition.series_id,
        "edition_id": world.edition.id,
        "reason": "Synthetic personal timetable fixture",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    approved = approve_position_assignment(
        **attribution, assignment_id=proposed.assignment_id, expected_version=1
    )
    assignment = PositionAssignment.objects.get(id=approved.assignment_id)
    assert assignment.participation_capacity_id is None
    save_person_availability(
        actor=person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=shifts._windows(),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return SimpleNamespace(
        planner=world.proposer,
        reviewer=world.approver,
        person=person,
        edition=world.edition,
        position=world.position,
        assignment=assignment,
        attribution=attribution,
    )


def arguments(scope):
    return {
        "actor_id": scope.person.id,
        "organization_id": scope.edition.organization_id,
        "edition_id": scope.edition.id,
        "correlation_id": uuid4(),
    }


def accepted_work(scope):
    demand = shifts._create_demand(scope)
    shifts._open(scope, demand)
    claim = shifts._claim(scope, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    shifts._confirm(scope, commitment)
    commitment.refresh_from_db()
    return demand, commitment


def test_exact_person_output_is_audited_minimized_and_non_participation(scope):
    demand, commitment = accepted_work(scope)
    before = excluded_counts()
    assert all(value == 0 for value in before.values())
    effects = (DomainEvent.objects.count(), OutboxMessage.objects.count())
    with CaptureQueriesContext(connection) as captured:
        result = queries.load_personal_shift_timetable(**arguments(scope))
    assert len(result) == 1
    entry = result[0]
    assert entry.commitment_id == commitment.id
    assert entry.version == commitment.command_version
    assert entry.status == "confirmed"
    assert (entry.starts_at, entry.ends_at, entry.rest_ends_at) == (
        commitment.starts_at,
        commitment.ends_at,
        commitment.rest_ends_at,
    )
    assert entry.instructions.demand_id == demand.id
    assert entry.instructions.briefing == demand.briefing
    assert entry.instructions.version == demand.command_version
    assert before == excluded_counts()
    assert effects == (DomainEvent.objects.count(), OutboxMessage.objects.count())
    assert (
        AuditEvent.objects.filter(
            operation="workforce.personal_timetable.read",
            principal_id=scope.person.id,
            outcome="allow",
        ).count()
        == 1
    )
    sql = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "programme_',
        'FROM "scheduling_',
        'FROM "participation_',
        'FROM "registration_',
        'FROM "workforce_personavailability',
    ):
        assert excluded not in sql
    source_sql = "\n".join(
        row["sql"]
        for row in captured
        if 'FROM "workforce_shiftcommitment"' in row["sql"]
    )
    for excluded in (
        "confirmation_reason",
        "removed_by_id",
        "confirmed_by_id",
        "availability_plan_id",
        "availability_version",
    ):
        assert excluded not in source_sql


def test_unclaimed_work_is_not_owned_and_claim_is_not_confirmation(scope):
    demand = shifts._create_demand(scope)
    shifts._open(scope, demand)
    assert queries.load_personal_shift_timetable(**arguments(scope)) == ()
    claim = shifts._claim(scope, demand)
    result = queries.load_personal_shift_timetable(**arguments(scope))
    assert [(entry.commitment_id, entry.status) for entry in result] == [
        (claim.commitment_id, "claimed")
    ]
    assert (
        queries.load_personal_shift_timetable(
            **(arguments(scope) | {"actor_id": AccountFactory().id})
        )
        == ()
    )


def test_retained_history_survives_assignment_end_without_retiming_work(scope):
    _demand, commitment = accepted_work(scope)
    original = queries.load_personal_shift_timetable(**arguments(scope))
    end_position_assignment(
        **(scope.attribution | {"actor": scope.planner, "retry_key": uuid4()}),
        assignment_id=scope.assignment.id,
        expected_version=scope.assignment.command_version,
    )
    assert queries.load_personal_shift_timetable(**arguments(scope)) == original
    commitment.refresh_from_db()
    assert commitment.starts_at == original[0].starts_at


def test_inactive_person_cannot_read_retained_work(scope):
    accepted_work(scope)
    deactivate_person_account_for_platform_emergency(
        actor=AccountFactory(is_superuser=True, is_staff=True),
        account_id=scope.person.id,
        reason="Synthetic timetable disclosure withdrawal",
        correlation_id=uuid4(),
    )
    with (
        patch.object(queries, "_entries") as entries,
        pytest.raises(ShiftAuthorizationDeniedError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))
    entries.assert_not_called()


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_foreign_scope_denies_before_work_lookup(scope, field):
    with (
        patch.object(queries, "_entries") as entries,
        pytest.raises(ShiftAuthorizationDeniedError),
    ):
        queries.load_personal_shift_timetable(**(arguments(scope) | {field: uuid4()}))
    entries.assert_not_called()


def test_missing_exact_profile_adapter_and_partial_fields_cannot_disclose_work(scope):
    with (
        patch.object(queries, "profile_allows_adapter", return_value=False),
        pytest.raises(ShiftAuthorizationDeniedError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))
    incomplete = PolicyDecision(
        allowed=True, fields=frozenset(), obligations=frozenset(), reason_code="self"
    )
    with (
        patch.object(
            queries, "decide_verified_principal_exact_self", return_value=incomplete
        ),
        pytest.raises(ShiftAuthorizationDeniedError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))


def test_final_policy_change_withholds_already_loaded_personal_work(scope):
    accepted_work(scope)
    decision = queries._authorize(
        scope.person.id, scope.edition.organization_id, scope.edition.id
    )
    with (
        patch.object(
            queries,
            "decide_verified_principal_exact_self",
            side_effect=(decision, decision, replace(decision, allowed=False)),
        ),
        pytest.raises(ShiftAuthorizationDeniedError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))
    assert not AuditEvent.objects.filter(
        operation="workforce.personal_timetable.read"
    ).exists()


def test_failed_sensitive_read_audit_releases_no_work(scope):
    accepted_work(scope)
    with (
        patch.object(
            queries, "append_audit", side_effect=RuntimeError("audit unavailable")
        ),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))
    assert not AuditEvent.objects.filter(
        operation="workforce.personal_timetable.read"
    ).exists()


def test_oversized_or_unavailable_work_never_becomes_partial_success(scope):
    accepted_work(scope)
    with (
        patch.object(queries, "MAX_SHIFT_COMMITMENTS", 0),
        pytest.raises(ShiftReadLimitExceededError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))
    with (
        patch.object(queries, "_entries", side_effect=DatabaseError),
        pytest.raises(ShiftUnavailableError),
    ):
        queries.load_personal_shift_timetable(**arguments(scope))


@pytest.mark.parametrize("value", [None, "wrong", 0, True])
def test_malformed_personal_scope_denies_before_policy(value):
    with (
        patch.object(queries, "_authorize") as authorize,
        pytest.raises(ValidationError),
    ):
        queries.load_personal_shift_timetable(
            actor_id=value,
            organization_id=uuid4(),
            edition_id=uuid4(),
            correlation_id=uuid4(),
        )
    authorize.assert_not_called()
