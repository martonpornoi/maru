"""Complete trusted release checks cannot inherit planning success or hidden work."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.catalogs import ProgrammeReadinessConcern
from maru.programme.commands import configure_programme_readiness
from maru.programme.models import ProgrammeItem
from maru.scheduling import planning_queries
from maru.scheduling import release_preflight as sources
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_eligibility import ReleaseCheck
from maru.venues.bindings import edition_space_binding_id
from maru.venues.models import VenueBooking
from maru.venues.services import approve_venue_booking
from maru.workforce import programme_queries, programme_staffing_queries
from maru.workforce.programme_release_queries import ProgrammeReleaseSourceDeniedError
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration.test_programme_current_release_sources import (
    public_copy,
)
from tests.integration.test_programme_current_release_sources import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_placement_decisions import (
    apply,
    preview,
)
from tests.integration.test_programme_placement_decisions import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_programme_release_sources import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_evaluations import availability
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_reservations import admit_reservations, reserve

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def preflight_scope(release_scope, monkeypatch):
    for module in (sources, programme_queries, programme_staffing_queries):
        monkeypatch.setattr(module, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(sources, "profile_allows_conflict_source", lambda *_args: True)
    admit_reservations(release_scope.world, monkeypatch)
    return release_scope


def load(scope, **overrides):
    return sources.load_release_preflight(
        SchedulingReadRequest(
            scope.request.actor_id,
            scope.request.organization_id,
            scope.request.edition_id,
            uuid4(),
        ),
        **(
            {
                "candidate_id": scope.selection.candidate_id,
                "candidate_revision_id": scope.selection.candidate_revision_id,
                "expected_candidate_version": (
                    scope.selection.expected_candidate_version
                ),
                "programme_authorizer": scope.policy,
                "scheduling_authorizer": scope.world.policy,
            }
            | overrides
        ),
    )


def states(result):
    return {row.check.value: row.state.value for row in result.checks}


def ready(scope):
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    # Explicit owner exemptions exercise the fact that release-level public copy,
    # physical approval and placement assessments remain mandatory regardless.
    for concern in ProgrammeReadinessConcern:
        configured = configure_programme_readiness(
            **scope.common,
            item_id=item.id,
            concern=concern,
            disposition="not_applicable",
            expected_version=item.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            authorizer=scope.policy,
        )
        item.aggregate_version = configured.resulting_item_version
    scope.selection = replace(
        scope.selection, expected_item_version=item.aggregate_version
    )
    public_copy(scope, AccountFactory().id)
    apply(scope)
    apply(
        scope,
        preview(scope, sources.ProgrammePlacementDecisionKind.STAFFING_NOT_REQUIRED),
    )
    placed = SimpleNamespace(
        object_id=scope.selection.candidate_id,
        version=scope.selection.expected_candidate_version,
    )
    _, reservation = reserve(scope.world, placed=placed)
    booking = VenueBooking.objects.get(id=reservation.target_booking_id)
    approver = AccountFactory()
    CapabilityGrantFactory(
        organization_id=booking.organization_id,
        edition_id=booking.edition_id,
        principal_id=approver.id,
        capability_code="venues.manage_space_schedule",
        resource_binding_id=edition_space_binding_id(booking.space_selection_id),
        department_id=booking.space_selection.responsible_department_id,
    )
    approve_venue_booking(
        actor=approver,
        organization_id=booking.organization_id,
        edition_id=booking.edition_id,
        space_selection_id=booking.space_selection_id,
        booking_id=booking.id,
        expected_version=booking.aggregate_version,
        reason="Synthetic independent physical approval",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_all_ten_categories_report_absence_without_inventing_readiness(preflight_scope):
    result = load(preflight_scope)
    assert {row.check for row in result.checks} == set(ReleaseCheck)
    actual = states(result)
    assert actual["candidate"] == actual["physical_constraints"] == "satisfied"
    assert actual["public_copy"] == actual["accessibility_fit"] == "unavailable"
    assert actual["staffing"] == "unavailable"
    assert actual["physical_approval"] == "blocked"
    assert not result.eligibility.eligible_for_review


def test_complete_owner_sources_allow_review_but_create_no_approval(preflight_scope):
    ready(preflight_scope)
    before = DomainEvent.objects.count()
    result = load(preflight_scope)
    assert result.eligibility.eligible_for_review, (states(result), result.findings)
    assert states(result)["staffing"] == "not_applicable"
    assert result == load(preflight_scope)
    assert DomainEvent.objects.count() == before
    assert AuditEvent.objects.filter(
        operation="scheduling.query.release_preflight"
    ).exists()
    serialized = str(asdict(result))
    for hidden in (
        "Keep the front aisle",
        "Synthetic",
        "account_id",
        "actor_id",
        "person_key",
        "periods",
        "starts_at",
        "ends_at",
        "reason",
        "calendar",
    ):
        assert hidden not in serialized


def test_independent_roles_share_current_release_fingerprint(preflight_scope):
    ready(preflight_scope)
    expected = load(preflight_scope)
    for _ in range(2):
        actor = AccountFactory()
        CapabilityGrantFactory(
            organization_id=preflight_scope.request.organization_id,
            edition_id=preflight_scope.request.edition_id,
            principal_id=actor.id,
            capability_code="workforce.view_shifts",
        )
        preflight_scope.request = replace(preflight_scope.request, actor_id=actor.id)
        assert load(preflight_scope) == expected


def test_old_planning_success_cannot_replace_missing_physical_approval(preflight_scope):
    result = load(preflight_scope)
    assert (
        not result.findings
    )  # The old time/host/physical evaluator finds no conflict.
    assert "physical_approval" in result.eligibility.blocked_checks
    assert "public_copy" in result.eligibility.unavailable_checks


def test_warnings_remain_exact_and_unacknowledged(preflight_scope):
    ready(preflight_scope)
    availability(preflight_scope.world, preference=True)
    result = load(preflight_scope)
    assert result.eligibility.unacknowledged_warnings
    assert not result.eligibility.eligible_for_review
    assert any(row.code == "host_outside_preference" for row in result.findings)
    assert result == load(preflight_scope)


def test_required_audit_failure_releases_nothing_and_rolls_back_owner_audits(
    preflight_scope,
    monkeypatch,
):
    before = AuditEvent.objects.count()
    original = planning_queries._audit

    def fail_final(request, capability, purpose, *, scope):
        if purpose == "release_preflight":
            raise RuntimeError("synthetic required audit failure")
        return original(request, capability, purpose, scope=scope)

    monkeypatch.setattr(sources, "_audit", fail_final)
    with pytest.raises(RuntimeError, match="required audit failure"):
        load(preflight_scope)
    assert AuditEvent.objects.count() == before


def test_missing_person_closure_stops_before_narrower_owner_reads(
    preflight_scope, monkeypatch
):
    def denied(*_args, **_kwargs):
        raise ProgrammeReleaseSourceDeniedError

    monkeypatch.setattr(sources, "load_programme_combined_person_source", denied)
    monkeypatch.setattr(
        sources,
        "load_release_candidate_source",
        lambda *_args, **_kwargs: pytest.fail("No narrower read after denied closure"),
    )
    with pytest.raises(ProgrammeReleaseSourceDeniedError):
        load(preflight_scope)


def test_new_field_is_independent_of_old_planning_conflict_fields(preflight_scope):
    class OldConflictPolicy:
        def authorize(self, **kwargs):
            fields = kwargs["requested_fields"]
            return PolicyDecision(
                allowed=True,
                fields=fields - {"release_preflight"},
                obligations=frozenset({"audit"}),
                reason_code="synthetic_old_ceiling",
            )

    with pytest.raises(SchedulingAuthorizationDeniedError):
        load(preflight_scope, scheduling_authorizer=OldConflictPolicy())


def test_current_profile_cannot_mount_complete_preflight(preflight_scope, monkeypatch):
    monkeypatch.setattr(sources, "profile_allows_adapter", lambda *_args: False)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load(preflight_scope)


@pytest.mark.parametrize("field", ["candidate_id", "candidate_revision_id"])
def test_foreign_or_absent_exact_manifest_is_not_discoverable(preflight_scope, field):
    with pytest.raises(SchedulingUnavailableError):
        load(preflight_scope, **{field: uuid4()})


def test_stale_candidate_is_not_silently_reselected(preflight_scope):
    with pytest.raises(SchedulingUnavailableError):
        load(preflight_scope, expected_candidate_version=99)


def test_owner_authority_expiry_at_final_composition_releases_nothing(
    preflight_scope, monkeypatch
):
    original = sources._collect
    before = AuditEvent.objects.count()

    def collect_then_expire(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(
            preflight_scope.policy,
            "authorize",
            lambda **_kwargs: PolicyDecision(
                allowed=False,
                fields=frozenset(),
                obligations=frozenset(),
                reason_code="synthetic_expiry",
            ),
        )
        return result

    monkeypatch.setattr(sources, "_collect", collect_then_expire)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load(preflight_scope)
    assert AuditEvent.objects.count() == before


def test_physical_source_change_during_collection_cannot_mix_snapshots(
    preflight_scope, monkeypatch
):
    original = sources.load_venue_scheduling_dependencies
    calls = 0

    def changed(**kwargs):
        nonlocal calls
        result = original(**kwargs)
        calls += 1
        return (
            replace(result, edition_version=result.edition_version + 1)
            if calls == 2
            else result
        )

    monkeypatch.setattr(sources, "load_venue_scheduling_dependencies", changed)
    with pytest.raises(SchedulingUnavailableError):
        load(preflight_scope)
