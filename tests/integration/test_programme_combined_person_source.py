"""Combined-person checks retain global rest without foreign disclosure."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from maru.audit.models import AuditEvent
from maru.programme import release_queries as programme_sources
from maru.programme.host_commands import invite_programme_host
from maru.programme.host_inputs import ProgrammeHostInvitationInput
from maru.programme.models import ProgrammeItem
from maru.workforce import programme_person_queries as sources
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.programme_release_queries import ProgrammeReleaseSourceDeniedError
from maru.workforce.programme_staffing_queries import ProgrammeStaffingUnavailableError
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_programme_placement_decisions import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_programme_release_sources import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import candidate_revision, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def combined_scope(assessed, monkeypatch):
    monkeypatch.setattr(
        programme_sources, "profile_allows_adapter", lambda *_args: True
    )
    return assessed


def load(scope):
    return sources.load_programme_combined_person_source(
        scope.request,
        candidate_id=scope.selection.candidate_id,
        candidate_revision_id=scope.selection.candidate_revision_id,
        expected_candidate_version=scope.selection.expected_candidate_version,
        programme_authorizer=scope.policy,
        scheduling_authorizer=scope.world.policy,
    )


def select_person_as_host(scope, person):
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    invited = invite_programme_host(
        **scope.common,
        item_id=item.id,
        invitation=ProgrammeHostInvitationInput(
            person.id,
            "host",
            "Synthetic host purpose",
            "Explicit synthetic invitation",
            item.aggregate_version,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=scope.policy,
    )
    original = scope.world.placement
    placed = place(
        scope.world,
        intent=replace(
            original,
            host_presences=(
                replace(original.host_presences[0], host_id=invited.host_id),
            ),
        ),
        version=scope.selection.expected_candidate_version,
    )
    scope.selection = replace(
        scope.selection,
        candidate_revision_id=candidate_revision(placed).id,
        expected_candidate_version=placed.version,
    )


def test_complete_host_only_source_has_no_work_conflict(combined_scope):
    result = load(combined_scope)
    assert result.person_state == result.rest_state == "satisfied"
    assert result.consequences == ()
    assert result == load(combined_scope)
    assert AuditEvent.objects.filter(
        operation="workforce.programme_release.person_conflicts"
    ).exists()


def test_authorized_planner_approver_and_publisher_observe_same_source_fingerprint(
    combined_scope,
):
    first = load(combined_scope)
    for _role in ("approver", "publisher"):
        actor = AccountFactory()
        CapabilityGrantFactory(
            organization_id=combined_scope.request.organization_id,
            edition_id=combined_scope.request.edition_id,
            principal=actor,
            capability_code="workforce.view_shifts",
        )
        other = replace(
            combined_scope.request, actor_id=actor.id, correlation_id=uuid4()
        )
        result = sources.load_programme_combined_person_source(
            other,
            candidate_id=combined_scope.selection.candidate_id,
            candidate_revision_id=combined_scope.selection.candidate_revision_id,
            expected_candidate_version=combined_scope.selection.expected_candidate_version,
            programme_authorizer=combined_scope.policy,
            scheduling_authorizer=combined_scope.world.policy,
        )
        assert result == first


@pytest.mark.parametrize(
    ("starts", "ends", "rest", "code"),
    [
        ("07:45", "08:45", 30, "overlap"),
        ("07:00", "08:15", 30, "rest"),
        ("06:30", "07:15", 60, None),
    ],
)
def test_real_cross_tenant_commitments_protect_overlap_and_retained_rest(
    combined_scope, monkeypatch, starts, ends, rest, code
):
    monkeypatch.setattr(
        shifts,
        "_windows",
        lambda: (
            AvailabilityWindowInput(
                datetime(2030, 8, 2, 6, tzinfo=UTC),
                datetime(2030, 8, 2, 12, tzinfo=UTC),
                "preferred",
            ),
        ),
    )
    foreign = shifts._shift_world()
    demand = shifts._create_demand(
        foreign,
        title="Private foreign operations title",
        starts_at=f"2030-08-02T{starts}:00+00:00",
        ends_at=f"2030-08-02T{ends}:00+00:00",
        minimum_rest_minutes=rest,
    )
    shifts._open(foreign, demand)
    shifts._claim(foreign, demand)
    assert foreign.edition.organization_id != combined_scope.request.organization_id
    select_person_as_host(combined_scope, foreign.person)
    result = load(combined_scope)
    assert result.person_state == ("blocked" if code == "overlap" else "satisfied")
    assert result.rest_state == ("blocked" if code == "rest" else "satisfied")
    assert tuple(row.code for row in result.consequences) == ((code,) if code else ())
    assert all(
        row.occurrence_id == combined_scope.selection.occurrence_id
        for row in result.consequences
    )
    serialized = str(asdict(result))
    for private in (
        str(foreign.edition.id),
        str(foreign.edition.organization_id),
        str(demand.id),
        str(foreign.person.id),
        demand.title,
        demand.starts_at.isoformat(),
        demand.ends_at.isoformat(),
    ):
        assert private not in serialized


def test_person_closure_overflow_never_returns_a_partial_success(
    combined_scope, monkeypatch
):
    monkeypatch.setattr(sources, "MAX_PERSON_REFERENCE_BATCH", 1)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        load(combined_scope)


def test_final_required_audit_failure_withholds_all_consequences(
    combined_scope, monkeypatch
):
    before = AuditEvent.objects.count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic combined-person audit unavailable")

    monkeypatch.setattr(sources, "append_audit", fail)
    with pytest.raises(
        RuntimeError, match="Synthetic combined-person audit unavailable"
    ):
        load(combined_scope)
    assert AuditEvent.objects.count() == before


def test_workforce_release_permission_is_required_before_private_candidate_collection(
    combined_scope, monkeypatch
):
    def denied(_request):
        raise ProgrammeReleaseSourceDeniedError

    def unexpected(*_args, **_kwargs):
        pytest.fail("Candidate loaded before independent Workforce admission")

    monkeypatch.setattr(sources, "_authorize", denied)
    monkeypatch.setattr(sources, "load_release_candidate_source", unexpected)
    with pytest.raises(ProgrammeReleaseSourceDeniedError):
        load(combined_scope)
