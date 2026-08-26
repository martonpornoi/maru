from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.policy import decide, resolve_organization_target
from maru.events.adoption import adoption_profile
from maru.identity.models import Account
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_superuser_manager_creates_an_explicit_platform_administrator() -> None:
    administrator = Account.objects.create_superuser(
        email="platform-admin@example.invalid",
        password="Synthetic platform password 927!",
    )

    assert administrator.account_kind == Account.Kind.PLATFORM_ADMINISTRATOR
    assert administrator.is_platform_administrator
    assert administrator.is_staff
    assert administrator.is_superuser


def test_platform_administrator_classification_requires_superuser_privileges() -> None:
    with pytest.raises(ValidationError):
        Account.objects.create_user(
            email="invalid-platform-admin@example.invalid",
            password="Synthetic invalid password 927!",
            account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
            is_staff=True,
            is_superuser=False,
        )

    person = AccountFactory()
    with transaction.atomic(), pytest.raises(IntegrityError):
        Account.objects.filter(pk=person.pk).update(is_superuser=True)


def test_platform_administrator_cannot_become_an_organization_member() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(
        ValidationError,
        match="platform administrator cannot participate",
    ):
        OrganizationMembership.objects.create(
            organization=OrganizationFactory(),
            account=administrator,
            state=OrganizationMembership.State.ACTIVE,
        )


def test_platform_administrator_cannot_receive_edition_participation() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()

    with pytest.raises(
        ValidationError,
        match="platform administrator cannot participate",
    ):
        Participation.objects.create(
            account=administrator,
            organization=edition.organization,
            edition=edition,
            status=Participation.Status.CONFIRMED,
            edition_name_snapshot="",
            series_name_snapshot="",
        )


@pytest.mark.parametrize("assignment_model", [CapabilityGrant, RoleAssignment])
def test_platform_administrator_cannot_receive_convention_authority(
    assignment_model,
) -> None:  # type: ignore[no-untyped-def]
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    actor = AccountFactory()
    organization = OrganizationFactory()
    common = {
        "organization": organization,
        "principal": administrator,
        "effective_from": timezone.now(),
        "expires_at": timezone.now() + timedelta(days=1),
        "granted_by": actor,
        "reason": "Synthetic rejected assignment.",
    }
    if assignment_model is CapabilityGrant:
        common["capability_code"] = "events.view_basic"
    else:
        common["role_bundle"] = RoleBundleFactory(organization=organization)

    with pytest.raises(
        ValidationError,
        match="platform administrator cannot participate",
    ):
        assignment_model.objects.create(**common)


def test_platform_administrator_uses_platform_policy_without_a_convention_grant() -> (
    None
):
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory()

    ordinary = decide(
        principal=administrator,
        capability_code="events.view_basic",
        resource=resolve_organization_target(organization_id=organization.id),
    )
    restricted_operation = decide(
        principal=administrator,
        capability_code="identity.manage_restrictions",
        resource=resolve_organization_target(organization_id=organization.id),
    )

    assert ordinary.allowed
    assert ordinary.reason_code == "platform_administration"
    assert restricted_operation.allowed
    assert restricted_operation.reason_code == "platform_administration"
    assert not CapabilityGrant.objects.filter(principal=administrator).exists()
    assert not RoleAssignment.objects.filter(principal=administrator).exists()


def test_platform_context_lists_editions_without_participation() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Marucon 2031")
    profile = adoption_profile(edition.adoption_profile_code)
    assert profile is not None
    client = APIClient()
    client.force_authenticate(administrator)

    response = client.get("/api/v1/me/context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["memberships"] == []
    assert payload["editions"] == [
        {
            "organization_id": str(edition.organization_id),
            "organization_slug": edition.organization.slug,
            "series_id": str(edition.series_id),
            "series_slug": edition.series.slug,
            "series_name": edition.series.name,
            "edition_id": str(edition.id),
            "edition_slug": edition.slug,
            "edition_name": "Marucon 2031",
            "lifecycle": edition.lifecycle,
            "adoption_profile_code": edition.adoption_profile_code,
            "adoption_profile_version": edition.adoption_profile_version,
            "adoption_profile_label": profile.label,
            "adopted_modules": sorted(profile.modules),
            "available_destinations": [
                "today",
                "my-registration",
                "people",
                "workforce",
                "commerce",
                "reports",
                "setup",
                "security",
            ],
            "time_zone": edition.time_zone,
            "language_codes": edition.language_codes,
            "currency_codes": edition.currency_codes,
            "starts_on": edition.starts_on.isoformat(),
            "ends_on": edition.ends_on.isoformat(),
            "participation_status": "not_participating",
            "capacities": [],
            "can_transition": True,
        }
    ]
    assert not Participation.objects.filter(account=administrator).exists()
