"""Person-owned Availability command, privacy, adapter, and guard coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent
from maru.workforce.assignment_commands import (
    propose_position_assignment,
    reject_position_assignment,
)
from maru.workforce.availability_commands import (
    AvailabilityAuthorizationDeniedError,
    AvailabilityRelationshipRequiredError,
    AvailabilityRetryConflictError,
    save_person_availability,
    withdraw_person_availability,
)
from maru.workforce.availability_inputs import (
    AvailabilityWindowInput,
    availability_window_set_digest,
)
from maru.workforce.availability_queries import (
    load_organizer_availability_overview,
    load_person_availability,
)
from maru.workforce.models import (
    PersonAvailabilityCommandReceipt,
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from tests.factories import AccountFactory, EventEditionFactory, ParticipationFactory
from tests.support.authority import (
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)
from tests.workforce_helpers import create_department_for_test, save_position_for_test

if TYPE_CHECKING:
    from uuid import UUID

    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _AvailabilityWorld:
    """Synthetic exact-edition Availability scope with one open assignment."""

    edition: EventEdition
    organizer: Account
    approver: Account
    person: Account
    assignment: PositionAssignment


def _availability_world() -> _AvailabilityWorld:
    edition = EventEditionFactory()
    organizer: Account | None = None
    approver: Account | None = None
    for capability_code in (
        "workforce.view_structure",
        "workforce.manage_assignments",
        "workforce.view_availability",
        "authorization.manage_roles",
        "authorization.revoke",
    ):
        organizer, approver = grant_board_controllers_edition_capability(
            edition,
            capability_code,
        )
    assert organizer is not None
    assert approver is not None
    _role_actor, _role_approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="availability-steward",
        name="Availability steward",
        capability_codes=("workforce.view_structure",),
    )
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="availability-steward",
        name="Availability steward",
        description="Synthetic responsibility for Availability tests.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=organizer,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code="operations-availability-steward",
            title="Operations Availability Steward",
            description="Keep the synthetic operations desk ready.",
            headcount=2,
            capacity_codes=["volunteer"],
            status=Position.Status.OPEN,
            created_by=organizer,
        )
    )
    person = AccountFactory(display_name="Taylor Example")
    ParticipationFactory(
        account=person,
        organization=edition.organization,
        edition=edition,
    )
    proposed = propose_position_assignment(
        actor=organizer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        account_id=person.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Taylor is a known participant for this responsibility.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return _AvailabilityWorld(
        edition=edition,
        organizer=organizer,
        approver=approver,
        person=person,
        assignment=PositionAssignment.objects.get(pk=proposed.assignment_id),
    )


def _windows() -> tuple[AvailabilityWindowInput, ...]:
    return (
        AvailabilityWindowInput(
            starts_at=datetime.fromisoformat("2030-08-01T09:00:00+02:00"),
            ends_at=datetime.fromisoformat("2030-08-01T13:00:00+02:00"),
            preference="preferred",
        ),
        AvailabilityWindowInput(
            starts_at=datetime.fromisoformat("2030-08-02T10:00:00+02:00"),
            ends_at=datetime.fromisoformat("2030-08-02T18:00:00+02:00"),
            preference="available",
        ),
    )


def _save(
    world: _AvailabilityWorld,
    *,
    expected_version: int,
    status: str,
    windows: tuple[AvailabilityWindowInput, ...],
    retry_key: UUID | None = None,
):
    return save_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=expected_version,
        status=status,
        windows=windows,
        retry_key=retry_key or uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def _owner_url(world: _AvailabilityWorld, name: str) -> str:
    return reverse(
        name,
        kwargs={
            "organization_slug": world.edition.organization.slug,
            "series_slug": world.edition.series.slug,
            "edition_slug": world.edition.slug,
        },
    )


def _organizer_url(world: _AvailabilityWorld) -> str:
    return reverse(
        "organization-workforce-availability",
        kwargs={
            "organization_slug": world.edition.organization.slug,
            "series_slug": world.edition.series.slug,
            "edition_slug": world.edition.slug,
        },
    )


def _assert_private_no_store(response) -> None:
    directives = {
        item.strip().casefold() for item in response["Cache-Control"].split(",")
    }
    assert {"private", "no-store"}.issubset(directives)


def _truncate_availability_windows_without_test_reset() -> None:
    """Attempt the destructive statement with the test-only reset disabled."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute("TRUNCATE public.workforce_personavailabilitywindow")


