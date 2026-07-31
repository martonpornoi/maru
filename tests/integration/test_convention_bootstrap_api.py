from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.participation.models import Participation
from maru.workforce.models import Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

BOOTSTRAP_URL = "/api/v1/management/convention-bootstrap"


def _payload(edition: EventEdition, chair_email: str) -> dict[str, str]:
    return {
        "organization_id": str(edition.organization_id),
        "edition_id": str(edition.id),
        "chair_email": chair_email,
        "reason": "Establish accountable convention leadership in the console.",
        "confirm_organization": edition.organization.slug,
        "controller_password": "synthetic-password",
    }


def test_bootstrap_workspace_is_superuser_only_and_audits_the_sensitive_read() -> None:
    controller = AccountFactory(
        email="bootstrap-controller@example.invalid",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(
        email="bootstrap-chair@example.invalid",
        display_name="Bootstrap Chair",
    )
    inactive = AccountFactory(
        email="inactive-chair@example.invalid",
        is_active=False,
    )
    edition = EventEditionFactory(
        slug="guided-bootstrap-2030",
        series__organization__slug="guided-bootstrap",
    )
    established_edition = EventEditionFactory()
    RoleBundleFactory(organization=established_edition.organization)
    client = APIClient()

    ordinary_staff = AccountFactory(is_staff=True, is_superuser=False)
    client.force_authenticate(ordinary_staff)
    denied = client.get(BOOTSTRAP_URL, HTTP_X_REQUEST_ID=str(uuid4()))
    assert denied.status_code == 403
    assert denied.json()["code"] == "bootstrap_superuser_required"

    request_id = uuid4()
    client.force_authenticate(controller)
    response = client.get(BOOTSTRAP_URL, HTTP_X_REQUEST_ID=str(request_id))

    assert response.status_code == 200
    payload = response.json()
    assert payload["controller_email"] == controller.email
    statuses = {
        organization["slug"]: organization["status"]
        for organization in payload["organizations"]
    }
    assert statuses[edition.organization.slug] == "eligible"
    assert statuses[established_edition.organization.slug] == "established"
    assert payload["editions"][0]["id"]
    chair_emails = {candidate["email"] for candidate in payload["chairs"]}
    assert chair.email in chair_emails
    assert controller.email not in chair_emails
    assert inactive.email not in chair_emails
    audit = AuditEvent.objects.get(
        correlation_id=request_id,
        operation="workforce.convention_bootstrap.view",
    )
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.elevated is True
    assert audit.safe_metadata["target_count"] >= 1


def test_browser_bootstrap_requires_password_confirmation_and_is_one_shot() -> None:
    controller = AccountFactory(
        email="guided-controller@example.invalid",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(
        email="guided-chair@example.invalid",
        display_name="Guided Convention Chair",
    )
    edition = EventEditionFactory(
        slug="guided-convention-2030",
        series__organization__slug="guided-convention",
    )
    client = APIClient()
    client.force_authenticate(controller)
    payload = _payload(edition, chair.email)

    wrong_password_id = uuid4()
    wrong_password = client.post(
        BOOTSTRAP_URL,
        {**payload, "controller_password": "incorrect-password"},
        format="json",
        HTTP_X_REQUEST_ID=str(wrong_password_id),
    )
    assert wrong_password.status_code == 400
    assert wrong_password.json()["code"] == "bootstrap_password_invalid"
    assert not RoleAssignment.objects.filter(organization=edition.organization).exists()
    assert (
        AuditEvent.objects.get(
            correlation_id=wrong_password_id,
            operation="workforce.convention_bootstrap",
        ).outcome
        == AuditEvent.Outcome.DENY
    )

    mismatch = client.post(
        BOOTSTRAP_URL,
        {**payload, "confirm_organization": "wrong-organizer"},
        format="json",
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "bootstrap_confirmation_mismatch"

    created_id = uuid4()
    created = client.post(
        BOOTSTRAP_URL,
        payload,
        format="json",
        HTTP_X_REQUEST_ID=str(created_id),
    )

    assert created.status_code == 201
    result = created.json()
    assert result["organization"]["slug"] == edition.organization.slug
    assert result["organization"]["status"] == "established"
    assert result["edition"]["slug"] == edition.slug
    assert result["chair"] == {
        "email": chair.email,
        "display_name": chair.display_name,
    }
    assert result["created"] == {
        "role_bundles": 11,
        "position_templates": 10,
        "departments": 1,
        "positions": 1,
        "role_assignments": 2,
        "position_assignments": 1,
    }
    assert RoleBundle.objects.filter(organization=edition.organization).count() == 11
    assert (
        PositionTemplate.objects.filter(organization=edition.organization).count() == 10
    )
    assert Position.objects.filter(
        edition=edition,
        code="convention-chair",
    ).exists()
    assert not Participation.objects.filter(
        edition=edition,
        account=controller,
    ).exists()
    assert Participation.objects.filter(edition=edition, account=chair).exists()
    assert not RoleAssignment.objects.filter(
        organization=edition.organization,
        principal=controller,
    ).exists()
    assert (
        AuditEvent.objects.get(
            correlation_id=created_id,
            operation="workforce.organization.bootstrap",
        ).source_channel
        == "management-console"
    )

    repeated = client.post(BOOTSTRAP_URL, payload, format="json")
    assert repeated.status_code == 400
    assert repeated.json()["code"] == "bootstrap_unavailable"


def test_bootstrap_immediately_enables_the_console_lifecycle_transition() -> None:
    controller = AccountFactory(
        email="lifecycle-controller@example.invalid",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(email="lifecycle-chair@example.invalid")
    edition = EventEditionFactory(
        slug="lifecycle-convention-2030",
        series__organization__slug="lifecycle-convention",
    )
    client = APIClient()
    client.force_authenticate(controller)

    assert (
        client.post(
            BOOTSTRAP_URL,
            _payload(edition, chair.email),
            format="json",
        ).status_code
        == 201
    )

    context = client.get("/api/v1/me/context")
    assert context.status_code == 200
    edition_context = context.json()["editions"][0]
    assert edition_context["edition_id"] == str(edition.id)
    assert edition_context["lifecycle"] == "draft"
    assert edition_context["can_transition"] is True
    assert context.json()["can_bootstrap_convention"] is True

    transitioned = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/"
            f"editions/{edition.id}/transition"
        ),
        {
            "to_state": "preparing",
            "reason": "Begin accountable convention planning.",
        },
        format="json",
    )
    assert transitioned.status_code == 200
    assert transitioned.json()["lifecycle"] == "preparing"
