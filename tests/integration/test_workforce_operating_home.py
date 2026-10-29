"""Real owner-state transitions and disclosure behind the operating home."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
import time_machine
from django.apps import apps
from django.db import DatabaseError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from maru.audit.models import AuditEvent
from maru.authorization.commands import grant_capability_direct, revoke_capability_grant
from maru.authorization.policy import resolve_edition_target
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.participation.models import Participation
from maru.workforce import operating_home as owner
from maru.workforce.availability_commands import withdraw_person_availability
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignmentCommandReceipt,
    ShiftDemandCommandReceipt,
)
from maru.workforce.shift_commands import complete_shift_demand, lock_shift_demand
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.support.authority import grant_board_controllers_edition_capability
from tests.support.workforce_home import (
    ANCHOR,
    approve_home_assignment,
    claim_home_shift,
    confirm_home_shift,
    create_home_shift,
    create_home_world,
    home_transition_arguments,
    open_home_shift,
    propose_home_assignment,
    share_home_availability,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world():
    with time_machine.travel(ANCHOR, tick=False):
        yield create_home_world()


def _read(world, actor=None):
    return owner.load_workforce_home_guidance(
        actor=actor or world.reviewer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        correlation_id=uuid4(),
        http_method="GET",
    )


def _codes(result):
    return {item.code for item in result.operating} if result is not None else set()


def _grant_viewer(world, *, capability="workforce.view_shifts", edition=None):
    viewer = AccountFactory()
    scope = edition or world.edition
    CapabilityGrantFactory(
        organization=scope.organization,
        edition=scope,
        principal=viewer,
        capability_code="events.view_basic",
    )
    CapabilityGrantFactory(
        organization=scope.organization,
        edition=scope,
        principal=viewer,
        capability_code=capability,
    )
    return viewer


def test_existing_owners_drive_complete_assignment_availability_shift_sequence(world):
    assert "assignment_plan" in _codes(_read(world))
    assignment = propose_home_assignment(world)
    assert "assignment_wait_review" in _codes(_read(world, world.manager))
    assert "assignment_review" in _codes(_read(world))
    assert "availability_wait" in _codes(_read(world))
    share_home_availability(world, status="draft")
    assert "availability_wait" in _codes(_read(world))
    approve_home_assignment(world, assignment)
    share_home_availability(world)
    assert "availability_shared" in _codes(_read(world))
    demand = create_home_shift(world)
    assert "shift_draft" in _codes(_read(world))
    open_home_shift(world, demand)
    assert "shift_coverage" in _codes(_read(world))
    commitment = claim_home_shift(world, demand)
    assert "shift_claims" in _codes(_read(world))
    confirm_home_shift(world, commitment)
    assert "shift_lock" in _codes(_read(world))
    lock_shift_demand(
        allow_understaffed=False, **home_transition_arguments(world, demand)
    )
    assert "shift_scheduled" in _codes(_read(world))
    with time_machine.travel(demand.ends_at, tick=False):
        assert "shift_complete" in _codes(_read(world))
        complete_shift_demand(**home_transition_arguments(world, demand))
        assert "shift_history" in _codes(_read(world))
    assert not Participation.objects.exists()


def test_home_never_serializes_person_labels_rationale_briefing_or_exact_availability(
    world,
):
    assignment = propose_home_assignment(world)
    approve_home_assignment(world, assignment)
    share_home_availability(world)
    demand = create_home_shift(world)
    open_home_shift(world, demand)
    claim_home_shift(world, demand)
    result = _read(world)
    assert "shift_claims" in _codes(result)
    assert "PRIVATE-HOME" not in repr(result)
    assert len(result.operating) <= 3
    availability = next(
        item for item in result.operating if item.code.startswith("availability")
    )
    assert availability.object_id is availability.due_at is None
    assert all(item.time_zone == "Europe/Budapest" for item in result.operating)


def test_shared_empty_withdrawn_and_missing_are_honest_separate_consequences(world):
    propose_home_assignment(world)
    assert "availability_wait" in _codes(_read(world))
    share_home_availability(world, empty=True)
    assert "availability_empty" in _codes(_read(world))
    plan = PersonAvailabilityPlan.objects.get(
        edition=world.edition, account=world.person
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
    assert "availability_withdrawn" in _codes(_read(world))


def test_current_shift_suitability_changes_follow_retained_availability_version(world):
    assignment = propose_home_assignment(world)
    approve_home_assignment(world, assignment)
    share_home_availability(world)
    demand = create_home_shift(world)
    open_home_shift(world, demand)
    commitment = claim_home_shift(world, demand)
    confirm_home_shift(world, commitment)
    share_home_availability(world)
    result = _read(world)
    item = next(item for item in result.operating if item.code.startswith("shift_"))
    assert item.code == "shift_changed"
    assert item.object_id == demand.id


def test_private_draft_edits_do_not_change_the_released_availability_signature(world):
    propose_home_assignment(world)
    share_home_availability(world, status="draft")
    context = owner._Context(
        world.reviewer, world.edition.organization_id, world.edition.id, uuid4(), "GET"
    )
    before = owner._read(context, "availability")
    share_home_availability(world, status="draft", empty=True)
    after = owner._read(context, "availability")
    assert before.signature == after.signature
    assert before.item.code == after.item.code == "availability_wait"


@pytest.mark.parametrize("missing", ["read", "fields", "scope"])
def test_manage_only_partial_field_and_foreign_scope_cannot_read_shift_facts(
    world, monkeypatch, missing
):
    capability = (
        "workforce.manage_shifts" if missing == "read" else "workforce.view_shifts"
    )
    edition = (
        EventEditionFactory(adoption_profile_code="workforce_only")
        if missing == "scope"
        else None
    )
    viewer = _grant_viewer(world, capability=capability, edition=edition)
    if missing == "fields":
        original = owner._decision

        def partial(context, code, fields):
            decision = original(context, code, fields)
            return (
                replace(decision, fields=frozenset({"shift_demands"}))
                if code == "workforce.view_shifts"
                else decision
            )

        monkeypatch.setattr(owner, "_decision", partial)
    source = Mock(side_effect=AssertionError("Unauthorized Shift source queried"))
    monkeypatch.setattr(owner, "_shifts", source)
    assert _read(world, viewer) is None
    source.assert_not_called()


def test_shift_reader_needs_no_assignment_or_availability_access(
    world,
):
    viewer = _grant_viewer(world)
    result = _read(world, viewer)
    assert result.setup is None
    assert _codes(result) == {"shift_plan"}


def test_cached_active_principal_cannot_survive_current_database_deactivation(world):
    viewer = _grant_viewer(world)
    assert viewer.is_active
    Account.objects.filter(pk=viewer.id).update(is_active=False)
    assert _read(world, viewer) is None


def test_one_audit_failure_is_generic_and_preserves_other_admitted_work(
    world, monkeypatch
):
    propose_home_assignment(world)
    monkeypatch.setattr(
        owner,
        "append_availability_read_audit",
        Mock(side_effect=DatabaseError("PRIVATE ERROR")),
    )
    result = _read(world)
    assert {"assignment_review", "availability_unavailable", "shift_plan"} <= _codes(
        result
    )
    failed = next(
        item for item in result.operating if item.code == "availability_unavailable"
    )
    assert failed.object_id is failed.due_at is failed.checked_at is None
    assert "PRIVATE ERROR" not in repr(result)


def test_one_real_source_change_recovers_with_a_complete_new_read(world, monkeypatch):
    original = owner._read
    changed = [False]

    def read(context, area):
        snapshot = original(context, area)
        if area == "assignments" and not changed[0]:
            changed[0] = True
            propose_home_assignment(world)
        return snapshot

    monkeypatch.setattr(owner, "_read", read)
    result = _read(world)
    assert "assignment_review" in _codes(result)


def test_persistent_movement_never_releases_a_target_or_all_clear(world, monkeypatch):
    original = owner._read

    def read(context, area):
        snapshot = original(context, area)
        return (
            replace(snapshot, signature=str(uuid4())) if area == "shifts" else snapshot
        )

    monkeypatch.setattr(owner, "_read", read)
    result = _read(world)
    assert "shifts_unavailable" in _codes(result)
    assert "assignment_plan" in _codes(result)


@pytest.mark.parametrize("area", ["assignments", "availability", "shifts"])
def test_complete_source_bounds_refuse_instead_of_truncating(world, monkeypatch, area):
    propose_home_assignment(world)
    create_home_shift(world)
    limit = {
        "assignments": "MAX_ASSIGNMENT_RECORDS",
        "availability": "MAX_AVAILABILITY_ASSIGNMENTS",
        "shifts": "MAX_SHIFT_DEMANDS",
    }[area]
    monkeypatch.setattr(owner, limit, 0)
    assert area + "_unavailable" in _codes(_read(world))


def test_read_only_home_creates_no_domain_receipts_events_or_unadopted_rows(world):
    before = (
        PositionAssignmentCommandReceipt.objects.count(),
        ShiftDemandCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    _read(world)
    after = (
        PositionAssignmentCommandReceipt.objects.count(),
        ShiftDemandCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    assert before == after
    assert AuditEvent.objects.filter(
        operation="workforce.shift_coverage.read",
        safe_metadata__route_name="admin:index",
    ).exists()
    for label in [
        "participation",
        "registration",
        "accreditation",
        "catalog",
        "charities",
    ]:
        for model in apps.get_app_config(label).get_models():
            assert not model.objects.exists(), model._meta.label


def test_actual_home_links_use_current_owner_routes_and_private_cache_policy(world):
    propose_home_assignment(world)
    client = Client()
    client.force_login(world.reviewer)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(world.edition.id)
    session.save()
    response = client.get("/admin/")
    assert response.status_code == 200
    text = response.content.decode()
    assert "Review a proposed Assignment" in text
    assert "Other team work" in text
    assert "PRIVATE-HOME" not in text
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]
    url = reverse(
        "organization-workforce-assignments",
        args=(
            world.edition.organization.slug,
            world.edition.series.slug,
            world.edition.slug,
        ),
    )
    assert client.get(url).status_code == 200


def _issued_viewer(world, capabilities):
    viewer = AccountFactory()
    target = resolve_edition_target(
        organization_id=world.edition.organization_id, edition_id=world.edition.id
    )
    grants = {}
    for capability in ("events.view_basic", *capabilities):
        grants[capability] = grant_capability_direct(
            actor=world.manager,
            approver=world.reviewer,
            recipient=viewer,
            capability_code=capability,
            target=target,
            effective_from=ANCHOR,
            expires_at=None,
            reason="Prepare exact-edition synthetic viewer authority.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    return viewer, target, grants


def test_real_revocation_during_read_audit_releases_no_shift_facts(world, monkeypatch):
    viewer, target, grants = _issued_viewer(world, ("workforce.view_shifts",))
    original = owner._audit

    def audit(context, area, decision, at):
        original(context, area, decision, at)
        revoke_capability_grant(
            actor=world.manager,
            target=target,
            grant_id=grants["workforce.view_shifts"].id,
            reason="Revoke the exact synthetic reader while its home read completes.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    monkeypatch.setattr(owner, "_audit", audit)
    assert _read(world, viewer) is None


def test_later_real_revocation_filters_an_already_audited_availability_area(
    world, monkeypatch
):
    propose_home_assignment(world)
    viewer, target, grants = _issued_viewer(
        world, ("workforce.view_shifts", "workforce.view_availability")
    )
    original = owner._audit

    def audit(context, area, decision, at):
        original(context, area, decision, at)
        if area == "shifts":
            revoke_capability_grant(
                actor=world.manager,
                target=target,
                grant_id=grants["workforce.view_availability"].id,
                reason="Revoke the earlier synthetic area before final release.",
                correlation_id=uuid4(),
                source_channel="test",
            )

    monkeypatch.setattr(owner, "_audit", audit)
    assert _codes(_read(world, viewer)) == {"shift_plan"}


def test_final_setup_dependency_failure_preserves_other_real_owner_reads(
    world, monkeypatch
):
    original = owner._decision

    def decide(context, capability, fields):
        if capability == "workforce.manage_structure":
            raise DatabaseError("Private setup dependency failure")
        return original(context, capability, fields)

    monkeypatch.setattr(owner, "_decision", decide)
    result = _read(world)
    assert result.setup.step == "unavailable"
    assert not result.setup.can_manage
    assert {"assignment_plan", "shift_plan"} <= _codes(result)


def test_expiry_boundary_invalidates_a_prepared_proposal_priority_and_refreshes(world):
    assignment = propose_home_assignment(world, expires_at=ANCHOR + timedelta(hours=1))
    approve_home_assignment(world, assignment)
    context = owner._Context(
        world.reviewer, world.edition.organization_id, world.edition.id, uuid4(), "GET"
    )
    snapshot = owner._stable(context, "assignments")
    assert snapshot.valid_until == assignment.expires_at
    with time_machine.travel(assignment.expires_at, tick=False):
        released = owner._release_area(
            context, ("assignments", snapshot.item, snapshot)
        )
        assert released.code == "assignments_unavailable"
        assert "assignment_end" in _codes(_read(world))


def test_operating_phases_follow_actual_owner_lifecycle_transitions(world):
    grant_board_controllers_edition_capability(world.edition, "events.transition")
    for phase in ("preparing", "ready", "live", "closing", "archived"):
        transition_edition(
            actor=world.manager,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            to_state=phase,
            reason="Exercise real synthetic lifecycle read consequences.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        codes = _codes(_read(world))
        expected = (
            "assignment_history"
            if phase == "archived"
            else "assignment_closing"
            if phase == "closing"
            else "assignment_plan"
        )
        assert expected in codes
        assert (
            "shift_history" if phase in {"closing", "archived"} else "shift_plan"
        ) in codes


def test_source_queries_are_bounded_without_loading_labels_or_private_period_values(
    world,
):
    assignment = propose_home_assignment(world)
    approve_home_assignment(world, assignment)
    share_home_availability(world)
    for offset in range(3):
        demand = create_home_shift(
            world,
            starts_at=ANCHOR + timedelta(hours=2 + offset * 2),
            ends_at=ANCHOR + timedelta(hours=3 + offset * 2),
        )
        open_home_shift(world, demand)
        claim_home_shift(world, demand)
    context = owner._Context(
        world.reviewer, world.edition.organization_id, world.edition.id, uuid4(), "GET"
    )
    reference = owner._reference(context)
    with CaptureQueriesContext(connection) as queries:
        availability, _signature = owner._availability(context, reference)
    assert availability.code == "availability_shared"
    assert len(queries) == 2
    assert all(
        "display_name" not in entry["sql"]
        and "starts_at" not in entry["sql"]
        and "ends_at" not in entry["sql"]
        for entry in queries
    )
    with CaptureQueriesContext(connection) as queries:
        shifts, _signature, _boundary = owner._shifts(
            context, reference, (True,), ANCHOR
        )
    assert shifts.code == "shift_claims"
    assert len(queries) == 2
    assert all(
        "display_name" not in entry["sql"]
        and '"briefing"' not in entry["sql"]
        and '"reason"' not in entry["sql"]
        for entry in queries
    )
