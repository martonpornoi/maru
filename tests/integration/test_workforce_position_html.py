"""Owner-facing Position workspace and workflow coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from django.test import Client
from django.urls import resolve, reverse
from django.utils.html import strip_tags

from maru.authorization.models import CapabilityGrant
from maru.workforce.models import (
    Department,
    Position,
    PositionTemplate,
    VolunteerOpportunity,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _HtmlWorld:
    administrator: Account
    manager: Account
    viewer: Account
    edition: EventEdition
    department: Department
    template: PositionTemplate


def _world() -> _HtmlWorld:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Synthetic Volunteer Convention")
    department = create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Volunteer Care",
        expected_code="volunteer-care",
    )
    _controller, _approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="volunteer-care-lead",
        name="Volunteer care lead",
        capability_codes=("workforce.view_structure",),
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="volunteer-care-lead",
        name="Volunteer care lead",
        description="Coordinate humane support for convention volunteers.",
        default_headcount=2,
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=administrator,
    )
    manager = AccountFactory(is_staff=False, is_superuser=False)
    viewer = AccountFactory(is_staff=False, is_superuser=False)
    for account in (manager, viewer):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=account,
            capability_code="workforce.view_structure",
        )
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=manager,
        capability_code="workforce.manage_structure",
    )
    return _HtmlWorld(
        administrator,
        manager,
        viewer,
        edition,
        department,
        template,
    )


def _client(account: Account) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _args(world: _HtmlWorld, position_id: object | None = None) -> list[object]:
    values: list[object] = [
        world.edition.organization.slug,
        world.edition.series.slug,
        world.edition.slug,
    ]
    if position_id is not None:
        values.append(position_id)
    return values


def _url(
    name: str,
    world: _HtmlWorld,
    position_id: object | None = None,
) -> str:
    return reverse(name, args=_args(world, position_id))


def _assert_private_no_store(response: Any) -> None:
    cache_control = response.headers.get("Cache-Control", "")
    assert "private" in cache_control
    assert "no-store" in cache_control


def test_position_workspace_routes_are_purpose_named_and_method_closed() -> None:
    world = _world()
    client = _client(world.manager)
    overview = _url("organization-structure-positions", world)
    create_page = _url("organization-structure-position-create", world)
    create_action = _url("create-organization-structure-position", world)

    assert overview.endswith("/structure/positions/")
    assert create_page.endswith("/structure/positions/new/")
    assert create_action.endswith("/structure/positions/create/")
    assert resolve(overview).url_name == "organization-structure-positions"
    assert resolve(create_page).url_name == "organization-structure-position-create"
    assert client.post(overview).status_code == 405
    assert client.post(create_page).status_code == 405
    assert client.get(create_action).status_code == 405


def test_owner_can_complete_position_journey_and_read_every_change_reason() -> None:
    world = _world()
    client = _client(world.manager)
    create_page = client.get(_url("organization-structure-position-create", world))

    assert create_page.status_code == 200
    _assert_private_no_store(create_page)
    create_form = create_page.context["form"]
    created = client.post(
        _url("create-organization-structure-position", world),
        {
            "template_id": str(world.template.id),
            "department_id": str(world.department.id),
            "reports_to_id": "",
            "title": "Volunteer Care Lead",
            "description": "Coordinate arrival, care, and volunteer handoffs.",
            "headcount": "2",
            "expected_version": str(create_form["expected_version"].value()),
            "retry_key": str(create_form["retry_key"].value()),
            "reason": "Establish accountable volunteer care for this edition.",
        },
    )

    assert created.status_code == 302
    position = Position.objects.get(edition=world.edition)
    detail_url = _url("organization-structure-position", world, position.id)
    assert created.headers["Location"] == detail_url
    detail = client.get(detail_url)
    assert detail.status_code == 200
    _assert_private_no_store(detail)
    content = strip_tags(detail.content.decode())
    assert "Volunteer Care Lead" in content
    assert "Draft" in content
    assert "Establish accountable volunteer care for this edition." in content

    update_form = detail.context["update_form"]
    updated = client.post(
        _url("update-organization-structure-position", world, position.id),
        {
            "reports_to_id": "",
            "title": "Volunteer Experience Lead",
            "description": "Make every volunteer arrival clear and welcoming.",
            "headcount": "3",
            "expected_version": str(update_form["expected_version"].value()),
            "reason": "Clarify the role before inviting applications.",
        },
    )
    assert updated.status_code == 302

    detail = client.get(detail_url)
    opportunity_form = detail.context["opportunity_form"]
    published = client.post(
        _url(
            "update-organization-structure-position-opportunity",
            world,
            position.id,
        ),
        {
            "status": "published",
            "headline": "Help volunteers begin with confidence",
            "description": "Welcome volunteers and coordinate their handoffs.",
            "applications_open_at": "2026-10-20T10:00",
            "applications_close_at": "2026-10-20T12:00",
            "visible_when_filled": "on",
            "expected_version": str(opportunity_form["expected_version"].value()),
            "reason": "Publish the reviewed opportunity for volunteers.",
        },
    )
    assert published.status_code == 302
    opportunity = VolunteerOpportunity.objects.get(position=position)
    assert opportunity.applications_open_at == datetime(2026, 10, 20, 8, tzinfo=UTC)
    assert opportunity.applications_close_at == datetime(2026, 10, 20, 10, tzinfo=UTC)

    detail = client.get(detail_url)
    closure_form = detail.context["closure_form"]
    closed = client.post(
        _url("close-organization-structure-position", world, position.id),
        {
            "expected_version": str(closure_form["expected_version"].value()),
            "confirmation_name": "Volunteer Experience Lead",
            "reason": "Close this responsibility while preserving its history.",
        },
    )
    assert closed.status_code == 302

    final_detail = client.get(detail_url)
    final_content = strip_tags(final_detail.content.decode())
    assert final_detail.status_code == 200
    assert "Closed" in final_content
    for reason in (
        "Establish accountable volunteer care for this edition.",
        "Clarify the role before inviting applications.",
        "Publish the reviewed opportunity for volunteers.",
        "Close this responsibility while preserving its history.",
    ):
        assert reason in final_content
    assert final_content.index(
        "Close this responsibility while preserving its history."
    ) < final_content.index("Establish accountable volunteer care for this edition.")


def test_viewer_sees_structure_but_not_position_management_inputs() -> None:
    world = _world()
    viewer = _client(world.viewer)

    structure = viewer.get(_url("organization-structure", world))
    management = viewer.get(_url("organization-structure-positions", world))
    create_page = viewer.get(_url("organization-structure-position-create", world))

    assert structure.status_code == 200
    structure_content = strip_tags(structure.content.decode())
    assert "View only" in structure_content
    assert "Manage Positions" not in structure_content
    assert management.status_code in {403, 404}
    assert create_page.status_code in {403, 404}
    assert world.edition.name not in strip_tags(management.content.decode())


def test_position_history_is_scoped_to_the_exact_edition() -> None:
    world = _world()
    other_edition = EventEditionFactory()
    foreign_grant = CapabilityGrantFactory(
        organization=other_edition.organization,
        edition=other_edition,
        principal=world.manager,
        capability_code="workforce.view_structure",
    )
    assert isinstance(foreign_grant, CapabilityGrant)

    response = _client(world.manager).get(
        reverse(
            "organization-structure-positions",
            args=[
                other_edition.organization.slug,
                other_edition.series.slug,
                other_edition.slug,
            ],
        )
    )
    assert response.status_code in {403, 404}
    assert world.department.name not in strip_tags(response.content.decode())
