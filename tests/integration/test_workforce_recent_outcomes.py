"""Real governed receipts, exact admission and optional-component release."""

import secrets
from dataclasses import replace
from datetime import timedelta
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

import pytest
import time_machine
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from psycopg import sql

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.identity.models import Account
from maru.workforce import operating_home as owner
from maru.workforce import recent_outcomes as source
from maru.workforce.models import ShiftDemandCommandReceipt
from maru.workforce.shift_commands import (
    cancel_shift_demand,
    complete_shift_demand,
    lock_shift_demand,
    reopen_shift_demand,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_database_role_safety import (
    _create_role,
    _password_authenticated_default_database,
    _prepare_least_privilege_boundary,
    _provision_runtime_role,
    _public_privilege_snapshot,
    _restore_public_privileges,
)
from tests.support.workforce_home import (
    ANCHOR,
    create_home_shift,
    create_home_world,
    home_transition_arguments,
    open_home_shift,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world():
    with time_machine.travel(ANCHOR, tick=False):
        yield create_home_world()


def _read(world, actor=None, edition=None):
    edition = edition or world.edition
    return owner.load_workforce_home_guidance(
        actor=actor or world.reviewer,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        http_method="GET",
    )


def _facts(world):
    return source.read_recent_outcome_facts(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        at=ANCHOR,
    )


def _locked(world):
    demand = create_home_shift(world)
    open_home_shift(world, demand)
    args = home_transition_arguments(world, demand)
    result = lock_shift_demand(allow_understaffed=True, **args)
    demand.refresh_from_db()
    return demand, args, result


def _reader(world, capability="workforce.view_shifts", *, platform=False):
    actor = AccountFactory(is_staff=platform, is_superuser=platform)
    for code in ("events.view_basic", capability):
        CapabilityGrantFactory(
            organization=world.edition.organization,
            edition=world.edition,
            principal=actor,
            capability_code=code,
        )
    return actor


def test_real_lock_replay_reopen_completion_and_cancellation_follow_current_receipts(
    world,
):
    assert _read(world).recent_outcomes.state == "empty"
    demand, args, original = _locked(world)
    first = _read(world).recent_outcomes
    assert first.state == "present"
    assert first.items[0].outcome == "locked"
    replay = lock_shift_demand(allow_understaffed=True, **args)
    assert replay.receipt_id == original.receipt_id
    assert _read(world).recent_outcomes.items == first.items
    reopen_shift_demand(**home_transition_arguments(world, demand))
    assert _read(world).recent_outcomes.state == "empty"
    lock_shift_demand(
        allow_understaffed=True, **home_transition_arguments(world, demand)
    )
    with time_machine.travel(demand.ends_at, tick=False):
        complete_shift_demand(**home_transition_arguments(world, demand))
        assert _read(world).recent_outcomes.items[0].outcome == "completed"
        second = create_home_shift(world)
        cancel_shift_demand(**home_transition_arguments(world, second))
        outcomes = _read(world).recent_outcomes.items
        assert {item.outcome for item in outcomes} == {"completed", "cancelled"}
        assert len({item.demand_id for item in outcomes}) == 2


@pytest.mark.parametrize("count", [6, 128, 129])
def test_exact_real_candidate_and_display_bounds_without_sampling(world, count):
    for _number in range(count):
        demand = create_home_shift(world)
        cancel_shift_demand(**home_transition_arguments(world, demand))
    panel = _read(world).recent_outcomes
    if count == 129:
        assert panel.state == "unavailable"
        assert panel.items == ()
        # The ceiling is for current horizon candidates, not all retained history.
        with time_machine.travel(ANCHOR + timedelta(days=8), tick=False):
            assert _read(world).recent_outcomes.state == "empty"
    else:
        assert panel.state == "present"
        assert len(panel.items) == 5
        expected = tuple(
            ShiftDemandCommandReceipt.objects.filter(
                edition=world.edition, action="cancelled"
            )
            .order_by("-created_at", "-id", "-demand_id")
            .values_list("demand_id", flat=True)[:5]
        )
        assert tuple(item.demand_id for item in panel.items) == expected


def test_seven_elapsed_days_include_equality_then_expire(world):
    _locked(world)
    with time_machine.travel(ANCHOR + timedelta(days=7), tick=False):
        assert _read(world).recent_outcomes.state == "present"
    with time_machine.travel(ANCHOR + timedelta(days=7, microseconds=1), tick=False):
        assert _read(world).recent_outcomes.state == "empty"


def test_source_cost_has_three_bounded_metadata_label_queries_and_no_people(world):
    for _number in range(6):
        demand = create_home_shift(world)
        cancel_shift_demand(**home_transition_arguments(world, demand))
    with CaptureQueriesContext(connection) as queries:
        facts = _facts(world)
    assert len(facts.items) == 5
    assert len(queries) == 3
    statements = [row["sql"] for row in queries]
    assert "LIMIT 1025" in statements[0]
    assert "LIMIT 129" in statements[1]
    assert "LIMIT 5" in statements[2]
    assert '"title"' not in statements[0] + statements[1]
    assert all(
        '"reason"' not in statement
        and '"actor_id"' not in statement
        and '"retry_key"' not in statement
        and '"briefing"' not in statement
        and "COUNT(" not in statement
        and "identity_account" not in statement
        for statement in statements
    )


@pytest.mark.parametrize(
    "mode",
    ["manage_only", "partial", "inactive", "platform", "foreign", "other_edition"],
)
def test_missing_current_exact_full_read_admission_has_no_panel(
    world, monkeypatch, mode
):
    _locked(world)
    actor = _reader(
        world,
        "workforce.manage_shifts" if mode == "manage_only" else "workforce.view_shifts",
    )
    edition = None
    if mode == "partial":
        decide = owner._decision

        def partial(context, capability, fields):
            result = decide(context, capability, fields)
            return (
                replace(result, fields=frozenset({"shift_demands"}))
                if capability == "workforce.view_shifts"
                else result
            )

        monkeypatch.setattr(owner, "_decision", partial)
    elif mode == "inactive":
        Account.objects.filter(pk=actor.id).update(is_active=False)
    elif mode == "platform":
        actor = AccountFactory(is_staff=True, is_superuser=True)
    elif mode == "foreign":
        edition = EventEditionFactory(adoption_profile_code="workforce_only")
    elif mode == "other_edition":
        edition = EventEditionFactory(
            series=world.edition.series, adoption_profile_code="workforce_only"
        )
    result = _read(world, actor, edition)
    assert result is None or result.recent_outcomes is None


def test_reader_needs_no_manage_or_availability_permission(world):
    demand, _args, _receipt = _locked(world)
    actor = _reader(world)
    result = _read(world, actor)
    assert result.setup is None
    assert result.recent_outcomes.items[0].demand_id == demand.id


def test_mandatory_audit_is_minimized_and_home_adds_no_domain_write(world):
    _locked(world)
    before = (
        ShiftDemandCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    result = _read(world)
    assert result.recent_outcomes.state == "present"
    assert before == (
        ShiftDemandCommandReceipt.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    audit = AuditEvent.objects.filter(operation="workforce.shift_outcomes.read").get()
    assert audit.retention_class == "workforce-personal"
    assert audit.principal_id == world.reviewer.id
    assert audit.organization_id == world.edition.organization_id
    assert audit.event_edition_id == world.edition.id
    assert set(audit.safe_metadata) == {"policy_version", "route_name", "http_method"}
    assert "PRIVATE-HOME" not in repr(audit.safe_metadata)
    assert "PRIVATE-HOME-VOLUNTEER" not in repr(result)
    assert "PRIVATE-HOME-BRIEFING" not in repr(result)
    assert "PRIVATE-HOME-SHIFT-NAME" in repr(result.recent_outcomes)


def test_audit_failure_withholds_every_row_and_preserves_existing_guidance(
    world, monkeypatch
):
    _locked(world)
    monkeypatch.setattr(
        owner, "_audit_recent", Mock(side_effect=DatabaseError("PRIVATE SOURCE ERROR"))
    )
    result = _read(world)
    assert result.recent_outcomes.state == "unavailable"
    assert result.recent_outcomes.items == ()
    assert result.operating
    assert "PRIVATE SOURCE ERROR" not in repr(result)


def test_absent_matching_receipt_is_not_inner_joined_into_an_empty_result(
    world, monkeypatch
):
    _locked(world)
    original = ShiftDemandCommandReceipt.objects.filter

    def absent(*args, **kwargs):
        query = original(*args, **kwargs)
        return (
            query.none() if set(kwargs) == {"demand_id", "resulting_version"} else query
        )

    # Simulate missing evidence at the read dependency; native integrity guards
    # stay enabled, and no receipt/parent is deleted or rewritten.
    monkeypatch.setattr(ShiftDemandCommandReceipt.objects, "filter", absent)
    result = _read(world)
    assert result.recent_outcomes.state == "unavailable"
    assert result.recent_outcomes.items == ()
    assert result.operating


def test_parent_foundation_overflow_withholds_the_optional_component(
    world, monkeypatch
):
    _locked(world)
    monkeypatch.setattr(source, "MAX_SHIFT_DEMANDS", 0)
    result = _read(world)
    assert result.recent_outcomes.state == "unavailable"
    assert result.recent_outcomes.items == ()
    assert result.operating


@pytest.mark.parametrize("stage", ["audit", "final_area"])
def test_real_source_movement_retries_whole_component_and_keeps_older_areas_safe(
    world, monkeypatch, stage
):
    demand, _args, _receipt = _locked(world)
    changed = False
    original_audit, original_final = owner._audit_recent, owner._finalize_area

    def move():
        nonlocal changed
        if not changed:
            changed = True
            reopen_shift_demand(**home_transition_arguments(world, demand))

    def audit(*args):
        original_audit(*args)
        if stage == "audit":
            move()

    def final(*args):
        result = original_final(*args)
        if stage == "final_area":
            move()
        return result

    monkeypatch.setattr(owner, "_audit_recent", audit)
    monkeypatch.setattr(owner, "_finalize_area", final)
    result = _read(world)
    assert changed
    assert result.recent_outcomes.state == "empty"
    assert result.recent_outcomes.items == ()
    assert any(item.code == "shifts_unavailable" for item in result.operating)


def test_revocation_during_later_provider_fence_discards_prepared_labels(
    world, monkeypatch
):
    _locked(world)
    reader = _reader(world)
    original = owner._finalize_area
    changed = False

    def finalize(*args):
        nonlocal changed
        result = original(*args)
        if not changed:
            changed = True
            Account.objects.filter(pk=reader.id).update(is_active=False)
        return result

    monkeypatch.setattr(owner, "_finalize_area", finalize)
    result = _read(world, reader)
    assert changed
    assert result is None or result.recent_outcomes is None


def test_authenticated_home_is_private_and_destination_reauthorizes(world):
    demand, _args, _receipt = _locked(world)
    actor = _reader(world)
    client = Client()
    client.force_login(actor)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(world.edition.id)
    session.save()
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]
    assert b"Recent Shift outcomes" in response.content
    target = reverse(
        "organization-workforce-shift",
        args=[
            world.edition.organization.slug,
            world.edition.series.slug,
            world.edition.slug,
            demand.id,
        ],
    )
    assert target.encode() in response.content
    assert client.get(target).status_code == 200
    Account.objects.filter(pk=actor.id).update(is_active=False)
    denied = client.get(target)
    assert denied.status_code in {302, 403, 404}
    assert b"PRIVATE-HOME-SHIFT-NAME" not in denied.content


def test_genuine_restricted_runtime_login_can_release_only_minimized_outcomes(world):
    _locked(world)
    public = _public_privilege_snapshot()
    password = secrets.token_urlsafe(36)
    role = _create_role(password=password)
    try:
        with transaction.atomic():
            _prepare_least_privilege_boundary()
            _provision_runtime_role(role)
        started = monotonic()
        with _password_authenticated_default_database(
            role_name=role, password=password
        ):
            panel = _read(world).recent_outcomes
            assert panel.state == "present"
            assert len(panel.items) == 1
            assert "PRIVATE-HOME-VOLUNTEER" not in repr(panel)
        assert monotonic() - started < 5.0
    finally:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            _restore_public_privileges(public)
