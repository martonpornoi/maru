from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.events.models import EventEdition
from maru.events.services import transition_edition
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    create_reference_convention,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _archive_current_edition(world: object) -> None:
    actor = AccountFactory()
    edition = world.current_edition
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    for state in (
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
        EventEdition.Lifecycle.CLOSING,
        EventEdition.Lifecycle.ARCHIVED,
    ):
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=actor,
            reason="Synthetic archive transition.",
            correlation_id=uuid4(),
        )


def test_self_context_requires_authentication() -> None:
    response = APIClient().get("/api/v1/me/context")

    assert response.status_code in {401, 403}


def test_self_context_cannot_leak_other_tenant() -> None:
    world = create_reference_convention()
    client = APIClient()
    client.force_authenticate(world.primary_account)

    response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    payload = response.json()
    serialized = str(payload)
    assert payload["account_id"] == str(world.primary_account.id)
    assert payload["memberships"][0]["organization_id"] == str(
        world.primary_organization.id
    )
    assert payload["editions"][0]["edition_id"] == str(world.current_edition.id)
    assert payload["editions"][0]["capacities"][0]["code"] == "volunteer"
    assert str(world.other_account.id) not in serialized
    assert str(world.other_organization.id) not in serialized
    assert str(world.other_edition.id) not in serialized
    assert world.other_organization.name not in serialized


def test_history_returns_only_own_archived_participation() -> None:
    world = create_reference_convention()
    _archive_current_edition(world)
    client = APIClient()
    client.force_authenticate(world.primary_account)

    response = client.get("/api/v1/me/participation-history")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["edition_id"] == str(world.current_edition.id)
    assert payload[0]["edition_name_snapshot"] == "Pawprint Convention 2030"
    assert payload[0]["capacities"][0]["label_snapshot"] == "Volunteer"
    assert str(world.other_edition.id) not in str(payload)
