from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import Department
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_structure_projection_is_nested_minimized_and_tenant_scoped() -> None:
    controller = AccountFactory(
        email="first-admin@example.invalid",
        login_handle="admin",
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(
        email="chair-private@example.invalid",
        login_handle="HelpfulChair",
        display_name="Helpful Chair",
    )
    edition = EventEditionFactory(
        name="Marucon 2030",
        series__organization__name="Marucon Organizers",
    )
    bootstrap_organization_workforce(
        organization=edition.organization,
        edition=edition,
        controller=controller,
        chair=chair,
        reason="Establish the synthetic organization structure.",
        correlation_id=uuid4(),
    )
    executive = Department.objects.get(
        edition=edition,
        code="convention-leadership",
    )
    executive.code = "executive-board"
    executive.name = "Executive Board"
    executive.save(update_fields=("code", "name", "updated_at"))
    helper = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        parent=executive,
        code="helper-board",
        name="Helper Board",
        description="Supports the Executive Board and convention departments.",
        position=10,
    )

    client = APIClient()
    client.force_authenticate(chair)
    url = (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/workforce/structure"
    )
    response = client.get(url)

    assert response.status_code == 200
    payload = response.json()
    departments = {item["code"]: item for item in payload["departments"]}
    assert payload["organization_name"] == "Marucon Organizers"
    assert departments["executive-board"]["parent_id"] is None
    assert departments["helper-board"]["parent_id"] == str(executive.id)
    chair_position = departments["executive-board"]["positions"][0]
    assert chair_position["holders"][0] == {
        "assignment_id": chair_position["holders"][0]["assignment_id"],
        "display_name": "Helpful Chair",
        "login_handle": "HelpfulChair",
        "other_roles": [],
    }
    assert chair.email not in str(payload)
    assert str(helper.id) in str(payload)

    outsider = APIClient()
    outsider.force_authenticate(AccountFactory())
    assert outsider.get(url).status_code == 403
    assert (
        client.get(
            f"/api/v1/organizations/{uuid4()}/editions/{edition.id}/workforce/structure"
        ).status_code
        == 404
    )
