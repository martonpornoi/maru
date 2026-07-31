from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.organizations.forms import OrganizationCreationForm
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.organizations.services import (
    ORGANIZATION_CREATION_FIELDS,
    OrganizationCreationDetails,
    create_draft_organization,
)
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import Department, PositionAssignment
from tests.factories import AccountFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_platform_administrator_can_open_the_complete_creation_page() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/new/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="create-organization"' in content
    assert "Create organization" in content
    assert 'aria-label="Platform administration"' in content
    assert 'href="/admin/"' in content
    assert 'href="/admin/organizations/new/"' in content
    assert "+ Add" in content
    assert 'aria-current="page"' in content
    assert "Public identity" in content
    assert "Legal identity and imprint" in content
    assert "Public contact" in content
    assert "Operating defaults" in content
    for field_name in (
        "name",
        "description",
        "legal_name",
        "legal_address",
        "legal_representative",
        "registration_authority",
        "registration_identifier",
        "tax_identifier",
        "imprint_text",
        "website_url",
        "contact_email",
        "contact_phone",
        "country_code",
        "default_language_codes",
        "default_time_zone",
    ):
        assert f'name="{field_name}"' in content
    assert content.count("Required</span>") == 1
    assert 'name="slug"' not in content
    assert 'name="lifecycle"' not in content
    assert "Draft organization" in content
    assert "does not create an Executive Board" in content


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
    assert organization.contact_phone == ""
    assert organization.legal_address == ""
    assert organization.legal_representative == ""
    assert organization.registration_authority == ""
    assert organization.registration_identifier == ""
    assert organization.tax_identifier == ""
    assert organization.imprint_text == ""
    assert organization.country_code == ""

    audit = AuditEvent.objects.get()
    assert audit.principal_id == administrator.id
    assert audit.organization_id == organization.id
    assert audit.target_id == organization.id
    assert audit.operation == "organizations.organization.create"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.reason_code == "platform_administration"
    assert audit.changed_fields == list(ORGANIZATION_CREATION_FIELDS)

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
def test_complete_profile_submission_persists_every_optional_property() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {
            "name": "Synthetic Maru Organizers",
            "description": "A synthetic community event organizer.",
            "legal_name": "Synthetic Maru Organizers Association",
            "legal_address": ("12 Synthetic Convention Street\n1051 Budapest\nHungary"),
            "legal_representative": "Synthetic Responsible Office",
            "registration_authority": "Synthetic Association Registry",
            "registration_identifier": "SYN-2031-42",
            "tax_identifier": "TAX-EXAMPLE-42",
            "imprint_text": "Synthetic legal notice for automated testing only.",
            "website_url": "https://maru.example.invalid/",
            "contact_email": "contact@example.invalid",
            "contact_phone": "+36123456789",
            "country_code": "HU",
            "default_language_codes": ["hu", "en"],
            "default_time_zone": "Europe/Budapest",
        },
    )

    assert response.status_code == 302
    organization = Organization.objects.get()
    assert organization.name == "Synthetic Maru Organizers"
    assert organization.description == "A synthetic community event organizer."
    assert organization.legal_name == "Synthetic Maru Organizers Association"
    assert organization.legal_address == (
        "12 Synthetic Convention Street\n1051 Budapest\nHungary"
    )
    assert organization.legal_representative == "Synthetic Responsible Office"
    assert organization.registration_authority == "Synthetic Association Registry"
    assert organization.registration_identifier == "SYN-2031-42"
    assert organization.tax_identifier == "TAX-EXAMPLE-42"
    assert organization.imprint_text == (
        "Synthetic legal notice for automated testing only."
    )
    assert organization.website_url == "https://maru.example.invalid/"
    assert organization.contact_email == "contact@example.invalid"
    assert organization.contact_phone == "+36123456789"
    assert organization.country_code == "HU"
    assert organization.default_language_codes == ["hu", "en"]
    assert organization.default_time_zone == "Europe/Budapest"
    assert organization.lifecycle == Organization.Lifecycle.DRAFT

    audit = AuditEvent.objects.get()
    assert audit.changed_fields == list(ORGANIZATION_CREATION_FIELDS)
    assert audit.safe_metadata == {}
    audit_text = "|".join(
        (
            audit.capability_code,
            audit.operation,
            audit.reason_code,
            *audit.changed_fields,
            str(audit.safe_metadata),
        )
    )
    assert "Synthetic Responsible Office" not in audit_text
    assert "TAX-EXAMPLE-42" not in audit_text
    assert "Synthetic Convention Street" not in audit_text


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
def test_posted_slug_and_lifecycle_cannot_override_code_owned_values() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {
            "name": "Protected Organization",
            "slug": "operator-controlled",
            "lifecycle": Organization.Lifecycle.ACTIVE,
        },
    )

    assert response.status_code == 302
    organization = Organization.objects.get()
    assert organization.slug == "protected-organization"
    assert organization.lifecycle == Organization.Lifecycle.DRAFT


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
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("website_url", "not a URL"),
        ("contact_email", "not an email"),
        ("contact_phone", "0043 123"),
        ("country_code", "ZZ"),
        ("default_language_codes", ["zz"]),
        ("default_time_zone", "Mars/Olympus"),
        ("imprint_text", "x" * 5001),
    ],
)
def test_invalid_optional_profile_value_creates_nothing(
    field_name: str,
    value: str | list[str],
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "Invalid Profile", field_name: value},
    )

    assert response.status_code == 200
    assert field_name in response.content.decode()
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


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_service_field_validation_is_mapped_back_to_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def rejected_profile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValidationError(
            {
                "contact_phone": ["Synthetic invalid telephone."],
                "unknown_property": ["Synthetic organization error."],
            }
        )

    monkeypatch.setattr(
        "maru.core.views.create_draft_organization",
        rejected_profile,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "Rejected Profile"},
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Synthetic invalid telephone." in content
    assert "Synthetic organization error." in content
    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_service_non_field_validation_is_mapped_back_to_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def rejected_profile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValidationError("Synthetic form-wide organization error.")

    monkeypatch.setattr(
        "maru.core.views.create_draft_organization",
        rejected_profile,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/new/",
        {"name": "Rejected Profile"},
    )

    assert response.status_code == 200
    assert "Synthetic form-wide organization error." in response.content.decode()
    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


