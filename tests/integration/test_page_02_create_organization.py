from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.organizations.services import create_draft_organization
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import Department, PositionAssignment
from tests.factories import AccountFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_platform_administrator_can_open_the_minimal_creation_page() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/new/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="create-organization"' in content
    assert "Create organization" in content
    assert "Organization name" in content
    assert 'name="name"' in content
    assert "keep the organization as a draft" in content
    assert "Legal name" not in content
    assert "Contact email" not in content
    assert "Primary operating country" not in content
    assert "Executive Board" not in content
    assert "Back to organizations" in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_route_redirects_anonymous_people_to_sign_in() -> None:
    response = APIClient().get("/admin/organizations/new/")

    assert response.status_code == 302
    assert response["Location"] == ("/accounts/login/?next=/admin/organizations/new/")


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize("is_staff", [False, True])
def test_non_platform_account_cannot_load_or_submit_creation(is_staff: bool) -> None:
    account = AccountFactory(is_staff=is_staff)
    client = APIClient()
    client.force_login(account)

    get_response = client.get("/admin/organizations/new/")
    post_response = client.post(
        "/admin/organizations/new/",
        {"name": "Hidden Organizer"},
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403
    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_name_only_submission_creates_an_audited_draft_without_relationships() -> None:
    administrator = AccountFactory(
        display_name="Maru Administrator",
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "Marucon Organizers"},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [("/admin/", 302)]
    organization = Organization.objects.get()
    assert organization.name == "Marucon Organizers"
    assert organization.slug == "marucon-organizers"
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert organization.default_language_codes == ["en"]
    assert organization.default_time_zone == "UTC"
    assert organization.legal_name == ""
    assert organization.description == ""
    assert organization.website_url == ""
    assert organization.contact_email == ""
    assert organization.country_code == ""

    audit = AuditEvent.objects.get()
    assert audit.principal_id == administrator.id
    assert audit.organization_id == organization.id
    assert audit.target_id == organization.id
    assert audit.operation == "organizations.organization.create"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.reason_code == "platform_administration"
    assert audit.changed_fields == ["name", "slug", "lifecycle"]

    assert not OrganizationMembership.objects.exists()
    assert not CapabilityGrant.objects.exists()
    assert not RoleBundle.objects.exists()
    assert not RoleAssignment.objects.exists()
    assert not ConventionSeries.objects.exists()
    assert not EventEdition.objects.exists()
    assert not Department.objects.exists()
    assert not Participation.objects.exists()
    assert not Registration.objects.exists()
    assert not PositionAssignment.objects.exists()

    content = response.content.decode()
    assert "Marucon Organizers was created as a draft." in content
    assert "Marucon Organizers" in content
    assert "marucon-organizers" in content
    assert "Draft" in content
    assert "Maru Administrator" in content

    next_response = client.get("/admin/")
    assert "was created as a draft" not in next_response.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_normalizes_name_and_disambiguates_generated_slug() -> None:
    OrganizationFactory(slug="marucon-organizers", name="Earlier Organizer")
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "  Marucon   Organizers  "},
    )

    assert response.status_code == 302
    created = Organization.objects.get(name="Marucon Organizers")
    assert created.slug == "marucon-organizers-2"
    assert created.lifecycle == Organization.Lifecycle.DRAFT


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_generated_slug_has_a_bounded_fallback_for_non_ascii_names() -> None:
    OrganizationFactory(slug="organization", name="Earlier Organizer")
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "猫会"},
    )

    assert response.status_code == 302
    created = Organization.objects.get(name="猫会")
    assert created.slug == "organization-2"
    assert len(created.slug) <= 80


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_generated_slug_never_exceeds_the_model_limit() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "A" * 160},
    )

    assert response.status_code == 302
    assert len(Organization.objects.get().slug) == 80


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize("name", ["   ", "x" * 161])
def test_invalid_name_keeps_validation_local_and_creates_nothing(name: str) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post("/admin/organizations/new/", {"name": name})

    assert response.status_code == 200
    assert 'data-page="create-organization"' in response.content.decode()
    assert "errorlist" in response.content.decode()
    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_audit_database_failure_rolls_back_creation_and_returns_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def unavailable_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private database detail")

    monkeypatch.setattr(
        "maru.organizations.services.append_audit",
        unavailable_audit,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "Rolled Back Organizer"},
    )

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be created" in content
    assert "synthetic private database detail" not in content
    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


def test_creation_service_repeats_platform_authorization() -> None:
    ordinary_account = AccountFactory(is_staff=True)

    with pytest.raises(PermissionDenied):
        create_draft_organization(
            actor=ordinary_account,
            name="Bypass Attempt",
            correlation_id=uuid4(),
        )

    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()
