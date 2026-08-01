import pytest
from django.core.management import get_commands
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient

from maru.authorization.models import RoleAssignment, RoleBundle
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

BOOTSTRAP_URL = "/api/v1/management/convention-bootstrap"


def test_public_convention_bootstrap_ceremony_is_unmounted() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    client = APIClient()
    client.force_authenticate(administrator)
    payload = {
        "organization_id": str(edition.organization_id),
        "edition_id": str(edition.id),
        "chair_email": AccountFactory().email,
        "reason": "This obsolete public ceremony must stay unavailable.",
        "confirm_organization": edition.organization.slug,
        "controller_password": "synthetic-password",
    }

    assert client.get(BOOTSTRAP_URL).status_code == 404
    assert client.post(BOOTSTRAP_URL, payload, format="json").status_code == 404
    assert not RoleBundle.objects.filter(organization=edition.organization).exists()
    assert not RoleAssignment.objects.filter(organization=edition.organization).exists()
    with pytest.raises(NoReverseMatch):
        reverse("api-convention-bootstrap")


def test_platform_context_does_not_advertise_recovery_bootstrap() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    EventEditionFactory()
    client = APIClient()
    client.force_authenticate(administrator)

    response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    assert "can_bootstrap_convention" not in response.json()


def test_operator_recovery_command_remains_available() -> None:
    assert get_commands()["bootstrap_convention"] == "maru.workforce"