def test_creation_service_repeats_platform_authorization() -> None:
    ordinary_account = AccountFactory(is_staff=True)

    with pytest.raises(PermissionDenied):
        create_draft_organization(
            actor=ordinary_account,
            details=OrganizationCreationDetails(name="Bypass Attempt"),
            correlation_id=uuid4(),
        )

    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


def test_creation_service_repeats_complete_model_validation() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(ValidationError):
        create_draft_organization(
            actor=administrator,
            details=OrganizationCreationDetails(
                name="Invalid Direct Service Profile",
                contact_phone="private-number",
            ),
            correlation_id=uuid4(),
        )

    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("name", ["", "x" * 161])
def test_creation_service_repeats_name_validation(name: str) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(ValidationError):
        create_draft_organization(
            actor=administrator,
            details=OrganizationCreationDetails(name=name),
            correlation_id=uuid4(),
        )

    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


def test_creation_service_reports_exhausted_slug_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    monkeypatch.setattr("maru.organizations.services.MAX_SLUG_CANDIDATES", 0)

    with pytest.raises(ValidationError, match="available organization URL name"):
        create_draft_organization(
            actor=administrator,
            details=OrganizationCreationDetails(name="No Available Slug"),
            correlation_id=uuid4(),
        )

    assert not Organization.objects.exists()
    assert not AuditEvent.objects.exists()


def test_creation_details_rejects_an_invalid_form() -> None:
    form = OrganizationCreationForm({"name": ""})

    with pytest.raises(ValueError, match="Validate the organization form"):
        form.creation_details()
