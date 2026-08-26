"""Complete Shift demand, claim, confirmation, lock, and adapter coverage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import time_machine
from django.core.exceptions import ValidationError
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent
from maru.workforce import shift_views
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    propose_position_assignment,
)
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.models import (
    EditionStructureControl,
    PersonAvailabilityPlan,
    Position,
    PositionAssignment,
    PositionTemplate,
    ShiftCommitment,
    ShiftCommitmentCommandReceipt,
    ShiftDemand,
    ShiftDemandCommandReceipt,
)
from maru.workforce.shift_commands import (
    ShiftAvailabilityConflictError,
    ShiftCapacityConflictError,
    ShiftOverlapConflictError,
    ShiftStateConflictError,
    ShiftVersionConflictError,
    cancel_shift_demand,
    claim_shift,
    complete_shift_demand,
    confirm_shift_commitment,
    create_shift_demand,
    lock_shift_demand,
    open_shift_demand,
    withdraw_shift_claim,
)
from maru.workforce.shift_queries import (
    load_my_shift_overview,
    load_organizer_shift_overview,
)
from maru.workforce.structure_commands import (
    StructureDependencyConflictError,
    close_position,
)
from tests.factories import AccountFactory, EventEditionFactory, ParticipationFactory
from tests.support.authority import (
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)
from tests.workforce_helpers import create_department_for_test, save_position_for_test

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from uuid import UUID

    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _ShiftWorld:
    """Synthetic exact-edition Shift scope with independent controllers."""

    edition: EventEdition
    planner: Account
    reviewer: Account
    person: Account
    position: Position
    assignment: PositionAssignment


def _windows(
    *,
    starts_at: str = "2030-08-01T08:00:00+02:00",
    ends_at: str = "2030-08-01T18:00:00+02:00",
    preference: str = "preferred",
) -> tuple[AvailabilityWindowInput, ...]:
    return (
        AvailabilityWindowInput(
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
            preference=preference,
        ),
    )


def _activate_person(
    *,
    edition: EventEdition,
    planner: Account,
    reviewer: Account,
    position: Position,
    person: Account | None = None,
) -> tuple[Account, PositionAssignment]:
    person = person or AccountFactory()
    ParticipationFactory(
        account=person,
        organization=edition.organization,
        edition=edition,
    )
    proposed = propose_position_assignment(
        actor=planner,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        account_id=person.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="The known participant is ready for this exact Position.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    approve_position_assignment(
        actor=reviewer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        assignment_id=proposed.assignment_id,
        expected_version=1,
        reason="A second controller verified Position readiness.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    save_person_availability(
        actor=person,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=_windows(),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return person, PositionAssignment.objects.get(pk=proposed.assignment_id)


def _shift_world(*, position_headcount: int = 4) -> _ShiftWorld:
    edition = EventEditionFactory()
    planner: Account | None = None
    reviewer: Account | None = None
    for capability_code in (
        "workforce.view_structure",
        "workforce.manage_structure",
        "workforce.manage_assignments",
        "workforce.view_availability",
        "workforce.view_shifts",
        "workforce.manage_shifts",
        "authorization.manage_roles",
        "authorization.revoke",
    ):
        planner, reviewer = grant_board_controllers_edition_capability(
            edition,
            capability_code,
        )
    assert planner is not None
    assert reviewer is not None
    _actor, _approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="shift-steward",
        name="Shift steward",
        capability_codes=("workforce.view_structure",),
    )
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="shift-steward",
        name="Shift steward",
        description="Synthetic Position for complete Shift tests.",
        default_headcount=position_headcount,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=planner,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code="operations-shift-steward",
            title="Operations Shift Steward",
            description="Keep one operational station safe and staffed.",
            headcount=position_headcount,
            capacity_codes=["volunteer"],
            status=Position.Status.OPEN,
            created_by=planner,
        )
    )
    person, assignment = _activate_person(
        edition=edition,
        planner=planner,
        reviewer=reviewer,
        position=position,
        person=AccountFactory(display_name="Taylor Shift Example"),
    )
    return _ShiftWorld(
        edition=edition,
        planner=planner,
        reviewer=reviewer,
        person=person,
        position=position,
        assignment=assignment,
    )


def _create_demand(
    world: _ShiftWorld,
    *,
    title: str = "Morning operations desk",
    starts_at: str = "2030-08-01T09:00:00+02:00",
    ends_at: str = "2030-08-01T13:00:00+02:00",
    required_headcount: int = 1,
    minimum_rest_minutes: int = 60,
) -> ShiftDemand:
    result = create_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=world.position.id,
        title=title,
        location_label="Operations desk A",
        briefing="Receive handover, answer radio calls, and record open issues.",
        supervision_note="Check in with the Operations lead before starting.",
        starts_at=datetime.fromisoformat(starts_at),
        ends_at=datetime.fromisoformat(ends_at),
        required_headcount=required_headcount,
        break_minutes=30,
        minimum_rest_minutes=minimum_rest_minutes,
        reason="Create a visible, bounded operating period.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return ShiftDemand.objects.get(pk=result.demand_id)


def _open(world: _ShiftWorld, demand: ShiftDemand) -> None:
    open_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        reason="Publish this reviewed work to suitable Position holders.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    demand.refresh_from_db()


def _claim(world: _ShiftWorld, demand: ShiftDemand, *, person: Account | None = None):
    return claim_shift(
        actor=person or world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def _confirm(world: _ShiftWorld, commitment: ShiftCommitment):
    return confirm_shift_commitment(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        commitment_id=commitment.id,
        expected_version=commitment.command_version,
        reason="Current Position, Availability, rest, and coverage were reviewed.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_complete_shift_journey_rechecks_stale_availability_and_completes() -> None:
    world = _shift_world()
    demand = _create_demand(world)
    assert demand.status == ShiftDemand.Status.DRAFT
    _open(world, demand)

    personal = load_my_shift_overview(account=world.person, edition=world.edition)
    assert len(personal.suitable) == 1
    assert personal.suitable[0].preference == "preferred"
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    assert commitment.status == ShiftCommitment.Status.CLAIMED
    assert (
        load_my_shift_overview(
            account=world.person,
            edition=world.edition,
        ).suitable
        == ()
    )

    _confirm(world, commitment)
    commitment.refresh_from_db()
    assert commitment.status == ShiftCommitment.Status.CONFIRMED
    original_availability_version = commitment.availability_version

    save_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=original_availability_version,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=_windows(),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(ShiftAvailabilityConflictError):
        lock_shift_demand(
            actor=world.planner,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            demand_id=demand.id,
            expected_version=demand.command_version,
            allow_understaffed=False,
            reason="Do not lock stale confirmation evidence.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    _confirm(world, commitment)
    commitment.refresh_from_db()
    assert commitment.availability_version == original_availability_version + 1

    locked = lock_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        allow_understaffed=False,
        reason="All requested coverage is confirmed and current.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert locked.status == ShiftDemand.Status.LOCKED
    commitment.refresh_from_db()
    with pytest.raises(ShiftStateConflictError):
        withdraw_shift_claim(
            actor=world.person,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            commitment_id=commitment.id,
            expected_version=commitment.command_version,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    with time_machine.travel("2030-08-01T14:00:00+02:00"):
        completed = complete_shift_demand(
            actor=world.planner,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            demand_id=demand.id,
            expected_version=locked.resulting_version,
            reason="The operating period ended and handover was acknowledged.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    commitment.refresh_from_db()
    assert completed.status == ShiftDemand.Status.COMPLETED
    assert commitment.status == ShiftCommitment.Status.COMPLETED
    assert list(
        ShiftDemandCommandReceipt.objects.filter(demand=demand)
        .order_by("resulting_version")
        .values_list("action", flat=True)
    ) == ["created", "opened", "locked", "completed"]
    assert list(
        ShiftCommitmentCommandReceipt.objects.filter(commitment=commitment)
        .order_by("resulting_version")
        .values_list("action", flat=True)
    ) == ["claimed", "confirmed", "confirmed", "completed"]
    assert (
        AuditEvent.objects.filter(
            target_id__in=(demand.id, commitment.id),
            operation__startswith="workforce.shift_",
        ).count()
        >= 8
    )
    assert DomainEvent.objects.filter(
        aggregate_id__in=(demand.id, commitment.id)
    ).exists()


def test_capacity_overlap_withdrawal_and_cancellation_are_transactional() -> None:
    world = _shift_world()
    second_person, _assignment = _activate_person(
        edition=world.edition,
        planner=world.planner,
        reviewer=world.reviewer,
        position=world.position,
        person=AccountFactory(display_name="Morgan Shift Example"),
    )
    first = _create_demand(world, required_headcount=1)
    _open(world, first)
    claimed = _claim(world, first)
    with pytest.raises(ShiftCapacityConflictError):
        _claim(world, first, person=second_person)

    overlapping = _create_demand(
        world,
        title="Operations handover",
        starts_at="2030-08-01T13:30:00+02:00",
        ends_at="2030-08-01T15:00:00+02:00",
        minimum_rest_minutes=0,
    )
    _open(world, overlapping)
    with pytest.raises(ShiftOverlapConflictError):
        _claim(world, overlapping)

    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    withdraw_shift_claim(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        commitment_id=commitment.id,
        expected_version=commitment.command_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    commitment.refresh_from_db()
    withdrawal_receipt = commitment.command_receipts.get(
        action=ShiftCommitmentCommandReceipt.Action.WITHDRAWN
    )
    assert commitment.removal_reason == (
        "The person withdrew their own open Shift commitment."
    )
    assert withdrawal_receipt.reason == commitment.removal_reason
    replacement = _claim(world, first, person=second_person)
    cancel_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=first.id,
        expected_version=first.command_version,
        reason="The operating desk is no longer required.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert ShiftCommitment.objects.get(pk=replacement.commitment_id).status == (
        ShiftCommitment.Status.REMOVED
    )
    assert ShiftDemand.objects.get(pk=first.id).status == ShiftDemand.Status.CANCELLED


def test_concurrent_claims_cannot_overfill_one_remaining_place() -> None:
    world = _shift_world()
    second_person, _assignment = _activate_person(
        edition=world.edition,
        planner=world.planner,
        reviewer=world.reviewer,
        position=world.position,
        person=AccountFactory(display_name="Concurrent Shift Example"),
    )
    demand = _create_demand(world, required_headcount=1)
    _open(world, demand)
    start = Barrier(2)

    def invoke(person: Account) -> str:
        close_old_connections()
        try:
            start.wait(timeout=5)
            _claim(world, demand, person=person)
        except ShiftCapacityConflictError:
            return "capacity_rejected"
        finally:
            connections.close_all()
        return "claimed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(
            future.result()
            for future in (
                executor.submit(invoke, world.person),
                executor.submit(invoke, second_person),
            )
        )

    assert outcomes == ["capacity_rejected", "claimed"]
    assert (
        ShiftCommitment.objects.filter(
            demand=demand,
            status=ShiftCommitment.Status.CLAIMED,
        ).count()
        == 1
    )
    assert (
        ShiftCommitmentCommandReceipt.objects.filter(
            demand=demand,
            action=ShiftCommitmentCommandReceipt.Action.CLAIMED,
        ).count()
        == 1
    )


def _organizer_url(world: _ShiftWorld, name: str, **kwargs: UUID) -> str:
    return reverse(
        name,
        kwargs={
            "organization_slug": world.edition.organization.slug,
            "series_slug": world.edition.series.slug,
            "edition_slug": world.edition.slug,
            **kwargs,
        },
    )


def _personal_url(world: _ShiftWorld, name: str, **kwargs: UUID) -> str:
    return _organizer_url(world, name, **kwargs)


def _api_url(world: _ShiftWorld, name: str, **kwargs: UUID) -> str:
    return reverse(
        name,
        kwargs={
            "organization_id": world.edition.organization_id,
            "edition_id": world.edition.id,
            **kwargs,
        },
    )


def _api_demand_payload(
    world: _ShiftWorld,
    *,
    title: str,
    expected_version: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "position_id": str(world.position.id),
        "title": title,
        "location_label": "Operations desk B",
        "briefing": "Receive handover, answer radio calls, and record open issues.",
        "supervision_note": "Check in with the Operations lead before starting.",
        "starts_at": "2030-08-01T09:00:00+02:00",
        "ends_at": "2030-08-01T13:00:00+02:00",
        "required_headcount": 1,
        "break_minutes": 30,
        "minimum_rest_minutes": 60,
        "reason": "Keep the published operating plan accurate and reviewable.",
    }
    if expected_version is not None:
        payload["expected_version"] = expected_version
    return payload


def _web_demand_payload(
    world: _ShiftWorld,
    *,
    title: str,
    expected_version: int,
) -> dict[str, str]:
    return {
        "position_id": str(world.position.id),
        "title": title,
        "location_label": "Operations desk C",
        "briefing": "Receive handover, answer radio calls, and record open issues.",
        "supervision_note": "Check in with the Operations lead before starting.",
        "starts_at": "2030-08-01T09:00",
        "ends_at": "2030-08-01T13:00",
        "required_headcount": "1",
        "break_minutes": "30",
        "minimum_rest_minutes": "60",
        "reason": "Keep the browser-managed operating plan reviewable.",
        "expected_version": str(expected_version),
        "retry_key": str(uuid4()),
    }


def _web_reason_payload(*, expected_version: int, reason: str) -> dict[str, str]:
    return {
        "expected_version": str(expected_version),
        "retry_key": str(uuid4()),
        "reason": reason,
    }


def _raise_shift_version_conflict(**_kwargs: object) -> None:
    raise ShiftVersionConflictError


def test_browser_and_api_keep_personal_and_organizer_shift_views_separate() -> None:
    world = _shift_world()
    demand = _create_demand(world)
    _open(world, demand)
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)

    organizer = Client()
    organizer.force_login(world.planner)
    organizer_page = organizer.get(
        _organizer_url(
            world,
            "organization-workforce-shift",
            demand_id=demand.id,
        )
    )
    assert organizer_page.status_code == 200
    organizer_text = strip_tags(organizer_page.content.decode())
    assert "Shift planning" in organizer_text
    assert "Taylor Shift Example" in organizer_text
    assert "Morning operations desk" in organizer_text

    person = Client()
    person.force_login(world.person)
    personal_page = person.get(_personal_url(world, "my-workforce-shifts"))
    assert personal_page.status_code == 200
    personal_text = strip_tags(personal_page.content.decode())
    assert "My shifts" in personal_text
    assert "Your claims and commitments" in personal_text
    assert "An organizer has not confirmed" in personal_text
    assert "Receive handover, answer radio calls" in personal_text
    assert "You do not need to explain why" in personal_text
    assert "Create a visible, bounded operating period" not in personal_text

    organizer_api = APIClient()
    organizer_api.force_authenticate(world.planner)
    api_url = reverse(
        "api-workforce-shifts",
        kwargs={
            "organization_id": world.edition.organization_id,
            "edition_id": world.edition.id,
        },
    )
    response = organizer_api.get(api_url)
    assert response.status_code == 200
    assert response.json()["demands"][0]["commitments"][0]["account_label"] == (
        "Taylor Shift Example"
    )

    person_api = APIClient()
    person_api.force_authenticate(world.person)
    my_response = person_api.get(
        reverse(
            "api-workforce-my-shifts",
            kwargs={
                "organization_id": world.edition.organization_id,
                "edition_id": world.edition.id,
            },
        )
    )
    assert my_response.status_code == 200
    assert my_response.json()["commitments"][0]["id"] == str(commitment.id)
    assert my_response.json()["commitments"][0]["briefing"].startswith(
        "Receive handover"
    )
    assert my_response.json()["commitments"][0]["minimum_rest_minutes"] == 60
    assert "account_label" not in my_response.content.decode()

    withdraw_url = reverse(
        "api-workforce-shift-withdraw",
        kwargs={
            "organization_id": world.edition.organization_id,
            "edition_id": world.edition.id,
            "commitment_id": commitment.id,
        },
    )
    private_reason = "A private personal circumstance that must not be retained."
    rejected = person_api.post(
        withdraw_url,
        {
            "expected_version": commitment.command_version,
            "confirm": True,
            "reason": private_reason,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert rejected.status_code == 400
    accepted = person_api.post(
        withdraw_url,
        {"expected_version": commitment.command_version, "confirm": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert accepted.status_code == 200
    commitment.refresh_from_db()
    assert commitment.removal_kind == ShiftCommitment.RemovalKind.WITHDRAWN
    assert private_reason not in commitment.removal_reason


def test_strict_api_supports_the_complete_shift_management_journey() -> None:
    world = _shift_world()
    organizer = APIClient()
    organizer.force_authenticate(world.planner)
    collection_url = _api_url(world, "api-workforce-shifts")

    created = organizer.post(
        collection_url,
        _api_demand_payload(world, title="API operations desk"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert created.status_code == 201
    demand = ShiftDemand.objects.get(pk=created.json()["id"])
    detail_url = _api_url(world, "api-workforce-shift", demand_id=demand.id)
    detail = organizer.get(detail_url)
    assert detail.status_code == 200
    assert detail.json()["title"] == "API operations desk"

    updated = organizer.put(
        detail_url,
        _api_demand_payload(
            world,
            title="Updated API operations desk",
            expected_version=demand.command_version,
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert updated.status_code == 200
    demand.refresh_from_db()
    assert demand.title == "Updated API operations desk"

    opened = organizer.post(
        _api_url(world, "api-workforce-shift-open", demand_id=demand.id),
        {
            "expected_version": demand.command_version,
            "reason": "Publish reviewed coverage for suitable people.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert opened.status_code == 200
    demand.refresh_from_db()

    person = APIClient()
    person.force_authenticate(world.person)
    personal = person.get(_api_url(world, "api-workforce-my-shifts"))
    assert personal.status_code == 200
    assert personal.json()["suitable"][0]["id"] == str(demand.id)
    claimed = person.post(
        _api_url(world, "api-workforce-shift-claim", demand_id=demand.id),
        {"expected_version": demand.command_version},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert claimed.status_code == 200
    commitment = ShiftCommitment.objects.get(pk=claimed.json()["id"])

    confirmed = organizer.post(
        _api_url(
            world,
            "api-workforce-shift-confirm",
            commitment_id=commitment.id,
        ),
        {
            "expected_version": commitment.command_version,
            "reason": "Confirm current qualification and shared Availability.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert confirmed.status_code == 200
    commitment.refresh_from_db()
    demand.refresh_from_db()

    locked = organizer.post(
        _api_url(world, "api-workforce-shift-lock", demand_id=demand.id),
        {
            "expected_version": demand.command_version,
            "allow_understaffed": False,
            "reason": "Lock complete and current accountable coverage.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert locked.status_code == 200
    demand.refresh_from_db()
    reopened = organizer.post(
        _api_url(world, "api-workforce-shift-reopen", demand_id=demand.id),
        {
            "expected_version": demand.command_version,
            "reason": "Reopen coverage to reflect an operating change.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert reopened.status_code == 200
    demand.refresh_from_db()
    commitment.refresh_from_db()

    removed = organizer.post(
        _api_url(
            world,
            "api-workforce-shift-remove",
            commitment_id=commitment.id,
        ),
        {
            "expected_version": commitment.command_version,
            "reason": "Remove coverage because the operating plan changed.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert removed.status_code == 200
    demand.refresh_from_db()
    cancelled = organizer.post(
        _api_url(world, "api-workforce-shift-cancel", demand_id=demand.id),
        {
            "expected_version": demand.command_version,
            "reason": "The operating desk is no longer required.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ShiftDemand.Status.CANCELLED


def test_strict_api_completes_ended_locked_shift() -> None:
    world = _shift_world()
    organizer = APIClient()
    organizer.force_authenticate(world.planner)
    completing = _create_demand(
        world,
        title="API completion desk",
        starts_at="2030-08-01T14:00:00+02:00",
        ends_at="2030-08-01T16:00:00+02:00",
    )
    _open(world, completing)
    completing_claim = _claim(world, completing)
    completing_commitment = ShiftCommitment.objects.get(
        pk=completing_claim.commitment_id
    )
    _confirm(world, completing_commitment)
    completing.refresh_from_db()
    lock_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=completing.id,
        expected_version=completing.command_version,
        allow_understaffed=False,
        reason="Lock the final reviewed coverage.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    completing.refresh_from_db()
    with time_machine.travel("2030-08-01T16:30:00+02:00"):
        completed = organizer.post(
            _api_url(
                world,
                "api-workforce-shift-complete",
                demand_id=completing.id,
            ),
            {
                "expected_version": completing.command_version,
                "reason": "The work ended and its handover was recorded.",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
    assert completed.status_code == 200
    assert completed.json()["status"] == ShiftDemand.Status.COMPLETED


def test_browser_forms_support_the_complete_shift_management_journey() -> None:
    world = _shift_world()
    organizer = Client()
    organizer.force_login(world.planner)
    planning_url = _organizer_url(world, "organization-workforce-shifts")

    planning = organizer.get(planning_url)
    assert planning.status_code == 200
    assert "Create a Shift draft" in strip_tags(planning.content.decode())

    created = organizer.post(
        _organizer_url(world, "create-organization-workforce-shift"),
        _web_demand_payload(
            world,
            title="Browser operations desk",
            expected_version=0,
        ),
        follow=True,
    )
    assert created.status_code == 200
    assert "Draft Shift created" in strip_tags(created.content.decode())
    demand = ShiftDemand.objects.get(title="Browser operations desk")

    updated = organizer.post(
        _organizer_url(
            world,
            "update-organization-workforce-shift",
            demand_id=demand.id,
        ),
        _web_demand_payload(
            world,
            title="Updated browser operations desk",
            expected_version=demand.command_version,
        ),
        follow=True,
    )
    assert updated.status_code == 200
    assert "Draft Shift updated" in strip_tags(updated.content.decode())
    demand.refresh_from_db()

    opened = organizer.post(
        _organizer_url(
            world,
            "open-organization-workforce-shift",
            demand_id=demand.id,
        ),
        _web_reason_payload(
            expected_version=demand.command_version,
            reason="Publish reviewed work for suitable people.",
        ),
        follow=True,
    )
    assert opened.status_code == 200
    assert "Shift opened for claims" in strip_tags(opened.content.decode())
    demand.refresh_from_db()

    person = Client()
    person.force_login(world.person)
    claimed = person.post(
        _personal_url(
            world,
            "claim-my-workforce-shift",
            demand_id=demand.id,
        ),
        {
            "expected_version": str(demand.command_version),
            "retry_key": str(uuid4()),
        },
        follow=True,
    )
    assert claimed.status_code == 200
    assert "Shift claimed" in strip_tags(claimed.content.decode())
    commitment = ShiftCommitment.objects.get(demand=demand)

    confirmed = organizer.post(
        _organizer_url(
            world,
            "confirm-organization-workforce-shift-commitment",
            demand_id=demand.id,
            commitment_id=commitment.id,
        ),
        _web_reason_payload(
            expected_version=commitment.command_version,
            reason="Confirm current qualification and shared Availability.",
        ),
        follow=True,
    )
    assert confirmed.status_code == 200
    assert "Shift claim confirmed" in strip_tags(confirmed.content.decode())
    commitment.refresh_from_db()
    demand.refresh_from_db()

    locked = organizer.post(
        _organizer_url(
            world,
            "lock-organization-workforce-shift",
            demand_id=demand.id,
        ),
        _web_reason_payload(
            expected_version=demand.command_version,
            reason="Lock complete and current accountable coverage.",
        ),
        follow=True,
    )
    assert locked.status_code == 200
    assert "Shift coverage locked" in strip_tags(locked.content.decode())
    demand.refresh_from_db()

    reopened = organizer.post(
        _organizer_url(
            world,
            "reopen-organization-workforce-shift",
            demand_id=demand.id,
        ),
        _web_reason_payload(
            expected_version=demand.command_version,
            reason="Reopen coverage after the operating plan changed.",
        ),
        follow=True,
    )
    assert reopened.status_code == 200
    assert "Shift reopened" in strip_tags(reopened.content.decode())
    commitment.refresh_from_db()
    demand.refresh_from_db()

    removed = organizer.post(
        _organizer_url(
            world,
            "remove-organization-workforce-shift-commitment",
            demand_id=demand.id,
            commitment_id=commitment.id,
        ),
        _web_reason_payload(
            expected_version=commitment.command_version,
            reason="Remove coverage because the operating plan changed.",
        ),
        follow=True,
    )
    assert removed.status_code == 200
    assert "Shift claim removed" in strip_tags(removed.content.decode())
    demand.refresh_from_db()

    cancelled = organizer.post(
        _organizer_url(
            world,
            "cancel-organization-workforce-shift",
            demand_id=demand.id,
        ),
        _web_reason_payload(
            expected_version=demand.command_version,
            reason="The operating desk is no longer required.",
        ),
        follow=True,
    )
    assert cancelled.status_code == 200
    assert "Shift cancelled" in strip_tags(cancelled.content.decode())
    demand.refresh_from_db()
    assert demand.status == ShiftDemand.Status.CANCELLED


def test_browser_person_can_withdraw_claim_without_explanation() -> None:
    world = _shift_world()
    person = Client()
    person.force_login(world.person)
    withdrawable = _create_demand(
        world,
        title="Browser withdrawal desk",
        starts_at="2030-08-01T14:00:00+02:00",
        ends_at="2030-08-01T16:00:00+02:00",
    )
    _open(world, withdrawable)
    withdrawal_claim = _claim(world, withdrawable)
    withdrawing = ShiftCommitment.objects.get(pk=withdrawal_claim.commitment_id)
    withdrawn = person.post(
        _personal_url(
            world,
            "withdraw-my-workforce-shift",
            commitment_id=withdrawing.id,
        ),
        {
            "expected_version": str(withdrawing.command_version),
            "retry_key": str(uuid4()),
            "confirm": "on",
        },
        follow=True,
    )
    assert withdrawn.status_code == 200
    assert "commitment was withdrawn" in strip_tags(withdrawn.content.decode())


def test_browser_shift_failures_remain_recoverable_and_action_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _shift_world()
    organizer = Client()
    organizer.force_login(world.planner)
    create_url = _organizer_url(world, "create-organization-workforce-shift")

    invalid_create = organizer.post(create_url, {})
    assert invalid_create.status_code == 400
    assert "Nothing was created" in strip_tags(invalid_create.content.decode())

    original_create = shift_views.create_shift_demand

    monkeypatch.setattr(
        shift_views,
        "create_shift_demand",
        _raise_shift_version_conflict,
    )
    conflicted_create = organizer.post(
        create_url,
        _web_demand_payload(
            world,
            title="Concurrent browser Shift",
            expected_version=0,
        ),
    )
    assert conflicted_create.status_code == 409
    assert "The Shift was not created" in strip_tags(conflicted_create.content.decode())
    monkeypatch.setattr(shift_views, "create_shift_demand", original_create)

    demand = _create_demand(world, title="Recoverable browser Shift")
    update_url = _organizer_url(
        world,
        "update-organization-workforce-shift",
        demand_id=demand.id,
    )
    invalid_update = organizer.post(update_url, {})
    assert invalid_update.status_code == 400
    assert "Nothing changed" in strip_tags(invalid_update.content.decode())

    original_update = shift_views.update_shift_demand
    monkeypatch.setattr(
        shift_views,
        "update_shift_demand",
        _raise_shift_version_conflict,
    )
    conflicted_update = organizer.post(
        update_url,
        _web_demand_payload(
            world,
            title="Stale browser Shift",
            expected_version=demand.command_version,
        ),
    )
    assert conflicted_update.status_code == 409
    assert "draft was not changed" in strip_tags(conflicted_update.content.decode())
    monkeypatch.setattr(shift_views, "update_shift_demand", original_update)

    open_url = _organizer_url(
        world,
        "open-organization-workforce-shift",
        demand_id=demand.id,
    )
    invalid_open = organizer.post(open_url, {}, follow=True)
    assert invalid_open.status_code == 200
    assert "action was incomplete" in strip_tags(invalid_open.content.decode())

    original_open = shift_views.open_shift_demand
    monkeypatch.setattr(
        shift_views,
        "open_shift_demand",
        _raise_shift_version_conflict,
    )
    conflicted_open = organizer.post(
        open_url,
        _web_reason_payload(
            expected_version=demand.command_version,
            reason="Attempt a stale transition without losing recovery guidance.",
        ),
        follow=True,
    )
    assert conflicted_open.status_code == 200
    assert "changed. Reload it" in strip_tags(conflicted_open.content.decode())
    monkeypatch.setattr(shift_views, "open_shift_demand", original_open)

    _open(world, demand)
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    confirm_url = _organizer_url(
        world,
        "confirm-organization-workforce-shift-commitment",
        demand_id=demand.id,
        commitment_id=commitment.id,
    )
    invalid_confirm = organizer.post(confirm_url, {}, follow=True)
    assert invalid_confirm.status_code == 200
    assert "coverage action was incomplete" in strip_tags(
        invalid_confirm.content.decode()
    )

    original_confirm = shift_views.confirm_shift_commitment
    monkeypatch.setattr(
        shift_views,
        "confirm_shift_commitment",
        _raise_shift_version_conflict,
    )
    conflicted_confirm = organizer.post(
        confirm_url,
        _web_reason_payload(
            expected_version=commitment.command_version,
            reason="Attempt a stale confirmation through the browser adapter.",
        ),
        follow=True,
    )
    assert conflicted_confirm.status_code == 200
    assert "changed. Reload it" in strip_tags(conflicted_confirm.content.decode())
    monkeypatch.setattr(
        shift_views,
        "confirm_shift_commitment",
        original_confirm,
    )


def test_browser_personal_shift_failures_remain_private_and_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _shift_world()
    demand = _create_demand(world, title="Personal recovery Shift")
    _open(world, demand)
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    person = Client()
    person.force_login(world.person)
    personal_url = _personal_url(world, "my-workforce-shifts")
    assert person.get(personal_url, {"unexpected": "value"}).status_code == 400

    second = _create_demand(
        world,
        title="Second recoverable Shift",
        starts_at="2030-08-01T14:00:00+02:00",
        ends_at="2030-08-01T16:00:00+02:00",
    )
    _open(world, second)
    claim_url = _personal_url(
        world,
        "claim-my-workforce-shift",
        demand_id=second.id,
    )
    invalid_claim = person.post(claim_url, {})
    assert invalid_claim.status_code == 400
    assert "Reload this Shift" in strip_tags(invalid_claim.content.decode())

    original_claim = shift_views.claim_shift
    monkeypatch.setattr(
        shift_views,
        "claim_shift",
        _raise_shift_version_conflict,
    )
    conflicted_claim = person.post(
        claim_url,
        {
            "expected_version": str(second.command_version),
            "retry_key": str(uuid4()),
        },
    )
    assert conflicted_claim.status_code == 409
    assert "This Shift was not claimed" in strip_tags(conflicted_claim.content.decode())
    monkeypatch.setattr(shift_views, "claim_shift", original_claim)

    withdraw_url = _personal_url(
        world,
        "withdraw-my-workforce-shift",
        commitment_id=commitment.id,
    )
    invalid_withdraw = person.post(withdraw_url, {})
    assert invalid_withdraw.status_code == 400
    assert "Confirm the withdrawal" in strip_tags(invalid_withdraw.content.decode())

    monkeypatch.setattr(
        shift_views,
        "withdraw_shift_claim",
        _raise_shift_version_conflict,
    )
    conflicted_withdraw = person.post(
        withdraw_url,
        {
            "expected_version": str(commitment.command_version),
            "retry_key": str(uuid4()),
            "confirm": "on",
        },
    )
    assert conflicted_withdraw.status_code == 409
    assert "commitment was not withdrawn" in strip_tags(
        conflicted_withdraw.content.decode()
    )


def test_locked_shift_page_offers_completion_only_after_work_ends() -> None:
    world = _shift_world()
    demand = _create_demand(world)
    _open(world, demand)
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)
    _confirm(world, commitment)
    lock_shift_demand(
        actor=world.planner,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        allow_understaffed=False,
        reason="All requested coverage is confirmed and current.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    client = Client()
    client.force_login(world.planner)
    url = _organizer_url(
        world,
        "organization-workforce-shift",
        demand_id=demand.id,
    )

    before_end = client.get(url)

    assert before_end.status_code == 200
    before_end_text = strip_tags(before_end.content.decode())
    assert "Completion becomes available after" in before_end_text
    assert "Complete Shift" not in before_end_text

    with time_machine.travel("2030-08-01T14:00:00+02:00"):
        ended_client = Client()
        ended_client.force_login(world.planner)
        after_end = ended_client.get(url)

    assert after_end.status_code == 200
    assert "Complete Shift" in strip_tags(after_end.content.decode())


def test_ended_shifts_neither_open_nor_appear_claimable() -> None:
    world = _shift_world()
    expired_draft = _create_demand(world, title="Expired private Shift")

    with (
        time_machine.travel("2030-08-02T09:00:00+02:00"),
        pytest.raises(ShiftStateConflictError, match="cannot be opened"),
    ):
        _open(world, expired_draft)

    expired_open = _create_demand(world, title="Expired published Shift")
    _open(world, expired_open)
    with time_machine.travel("2030-08-02T09:00:00+02:00"):
        assert (
            load_my_shift_overview(
                account=world.person,
                edition=world.edition,
            ).suitable
            == ()
        )
        with pytest.raises(ShiftStateConflictError, match="no longer be claimed"):
            _claim(world, expired_open)


def test_complete_shift_projections_keep_query_counts_bounded(
    django_assert_max_num_queries: Callable[[int], AbstractContextManager[None]],
) -> None:
    world = _shift_world(position_headcount=4)
    second_person, _assignment = _activate_person(
        edition=world.edition,
        planner=world.planner,
        reviewer=world.reviewer,
        position=world.position,
        person=AccountFactory(display_name="Alex Shift Example"),
    )
    demand = _create_demand(world, required_headcount=3)
    _open(world, demand)
    _claim(world, demand)
    _claim(world, demand, person=second_person)

    with django_assert_max_num_queries(3):
        organizer = load_organizer_shift_overview(edition=world.edition)
    with django_assert_max_num_queries(6):
        personal = load_my_shift_overview(account=world.person, edition=world.edition)

    assert organizer.demands[0].active_count == 2
    assert len(personal.commitments) == 1


def test_unfinished_shift_protects_position_in_command_and_database() -> None:
    world = _shift_world()
    _create_demand(world)
    structure_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )

    with pytest.raises(StructureDependencyConflictError, match="Shifts still depend"):
        close_position(
            actor=world.planner,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=world.position.id,
            expected_version=structure_version,
            confirmation_name=world.position.title,
            reason="Attempt to close work that still has unfinished planning.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    with (
        pytest.raises(IntegrityError, match="unfinished Workforce Shifts"),
        transaction.atomic(),
    ):
        Position.objects.filter(pk=world.position.pk).update(
            status=Position.Status.CLOSED
        )


def _truncate_shift_commitments_without_test_reset() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(
            "TRUNCATE public.workforce_shiftcommitmentcommandreceipt, "
            "public.workforce_shiftcommitment, "
            "public.workforce_shiftdemandcommandreceipt, "
            "public.workforce_shiftdemand"
        )


def test_database_guards_reject_tampering_subject_conversion_and_truncate() -> None:
    world = _shift_world()
    demand = _create_demand(world)
    _open(world, demand)
    claimed = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claimed.commitment_id)

    with (
        pytest.raises(IntegrityError, match="published workforce Shift planning"),
        transaction.atomic(),
    ):
        ShiftDemand.objects.filter(pk=demand.pk).update(
            title="Silent rewrite",
            command_version=demand.command_version + 1,
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
    receipt = commitment.command_receipts.get(resulting_version=1)
    with pytest.raises(ValidationError, match="immutable"):
        receipt.delete()
    with (
        pytest.raises(IntegrityError, match="receipts are immutable"),
        transaction.atomic(),
    ):
        ShiftCommitmentCommandReceipt.objects.filter(pk=receipt.pk).update(
            source_channel="rewritten"
        )
    with pytest.raises(DatabaseError, match="cannot be truncated"):
        _truncate_shift_commitments_without_test_reset()
