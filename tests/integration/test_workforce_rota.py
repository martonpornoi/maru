"""Real scoped rota disclosure, complete inventory, audit and lifecycle evidence."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from django.db import DatabaseError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker

from maru.audit.models import AuditEvent
from maru.authorization.commands import grant_capability_direct
from maru.authorization.policy import resolve_edition_target
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.workforce import rota, rota_views, shift_queries
from maru.workforce.models import ShiftCommitment
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationMembershipFactory,
)
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_workforce_programme_personal_inputs import excluded_counts
from tests.integration.test_workforce_timetable_outputs import (
    scope as scope,  # noqa: PLC0414 - register the shared pytest fixture
)
from tests.support.authority import grant_board_controllers_edition_capability

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(scope):
    grant_board_controllers_edition_capability(scope.edition, "events.view_basic")
    return scope


def route(world, representation="download", **overrides):
    kwargs = {
        "organization_slug": world.edition.organization.slug,
        "series_slug": world.edition.series.slug,
        "edition_slug": world.edition.slug,
        **overrides,
    }
    return reverse(f"{representation}-workforce-rota", kwargs=kwargs)


def request(world, representation="download", *, actor=None):
    client = Client()
    client.force_login(actor or world.planner)
    return client.get(route(world, representation))


def body(response):
    with ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read("rota.json"))
        Draft202012Validator(
            json.loads(archive.read("schema.json")), format_checker=FormatChecker()
        ).validate(payload)
        assert archive.testzip() is None
        return payload, archive.read("rota.html").decode()


@pytest.mark.parametrize("representation", ["download", "print"])
def test_real_authorized_rota_is_minimized_audited_and_has_no_domain_effects(
    world, representation
):
    demand = shifts._create_demand(world, title="Rota <script>never execute</script>")
    shifts._open(world, demand)
    claim = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    shifts._confirm(world, commitment)
    commitment.refresh_from_db()
    before = excluded_counts()
    effects = (DomainEvent.objects.count(), OutboxMessage.objects.count())
    assert all(count == 0 for count in before.values())
    response = request(world, representation)
    assert response.status_code == 200
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "Cookie" in response["Vary"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert before == excluded_counts()
    assert effects == (DomainEvent.objects.count(), OutboxMessage.objects.count())
    audit = AuditEvent.objects.get(operation="workforce.rota.export")
    assert audit.principal_id == world.planner.id
    assert audit.organization_id == world.edition.organization_id
    assert audit.event_edition_id == world.edition.id
    assert audit.safe_metadata == {
        "policy_version": rota.POLICY_VERSION,
        "route_name": f"{representation}-workforce-rota",
        "http_method": "GET",
    }
    assert not audit.changed_fields
    assert str(commitment.account_id) not in json.dumps(audit.safe_metadata)
    if representation == "download":
        data, html = body(response)
        assert response["Content-Disposition"].endswith(f'{world.edition.id}.zip"')
        assert data["scope"]["edition_id"] == str(world.edition.id)
        item = data["shifts"][0]
        assert item["id"] == str(demand.id)
        assert item["version"] == demand.command_version
        assert item["local_starts_at"].endswith("+02:00")
        assert item["starts_at"].endswith("+00:00")
        row = item["commitments"][0]
        assert row["status"] == "confirmed"
        assert row["version"] == commitment.command_version
        assert str(world.person.id) not in json.dumps(data)
        assert not {
            "confirmation_reason",
            "removal_reason",
            "availability_windows",
            "availability_plan_id",
            "email",
            "confirmed_by",
            "position_assignment_id",
        }.intersection(row)
        assert commitment.confirmation_reason not in json.dumps(data)
    else:
        html = response.content.decode()
    assert "<script>never execute</script>" not in html
    assert "&lt;script&gt;never execute&lt;/script&gt;" in html
    assert "Private Availability windows" in html


def test_empty_edition_is_explicitly_not_staffing_readiness(world):
    response = request(world)
    assert response.status_code == 200
    data, html = body(response)
    assert data["shifts"] == []
    assert "No Shift demand" in html
    assert "does not establish staffing readiness" in html


def test_claim_and_retained_withdrawal_are_not_reported_as_confirmation(world):
    demand = shifts._create_demand(world)
    shifts._open(world, demand)
    claim = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    first, _ = body(request(world))
    assert first["shifts"][0]["claimed_count"] == 1
    assert first["shifts"][0]["confirmed_count"] == 0
    shifts.withdraw_shift_claim(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        commitment_id=commitment.id,
        expected_version=commitment.command_version,
        retry_key=shifts.uuid4(),
        correlation_id=shifts.uuid4(),
        source_channel="test",
    )
    second, _ = body(request(world))
    item = second["shifts"][0]
    assert item["claimed_count"] == item["confirmed_count"] == 0
    assert item["remaining_count"] == 1
    assert item["commitments"][0]["status"] == "removed"
    assert item["commitments"][0]["version"] > commitment.command_version


@pytest.mark.parametrize("representation", ["download", "print"])
def test_person_and_foreign_edition_are_denied_before_shift_inventory(
    world, representation
):
    client = Client()
    client.force_login(world.person)
    with CaptureQueriesContext(connection) as captured:
        denied = client.get(route(world, representation))
    assert denied.status_code == 403
    assert all('FROM "workforce_shiftdemand"' not in item["sql"] for item in captured)
    foreign = EventEditionFactory(adoption_profile_code="workforce_only")
    client.force_login(world.planner)
    foreign_route = route(
        world,
        representation,
        organization_slug=foreign.organization.slug,
        series_slug=foreign.series.slug,
        edition_slug=foreign.slug,
    )
    denied = client.get(foreign_route)
    assert denied.status_code == 403
    assert foreign.name.encode() not in denied.content
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


@pytest.mark.parametrize(
    "missing", ["events.view_basic", "workforce.view_shifts", "workforce.manage_shifts"]
)
def test_each_independent_permission_is_required_before_inventory(
    world, monkeypatch, missing
):
    original = rota.decide_verified_principal_exact_edition

    def deny(**kwargs):
        result = original(**kwargs)
        return (
            replace(result, allowed=False, fields=frozenset())
            if kwargs["capability_code"] == missing
            else result
        )

    monkeypatch.setattr(rota, "decide_verified_principal_exact_edition", deny)
    with CaptureQueriesContext(connection) as captured:
        denied = request(world)
    assert denied.status_code == 403
    assert all('FROM "workforce_shiftdemand"' not in item["sql"] for item in captured)


def test_partial_source_field_ceiling_cannot_export(world, monkeypatch):
    original = rota.decide_verified_principal_exact_edition

    def partial(**kwargs):
        result = original(**kwargs)
        if kwargs["capability_code"] == "workforce.view_shifts":
            return replace(result, fields=result.fields - {"holder_display_labels"})
        return result

    monkeypatch.setattr(rota, "decide_verified_principal_exact_edition", partial)
    assert request(world).status_code == 403
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_current_account_is_rechecked_after_serialization(world, monkeypatch):
    exporter = AccountFactory()
    OrganizationMembershipFactory(
        organization=world.edition.organization, account=exporter
    )
    target = resolve_edition_target(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    for code in (
        "events.view_basic",
        "workforce.view_shifts",
        "workforce.manage_shifts",
    ):
        grant_capability_direct(
            actor=world.planner,
            approver=world.reviewer,
            recipient=exporter,
            capability_code=code,
            target=target,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Independently approve synthetic rota access.",
            correlation_id=shifts.uuid4(),
            source_channel="test",
        )
    original = rota.rota_package

    def withdraw_account(**kwargs):
        content = original(**kwargs)
        deactivate_person_account_for_platform_emergency(
            actor=AccountFactory(is_superuser=True, is_staff=True),
            account_id=exporter.id,
            reason="Synthetic rota disclosure withdrawal",
            correlation_id=shifts.uuid4(),
        )
        return content

    monkeypatch.setattr(rota_views, "rota_package", withdraw_account)
    response = request(world, actor=exporter)
    exporter.refresh_from_db()
    assert not exporter.is_active
    assert response.status_code == 403
    assert not response.content.startswith(b"PK")
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


@pytest.mark.parametrize("representation", ["download", "print"])
def test_audit_failure_releases_neither_names_nor_partial_package(
    world, monkeypatch, representation
):
    shifts._create_demand(world, title="Protected rota demand")

    def unavailable(*args, **kwargs):
        raise DatabaseError("Synthetic required audit failure")

    monkeypatch.setattr(rota, "append_audit", unavailable)
    response = request(world, representation)
    assert response.status_code == 503
    assert b"Protected rota demand" not in response.content
    assert not response.content.startswith(b"PK")
    assert "no-store" in response["Cache-Control"]


def test_complete_inventory_overflow_never_becomes_truncated_success(
    world, monkeypatch
):
    shifts._create_demand(world)
    monkeypatch.setattr(shift_queries, "MAX_SHIFT_DEMANDS", 0)
    response = request(world)
    assert response.status_code == 503
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_unsupported_profile_and_unknown_inputs_do_not_export(world):
    platform = AccountFactory(is_superuser=True, is_staff=True)
    foreign = EventEditionFactory()
    client = Client()
    client.force_login(platform)
    response = client.get(
        route(
            world,
            organization_slug=foreign.organization.slug,
            series_slug=foreign.series.slug,
            edition_slug=foreign.slug,
        )
    )
    assert response.status_code == 403
    client.force_login(world.planner)
    assert client.get(route(world) + "?person=someone").status_code == 400
    assert client.post(route(world), {}).status_code == 405
    assert client.head(route(world)).status_code == 405
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_shift_planning_exposes_links_only_with_full_export_authority(world):
    client = Client()
    client.force_login(world.planner)
    url = reverse(
        "organization-workforce-shifts",
        kwargs={
            "organization_slug": world.edition.organization.slug,
            "series_slug": world.edition.series.slug,
            "edition_slug": world.edition.slug,
        },
    )
    response = client.get(url)
    assert response.status_code == 200
    assert route(world).encode() in response.content
    assert route(world, "print").encode() in response.content


@pytest.mark.parametrize("permission", ["management", "fields"])
def test_permission_withdrawal_after_rendering_discards_prepared_bytes(
    world, monkeypatch, permission
):
    original_package = rota.rota_package
    original_decide = rota.decide_verified_principal_exact_edition

    def deny_current(**kwargs):
        decision = original_decide(**kwargs)
        if (
            permission == "management"
            and kwargs["capability_code"] == "workforce.manage_shifts"
        ):
            return replace(decision, allowed=False, fields=frozenset())
        if (
            permission == "fields"
            and kwargs["capability_code"] == "workforce.view_shifts"
        ):
            return replace(decision, fields=decision.fields - {"holder_display_labels"})
        return decision

    def render_then_withdraw(**kwargs):
        data = original_package(**kwargs)
        monkeypatch.setattr(
            rota, "decide_verified_principal_exact_edition", deny_current
        )
        return data

    monkeypatch.setattr(rota_views, "rota_package", render_then_withdraw)
    response = request(world)
    assert response.status_code == 403
    assert not response.content.startswith(b"PK")
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_metadata_movement_after_rendering_discards_prepared_bytes(world, monkeypatch):
    original_package = rota.rota_package
    original_reference = rota.resolve_edition_rota_reference

    def changed_reference(**kwargs):
        reference = original_reference(**kwargs)
        return replace(reference, aggregate_version=reference.aggregate_version + 1)

    def render_then_move(**kwargs):
        data = original_package(**kwargs)
        monkeypatch.setattr(rota, "resolve_edition_rota_reference", changed_reference)
        return data

    monkeypatch.setattr(rota_views, "rota_package", render_then_move)
    response = request(world)
    assert response.status_code == 503
    assert not response.content.startswith(b"PK")
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


@pytest.mark.parametrize("with_demand", [False, True])
def test_malformed_owner_time_zone_is_unavailable_without_names(
    world, monkeypatch, with_demand
):
    original_reference = rota.resolve_edition_rota_reference

    def invalid_reference(**kwargs):
        return replace(original_reference(**kwargs), time_zone="Invalid/Zone")

    if with_demand:
        shifts._create_demand(world, title="Private malformed-zone work")
    monkeypatch.setattr(rota, "resolve_edition_rota_reference", invalid_reference)
    response = request(world)
    assert response.status_code == 503
    assert b"Private malformed-zone work" not in response.content
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_print_size_refusal_precedes_read_audit(world, monkeypatch):
    monkeypatch.setattr(rota_views, "MAX_ROTA_BYTES", 1)
    response = request(world, "print")
    assert response.status_code == 503
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_render_failure_releases_no_snapshot_or_allow_evidence(world, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic template failure")

    monkeypatch.setattr(rota_views, "render_to_string", unavailable)
    response = request(world)
    assert response.status_code == 503
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_unverified_platform_session_cannot_export(world):
    actor = AccountFactory(is_superuser=True, is_staff=True, email_verified_at=None)
    response = request(world, actor=actor)
    assert response.status_code == 403
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()


def test_incomplete_metadata_admission_reads_no_event_or_parent_labels(
    world, monkeypatch
):
    original = rota.decide_verified_principal_exact_edition

    def partial(**kwargs):
        decision = original(**kwargs)
        return (
            replace(decision, fields=decision.fields - {"name"})
            if kwargs["capability_code"] == "events.view_basic"
            else decision
        )

    monkeypatch.setattr(rota, "decide_verified_principal_exact_edition", partial)
    actor = AccountFactory(is_superuser=True, is_staff=True)
    with CaptureQueriesContext(connection) as captured:
        response = request(world, actor=actor)
    assert response.status_code == 403
    for row in captured:
        projection = row["sql"].split(" FROM ", 1)[0]
        assert '"events_eventedition"."name"' not in projection
        assert '"organizations_organization"."name"' not in projection
        assert '"organizations_conventionseries"."name"' not in projection
    assert not AuditEvent.objects.filter(operation="workforce.rota.export").exists()