def test_owner_commands_hide_drafts_and_publish_only_current_consequences() -> None:
    world = _availability_world()
    periods = _windows()
    draft_key = uuid4()

    draft = _save(
        world,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.DRAFT,
        windows=periods,
        retry_key=draft_key,
    )
    replay = _save(
        world,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.DRAFT,
        windows=periods,
        retry_key=draft_key,
    )

    assert draft.resulting_version == 1
    assert draft.window_count == 2
    assert replay.replayed
    assert replay.receipt_id == draft.receipt_id
    with pytest.raises(AvailabilityRetryConflictError):
        _save(
            world,
            expected_version=0,
            status=PersonAvailabilityPlan.Status.SUBMITTED,
            windows=periods,
            retry_key=draft_key,
        )

    owner_projection = load_person_availability(
        account=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    organizer_projection = load_organizer_availability_overview(edition=world.edition)
    assert owner_projection.state == "draft"
    assert len(owner_projection.windows) == 2
    assert organizer_projection.not_shared_count == 1
    assert organizer_projection.people[0].state == "not_shared"
    assert organizer_projection.people[0].windows == ()
    assert organizer_projection.people[0].shared_at is None

    shared = _save(
        world,
        expected_version=1,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=periods,
    )
    organizer_projection = load_organizer_availability_overview(edition=world.edition)
    assert shared.resulting_version == 2
    assert organizer_projection.shared_count == 1
    assert organizer_projection.people[0].account_label == "Taylor Example"
    assert organizer_projection.people[0].positions[0].position_title == (
        "Operations Availability Steward"
    )
    assert len(organizer_projection.people[0].windows) == 2

    unavailable = _save(
        world,
        expected_version=2,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=(),
    )
    organizer_projection = load_organizer_availability_overview(edition=world.edition)
    assert unavailable.resulting_version == 3
    assert organizer_projection.unavailable_count == 1
    assert organizer_projection.people[0].windows == ()

    withdrawn = withdraw_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=3,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    organizer_projection = load_organizer_availability_overview(edition=world.edition)
    assert withdrawn.resulting_version == 4
    assert withdrawn.window_count == 0
    assert organizer_projection.withdrawn_count == 1
    assert not PersonAvailabilityWindow.objects.filter(
        plan_id=withdrawn.plan_id
    ).exists()
    assert list(
        PersonAvailabilityCommandReceipt.objects.filter(plan_id=withdrawn.plan_id)
        .order_by("resulting_version")
        .values_list("action", flat=True)
    ) == ["draft_saved", "submitted", "submitted", "withdrawn"]

    audit_rows = AuditEvent.objects.filter(
        target_id=withdrawn.plan_id,
        operation__startswith="workforce.person_availability.",
    )
    assert audit_rows.count() == 4
    assert all(
        set(row.safe_metadata) == {"policy_version", "target_count"}
        for row in audit_rows
    )
    event_rows = DomainEvent.objects.filter(aggregate_id=withdrawn.plan_id)
    assert event_rows.count() == 4
    assert all(set(row.payload) == {"status", "window_count"} for row in event_rows)


def test_open_assignment_is_required_to_replace_but_not_to_withdraw() -> None:
    world = _availability_world()
    saved = _save(
        world,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=_windows(),
    )
    reject_position_assignment(
        actor=world.approver,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=world.assignment.id,
        expected_version=world.assignment.command_version,
        reason="Close the synthetic proposal after the person shared availability.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    with pytest.raises(AvailabilityRelationshipRequiredError):
        _save(
            world,
            expected_version=saved.resulting_version,
            status=PersonAvailabilityPlan.Status.DRAFT,
            windows=(),
        )

    owner = Client()
    owner.force_login(world.person)
    owner_page = owner.get(_owner_url(world, "my-workforce-availability"))
    assert owner_page.status_code == 200
    _assert_private_no_store(owner_page)
    owner_text = strip_tags(owner_page.content.decode())
    assert "Availability is read-only" in owner_text
    assert "08/01/2030 9 a.m.\N{EN DASH}08/01/2030 1 p.m." in owner_text
    assert "08/01/2030 7 a.m.\N{EN DASH}08/01/2030 11 a.m." not in owner_text

    withdrawn = withdraw_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=saved.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert withdrawn.status == PersonAvailabilityPlan.Status.WITHDRAWN

    platform_actor = AccountFactory(is_staff=True, is_superuser=True)
    with pytest.raises(AvailabilityAuthorizationDeniedError):
        save_person_availability(
            actor=platform_actor,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            expected_version=0,
            status=PersonAvailabilityPlan.Status.DRAFT,
            windows=(),
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_browser_surfaces_keep_private_drafts_out_of_organizer_view() -> None:
    world = _availability_world()
    owner = Client()
    owner.force_login(world.person)

    owner_page = owner.get(_owner_url(world, "my-workforce-availability"))
    assert owner_page.status_code == 200
    _assert_private_no_store(owner_page)
    owner_text = strip_tags(owner_page.content.decode())
    assert "My availability" in owner_text
    assert "Only you can see the periods" in owner_text
    assert "time outside them is unavailable" in owner_text
    command_form = owner_page.context["command_form"]
    saved = owner.post(
        _owner_url(world, "save-my-workforce-availability"),
        {
            "expected_version": command_form["expected_version"].value(),
            "retry_key": command_form["retry_key"].value(),
            "status": PersonAvailabilityPlan.Status.DRAFT,
            "windows-TOTAL_FORMS": "1",
            "windows-INITIAL_FORMS": "0",
            "windows-MIN_NUM_FORMS": "0",
            "windows-MAX_NUM_FORMS": "64",
            "windows-0-starts_at": "2030-08-01T09:00",
            "windows-0-ends_at": "2030-08-01T13:00",
            "windows-0-preference": "preferred",
        },
    )
    assert saved.status_code == 302

    organizer = Client()
    organizer.force_login(world.organizer)
    organizer_page = organizer.get(_organizer_url(world))
    assert organizer_page.status_code == 200
    _assert_private_no_store(organizer_page)
    organizer_text = strip_tags(organizer_page.content.decode())
    assert "Workforce availability" in organizer_text
    assert "Taylor Example" in organizer_text
    assert "Not shared" in organizer_text
    assert "2030-08-01" not in organizer_text
    assert "09:00" not in organizer_text
    assert AuditEvent.objects.filter(
        principal_id=world.organizer.id,
        capability_code="workforce.view_availability",
        operation="workforce.person_availability.read",
    ).exists()

    _save(
        world,
        expected_version=1,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=_windows(),
    )
    shared_page = organizer.get(_organizer_url(world))
    assert shared_page.status_code == 200
    shared_text = strip_tags(shared_page.content.decode())
    assert "Thu, Aug 1, 09:00\N{EN DASH}Thu, Aug 1, 13:00" in shared_text
    assert "Thu, Aug 1, 07:00\N{EN DASH}Thu, Aug 1, 11:00" not in shared_text

    denied = Client()
    denied.force_login(AccountFactory())
    assert denied.get(_organizer_url(world)).status_code == 403
    assert (
        owner.get(
            _owner_url(world, "my-workforce-availability"),
            {"unexpected": "private input"},
        ).status_code
        == 400
    )


def test_availability_api_is_strict_idempotent_and_scope_safe() -> None:
    world = _availability_world()
    owner_url = reverse(
        "api-workforce-my-availability",
        args=[world.edition.organization_id, world.edition.id],
    )
    organizer_url = reverse(
        "api-workforce-availability",
        args=[world.edition.organization_id, world.edition.id],
    )
    owner = APIClient()
    owner.force_authenticate(world.person)
    initial = owner.get(owner_url)
    assert initial.status_code == 200
    _assert_private_no_store(initial)
    assert initial.json()["state"] == "not_started"
    assert initial.json()["can_edit"] is True

    retry_key = uuid4()
    payload = {
        "expected_version": 0,
        "status": PersonAvailabilityPlan.Status.DRAFT,
        "windows": [
            {
                "starts_at": "2030-08-01T09:00:00+02:00",
                "ends_at": "2030-08-01T13:00:00+02:00",
                "preference": "preferred",
            }
        ],
    }
    nested_unknown = owner.put(
        owner_url,
        {
            **payload,
            "windows": [{**payload["windows"][0], "private_note": "reject me"}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    naive_time = owner.put(
        owner_url,
        {
            **payload,
            "windows": [
                {
                    **payload["windows"][0],
                    "starts_at": "2030-08-01T09:00:00",
                }
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    created = owner.put(
        owner_url,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replayed = owner.put(
        owner_url,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    assert nested_unknown.status_code == 400
    assert nested_unknown.json()["code"] == "unknown_input_field"
    assert naive_time.status_code == 400
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.json() == created.json()

    organizer = APIClient()
    organizer.force_authenticate(world.organizer)
    draft_view = organizer.get(organizer_url)
    assert draft_view.status_code == 200
    assert draft_view.json()["people"][0]["state"] == "not_shared"
    assert draft_view.json()["people"][0]["windows"] == []

    shared = owner.put(
        owner_url,
        {**payload, "expected_version": 1, "status": "submitted"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    shared_view = organizer.get(organizer_url)
    assert shared.status_code == 200
    assert shared_view.status_code == 200
    assert shared_view.json()["people"][0]["state"] == "shared"
    assert len(shared_view.json()["people"][0]["windows"]) == 1

    outsider = APIClient()
    outsider.force_authenticate(AccountFactory())
    malformed_denied = outsider.put(
        owner_url,
        {"private_sentinel": "must not reach request parsing"},
        format="json",
    )
    assert malformed_denied.status_code == 403
    assert malformed_denied.json()["code"] == ("availability_authorization_denied")
    assert outsider.get(organizer_url).status_code == 403

    other_edition = EventEditionFactory()
    cross_tenant_url = reverse(
        "api-workforce-my-availability",
        args=[other_edition.organization_id, other_edition.id],
    )
    assert owner.get(cross_tenant_url).status_code == 403

    withdraw_url = reverse(
        "api-workforce-my-availability-withdraw",
        args=[world.edition.organization_id, world.edition.id],
    )
    withdrawn = owner.post(
        withdraw_url,
        {"expected_version": 2},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert withdrawn.json()["window_count"] == 0


def test_database_guards_require_evidence_and_complete_replacements() -> None:
    world = _availability_world()
    empty_digest = availability_window_set_digest(())

    with (
        pytest.raises(IntegrityError, match="lacks exact command evidence"),
        transaction.atomic(),
    ):
        PersonAvailabilityPlan.objects.create(
            organization=world.edition.organization,
            edition=world.edition,
            account=world.person,
            status=PersonAvailabilityPlan.Status.DRAFT,
            time_zone=world.edition.time_zone,
            command_version=1,
            window_count=0,
            window_set_digest=empty_digest,
            submitted_at=None,
            withdrawn_at=None,
        )
    assert not PersonAvailabilityPlan.objects.filter(account=world.person).exists()

    saved = _save(
        world,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=_windows(),
    )
    plan = PersonAvailabilityPlan.objects.get(pk=saved.plan_id)
    window = plan.windows.order_by("starts_at").first()
    assert window is not None

    with (
        pytest.raises(IntegrityError, match="replacement-only"),
        transaction.atomic(),
    ):
        PersonAvailabilityWindow.objects.filter(pk=window.pk).update(
            preference=PersonAvailabilityWindow.Preference.AVAILABLE
        )
    with (
        pytest.raises(IntegrityError, match="replace the complete"),
        transaction.atomic(),
    ):
        PersonAvailabilityWindow.objects.filter(pk=window.pk).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        PersonAvailabilityWindow.objects.bulk_create(
            [
                PersonAvailabilityWindow(
                    plan=plan,
                    starts_at=datetime.fromisoformat("2030-08-01T10:00:00+02:00"),
                    ends_at=datetime.fromisoformat("2030-08-01T12:00:00+02:00"),
                    preference=PersonAvailabilityWindow.Preference.AVAILABLE,
                    created_by_version=plan.command_version,
                )
            ]
        )
    with (
        pytest.raises(IntegrityError, match="platform account cannot retain"),
        transaction.atomic(),
    ):
        type(world.person).objects.filter(pk=world.person.pk).update(
            account_kind="platform_administrator",
            is_staff=True,
            is_superuser=True,
        )
    receipt = plan.command_receipts.get(resulting_version=1)
    with pytest.raises(ValidationError, match="immutable"):
        receipt.delete()
    with (
        pytest.raises(IntegrityError, match="receipts are immutable"),
        transaction.atomic(),
    ):
        PersonAvailabilityCommandReceipt.objects.filter(pk=receipt.pk).update(
            source_channel="rewritten"
        )
    with pytest.raises(DatabaseError, match="cannot be truncated"):
        _truncate_availability_windows_without_test_reset()
