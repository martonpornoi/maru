from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from maru.authorization.policy import AuthorizedScopeProjection
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
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
    assert payload["can_access_advanced_records"] is False
    assert payload["memberships"][0]["organization_id"] == str(
        world.primary_organization.id
    )
    assert payload["editions"][0]["edition_id"] == str(world.current_edition.id)
    assert payload["editions"][0]["capacities"][0]["code"] == "volunteer"
    assert str(world.other_account.id) not in serialized
    assert str(world.other_organization.id) not in serialized
    assert str(world.other_edition.id) not in serialized
    assert world.other_organization.name not in serialized


def test_self_context_projects_assignment_semantics_independently_of_modules() -> None:
    """Project the exact Workforce adapter result, not module membership."""
    world = create_reference_convention()
    client = APIClient()
    client.force_authenticate(world.primary_account)

    with patch(
        "maru.participation.api.assignment_uses_participation_evidence",
        return_value=False,
    ) as assignment_semantics:
        response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    edition = response.json()["editions"][0]
    assert "participation" in edition["adopted_modules"]
    assert edition["assignment_uses_participation_evidence"] is False
    assignment_semantics.assert_called_once_with("full_convention", 1)


def test_self_context_projects_organization_authority_through_exact_profiles() -> None:
    """Stop purpose-root authority from fanning out across profile editions."""
    account = AccountFactory()
    full_edition = EventEditionFactory(name="Full purpose boundary")
    workforce_edition = EventEditionFactory(
        series=full_edition.series,
        name="Workforce purpose boundary",
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    client = APIClient()
    client.force_authenticate(account)
    purpose_scope = AuthorizedScopeProjection(
        organization_id=full_edition.organization_id,
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
        capability_codes=frozenset({"events.view_basic"}),
        direct_capability_codes=frozenset(),
        ordinary_role_capability_sets=(),
        purpose_bound_role_capabilities=(
            ("maru-operators", frozenset({"events.view_basic"})),
        ),
    )

    with patch(
        "maru.participation.api.project_active_authority_scopes",
        return_value=(purpose_scope,),
    ):
        purpose_response = client.get("/api/v1/me/context")

    assert purpose_response.status_code == 200
    assert {item["edition_id"] for item in purpose_response.json()["editions"]} == {
        str(workforce_edition.id)
    }

    unbound_scope = AuthorizedScopeProjection(
        organization_id=full_edition.organization_id,
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
        capability_codes=frozenset({"events.view_basic"}),
        direct_capability_codes=frozenset({"events.view_basic"}),
        ordinary_role_capability_sets=(),
        purpose_bound_role_capabilities=(),
    )
    with patch(
        "maru.participation.api.project_active_authority_scopes",
        return_value=(unbound_scope,),
    ):
        unbound_response = client.get("/api/v1/me/context")

    assert unbound_response.status_code == 200
    assert {item["edition_id"] for item in unbound_response.json()["editions"]} == {
        str(full_edition.id),
        str(workforce_edition.id),
    }


def test_self_context_ignores_attendee_rows_without_the_exact_adapter() -> None:
    """Do not infer attendee discovery from a durable relation alone."""
    account = AccountFactory()
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    ParticipationFactory(
        account=account,
        organization=edition.organization,
        edition=edition,
    )
    client = APIClient()
    client.force_authenticate(account)

    response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    assert response.json()["editions"] == []


def test_platform_context_omits_an_unsupported_exact_profile_candidate() -> None:
    """Do not project names or raise when a defensive platform source drifts."""
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(administrator)
    unsupported = SimpleNamespace(
        adoption_profile_code="full_convention",
        adoption_profile_version=2,
    )

    with patch(
        "maru.participation.api.platform_editions",
        return_value=(unsupported,),
    ):
        response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    assert response.json()["editions"] == []


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
