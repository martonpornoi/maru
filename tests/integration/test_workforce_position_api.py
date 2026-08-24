"""HTTP contract coverage for governed Position management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from maru.workforce.models import (
    Department,
    Position,
    PositionTemplate,
    VolunteerOpportunity,
)
from tests.factories import AccountFactory, EventEditionFactory
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _ApiWorld:
    actor: Account
    edition: EventEdition
    department: Department
    template: PositionTemplate


def _world() -> _ApiWorld:
    actor = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        actor=actor,
        name="Volunteer Services",
        expected_code="volunteer-services",
    )
    _controller, _approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="volunteer-services-lead",
        name="Volunteer services lead",
        capability_codes=("workforce.view_structure",),
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="volunteer-services-lead",
        name="Volunteer services lead",
        description="Coordinate the volunteer experience.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    return _ApiWorld(actor, edition, department, template)


def _client(account: Account) -> APIClient:
    client = APIClient()
    client.force_authenticate(account)
    return client


def _scope_url(world: _ApiWorld, suffix: str) -> str:
    return (
        f"/api/v1/organizations/{world.edition.organization_id}/"
        f"editions/{world.edition.id}/workforce/{suffix}"
    )


def _position_payload(world: _ApiWorld, *, expected_version: int) -> dict[str, object]:
    return {
        "template_id": str(world.template.id),
        "department_id": str(world.department.id),
        "reports_to_id": None,
        "title": "Volunteer Services Lead",
        "description": "Coordinate a welcoming volunteer experience.",
        "headcount": 2,
        "expected_version": expected_version,
        "reason": "Establish the accountable volunteer-services role.",
    }


def test_position_api_runs_create_edit_publication_and_closure_journey() -> None:
    world = _world()
    client = _client(world.actor)
    create_url = _scope_url(world, "positions")
    retry_key = uuid4()

    created = client.post(
        create_url,
        _position_payload(world, expected_version=1),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )
    replayed = client.post(
        create_url,
        _position_payload(world, expected_version=1),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key),
    )

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.json() == created.json()
    position_id = UUID(created.json()["position_id"])
    assert created.json()["aggregate_version"] == 2
    detail_url = _scope_url(world, f"positions/{position_id}")
    updated = client.put(
        detail_url,
        {
            "reports_to_id": None,
            "title": "Volunteer Experience Lead",
            "description": "Coordinate arrival, care, and volunteer handoffs.",
            "headcount": 3,
            "expected_version": 2,
            "reason": "Clarify the organizer-facing responsibility.",
        },
        format="json",
    )
    naive_opportunity = client.put(
        _scope_url(world, f"positions/{position_id}/opportunity"),
        {
            "status": "published",
            "headline": "Help volunteers begin with confidence",
            "description": "Welcome volunteers and coordinate their handoffs.",
            "applications_open_at": "2026-10-20T10:00:00",
            "applications_close_at": "2026-10-20T12:00:00",
            "visible_when_filled": True,
            "expected_version": 3,
            "reason": "Publish the reviewed volunteer opportunity.",
        },
        format="json",
    )
    opportunity = client.put(
        _scope_url(world, f"positions/{position_id}/opportunity"),
        {
            "status": "published",
            "headline": "Help volunteers begin with confidence",
            "description": "Welcome volunteers and coordinate their handoffs.",
            "applications_open_at": "2026-10-20T10:00:00+02:00",
            "applications_close_at": "2026-10-20T12:00:00+02:00",
            "visible_when_filled": True,
            "expected_version": 3,
            "reason": "Publish the reviewed volunteer opportunity.",
        },
        format="json",
    )
    closed = client.post(
        _scope_url(world, f"positions/{position_id}/close"),
        {
            "expected_version": 4,
            "confirmation_name": "Volunteer Experience Lead",
            "reason": "Retire this responsibility while retaining its history.",
        },
        format="json",
    )

    assert updated.status_code == 200
    assert updated.json()["aggregate_version"] == 3
    assert naive_opportunity.status_code == 400
    assert naive_opportunity.json()["code"] == "timezone_required"
    assert opportunity.status_code == 200
    assert opportunity.json()["aggregate_version"] == 4
    assert closed.status_code == 200
    assert closed.json()["aggregate_version"] == 5
    position = Position.objects.get(id=position_id)
    assert position.status == Position.Status.CLOSED
    persisted_opportunity = VolunteerOpportunity.objects.get(position=position)
    assert persisted_opportunity.status == VolunteerOpportunity.Status.CLOSED
    assert persisted_opportunity.applications_open_at == datetime(
        2026, 10, 20, 8, tzinfo=UTC
    )
    assert persisted_opportunity.applications_close_at == datetime(
        2026, 10, 20, 10, tzinfo=UTC
    )

    structure = client.get(_scope_url(world, "structure"))
    assert structure.status_code == 200
    assert structure.json()["can_manage_positions"] is True
    projected = structure.json()["structure"]["departments"][0]["positions"][0]
    assert projected["id"] == str(position_id)
    assert projected["title"] == "Volunteer Experience Lead"
    assert projected["status"] == "closed"


def test_position_api_authorizes_before_parsing_and_closes_input_objects() -> None:
    world = _world()
    outsider = AccountFactory(is_staff=False, is_superuser=False)
    denied = _client(outsider).post(
        _scope_url(world, "positions"),
        {"unexpected": "catalog probe"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )

    assert denied.status_code == 403
    assert denied.json()["code"] == "structure_authorization_denied"
    assert str(world.template.id) not in str(denied.json())

    invalid = _client(world.actor).post(
        _scope_url(world, "positions"),
        {
            **_position_payload(world, expected_version=1),
            "unexpected": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "unknown_input_field"
    assert not Position.objects.filter(edition=world.edition).exists()


def test_position_routes_resolve_to_purpose_named_api_contracts() -> None:
    world = _world()
    position_id = uuid4()
    routes = {
        "api-workforce-positions": _scope_url(world, "positions"),
        "api-workforce-position-detail": _scope_url(world, f"positions/{position_id}"),
        "api-workforce-position-opportunity": _scope_url(
            world, f"positions/{position_id}/opportunity"
        ),
        "api-workforce-position-close": _scope_url(
            world, f"positions/{position_id}/close"
        ),
    }
    for name, url in routes.items():
        assert (
            reverse(
                name,
                kwargs={
                    "organization_id": world.edition.organization_id,
                    "edition_id": world.edition.id,
                    **(
                        {"position_id": position_id}
                        if name != "api-workforce-positions"
                        else {}
                    ),
                },
            )
            == url
        )
