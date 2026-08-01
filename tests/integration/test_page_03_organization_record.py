from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, models
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.organizations.models import Organization
from maru.organizations.services import (
    ORGANIZATION_PROFILE_FIELDS,
    OrganizationCreationDetails,
    delete_empty_draft_organization,
    update_organization_profile,
)
from tests.factories import AccountFactory, ConventionSeriesFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _profile_post(
    organization: Organization,
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "name": organization.name,
        "description": organization.description,
        "legal_name": organization.legal_name,
        "legal_address": organization.legal_address,
        "legal_representative": organization.legal_representative,
        "registration_authority": organization.registration_authority,
        "registration_identifier": organization.registration_identifier,
        "tax_identifier": organization.tax_identifier,
        "imprint_text": organization.imprint_text,
        "website_url": organization.website_url,
        "contact_email": organization.contact_email,
        "contact_phone": organization.contact_phone,
        "country_code": organization.country_code,
        "default_language_codes": organization.default_language_codes,
        "default_time_zone": organization.default_time_zone,
    }
    values.update(overrides)
    return values


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_inventory_and_record_use_compact_navigation_and_record_link() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    client = APIClient()
    client.force_login(administrator)

    inventory = client.get("/admin/")
    record = client.get("/admin/organizations/synthetic-maru/")

    assert inventory.status_code == 200
    inventory_content = inventory.content.decode()
    assert 'class="baseline-sidebar-row"' in inventory_content
    assert 'aria-label="Add organization"' in inventory_content
    assert 'class="baseline-sidebar-context"' not in inventory_content
    assert 'href="/admin/organizations/synthetic-maru/"' in inventory_content
    assert record.status_code == 200
    content = record.content.decode()
    assert 'data-page="organization-record"' in content
    assert content.count('class="baseline-sidebar-row"') == 2
    assert content.count('aria-current="page"') == 1
    assert 'class="baseline-sidebar-context"' in content
    assert "Organization record" in content
    assert (
        'href="/admin/organizations/synthetic-maru/#convention-series-title"' in content
    )
    assert 'aria-label="Add convention series for Synthetic Maru Organizers"' in content
    assert 'href="/admin/"' in content
    assert 'href="/admin/organizations/new/"' in content
    assert "Synthetic Maru Organizers" in content
    assert "Stable URL name" in content
    assert "synthetic-maru" in content
    assert "Save changes" in content
    assert "Delete organization" in content
    assert "autofocus" not in content
    assert 'name="slug"' not in content
    assert 'name="lifecycle"' not in content
    assert str(organization.id) not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_record_authorization_happens_before_record_lookup() -> None:
    anonymous = APIClient().get("/admin/organizations/hidden-organizer/")
    assert anonymous.status_code == 302
    assert anonymous["Location"] == (
        "/accounts/login/?next=/admin/organizations/hidden-organizer/"
    )

    ordinary = AccountFactory(is_staff=True)
    client = APIClient()
    client.force_login(ordinary)
    assert client.get("/admin/organizations/hidden-organizer/").status_code == 403
    assert (
        client.post(
            "/admin/organizations/hidden-organizer/delete/",
            {"confirmation_name": "Hidden Organizer", "acknowledge": True},
        ).status_code
        == 403
    )


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_authorized_unknown_record_is_not_found() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    assert client.get("/admin/organizations/missing/").status_code == 404
    assert client.post("/admin/organizations/missing/delete/").status_code == 404


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_complete_profile_update_keeps_slug_and_lifecycle_and_audits_fields() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Synthetic Organizer",
        slug="stable-organizer",
        lifecycle=Organization.Lifecycle.DRAFT,
        default_time_zone="UTC",
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/stable-organizer/",
        _profile_post(
            organization,
            name="  Renamed   Synthetic Organizer  ",
            description="A maintained synthetic profile.",
            legal_name="Synthetic Organizer Association",
            legal_address="12 Example Street\nExample City",
            legal_representative="Synthetic Responsible Office",
            registration_authority="Synthetic Registry",
            registration_identifier="SYN-42",
            tax_identifier="TAX-42",
            imprint_text="Synthetic legal wording.",
            website_url="https://organizer.example.invalid/",
            contact_email="contact@example.invalid",
            contact_phone="+36123456789",
            country_code="HU",
            default_language_codes=["hu", "en"],
            default_time_zone="Europe/Budapest",
            slug="crafted-slug",
            lifecycle=Organization.Lifecycle.ACTIVE,
        ),
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [("/admin/organizations/stable-organizer/", 302)]
    organization.refresh_from_db()
    assert organization.name == "Renamed Synthetic Organizer"
    assert organization.slug == "stable-organizer"
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert organization.description == "A maintained synthetic profile."
    assert organization.legal_name == "Synthetic Organizer Association"
    assert organization.legal_address == "12 Example Street\nExample City"
    assert organization.legal_representative == "Synthetic Responsible Office"
    assert organization.registration_authority == "Synthetic Registry"
    assert organization.registration_identifier == "SYN-42"
    assert organization.tax_identifier == "TAX-42"
    assert organization.imprint_text == "Synthetic legal wording."
    assert organization.website_url == "https://organizer.example.invalid/"
    assert organization.contact_email == "contact@example.invalid"
    assert organization.contact_phone == "+36123456789"
    assert organization.country_code == "HU"
    assert organization.default_language_codes == ["hu", "en"]
    assert organization.default_time_zone == "Europe/Budapest"

    audit = AuditEvent.objects.get()
    assert audit.operation == "organizations.organization.update"
    assert audit.principal_id == administrator.id
    assert audit.organization_id == organization.id
    assert audit.target_id == organization.id
    assert set(audit.changed_fields) == set(ORGANIZATION_PROFILE_FIELDS)
    assert audit.safe_metadata == {}
    audit_text = "|".join((*audit.changed_fields, str(audit.safe_metadata)))
    assert "Synthetic Responsible Office" not in audit_text
    assert "TAX-42" not in audit_text
    assert "Example Street" not in audit_text
    assert "Renamed Synthetic Organizer was updated." in response.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_unchanged_profile_does_not_write_or_audit() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        lifecycle=Organization.Lifecycle.DRAFT,
        default_time_zone="UTC",
    )
    original_updated_at = organization.updated_at
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/",
        _profile_post(organization),
        follow=True,
    )

    assert response.status_code == 200
    organization.refresh_from_db()
    assert organization.updated_at == original_updated_at
    assert not AuditEvent.objects.exists()
    assert "No organization details changed." in response.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_invalid_profile_keeps_record_unchanged() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        lifecycle=Organization.Lifecycle.DRAFT,
        default_time_zone="UTC",
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/",
        _profile_post(organization, contact_phone="private-number"),
    )

    assert response.status_code == 200
    assert "Enter an international number" in response.content.decode()
    organization.refresh_from_db()
    assert organization.contact_phone == ""
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_update_audit_failure_rolls_back_and_returns_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Original Organizer",
        lifecycle=Organization.Lifecycle.DRAFT,
        default_time_zone="UTC",
    )

    def unavailable_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private audit failure")

    monkeypatch.setattr("maru.organizations.services.append_audit", unavailable_audit)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/",
        _profile_post(organization, name="Should Roll Back"),
    )

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be updated" in content
    assert "synthetic private audit failure" not in content
    organization.refresh_from_db()
    assert organization.name == "Original Organizer"
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_delete_requires_exact_name_and_acknowledgement() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Exact Draft Name",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    client = APIClient()
    client.force_login(administrator)

    mismatch = client.post(
        f"/admin/organizations/{organization.slug}/delete/",
        {"confirmation_name": "exact draft name", "acknowledge": True},
    )
    missing_acknowledgement = client.post(
        f"/admin/organizations/{organization.slug}/delete/",
        {"confirmation_name": organization.name},
    )

    assert mismatch.status_code == 200
    assert "Enter the organization name exactly" in mismatch.content.decode()
    assert missing_acknowledgement.status_code == 200
    assert "This field is required" in missing_acknowledgement.content.decode()
    assert Organization.objects.filter(id=organization.id).exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_empty_draft_can_be_deleted_with_atomic_audit() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Accidental Synthetic Draft",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    organization_id = organization.id
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/delete/",
        {"confirmation_name": organization.name, "acknowledge": True},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [("/admin/", 302)]
    assert not Organization.objects.filter(id=organization_id).exists()
    audit = AuditEvent.objects.get()
    assert audit.operation == "organizations.organization.delete"
    assert audit.reason_code == "empty_draft_removed"
    assert audit.organization_id == organization_id
    assert audit.target_id == organization_id
    assert audit.changed_fields == ["record"]
    assert audit.safe_metadata == {}
    assert "Accidental Synthetic Draft was deleted." in response.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_non_draft_and_related_draft_cannot_be_deleted() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    active = OrganizationFactory(name="Active Organizer")
    related = OrganizationFactory(
        name="Draft With Series",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    ConventionSeriesFactory(organization=related)
    client = APIClient()
    client.force_login(administrator)

    active_response = client.post(
        f"/admin/organizations/{active.slug}/delete/",
        {"confirmation_name": active.name, "acknowledge": True},
    )
    related_response = client.post(
        f"/admin/organizations/{related.slug}/delete/",
        {"confirmation_name": related.name, "acknowledge": True},
    )

    assert active_response.status_code == 200
    assert "Only an empty Draft organization can be deleted" in (
        active_response.content.decode()
    )
    assert related_response.status_code == 200
    assert "has related records and cannot be deleted" in (
        related_response.content.decode()
    )
    assert Organization.objects.filter(id__in=(active.id, related.id)).count() == 2
    assert not AuditEvent.objects.exists()


def test_every_direct_organization_relationship_protects_history() -> None:
    related_objects = Organization._meta.related_objects

    assert related_objects
    assert all(
        relationship.on_delete is models.PROTECT for relationship in related_objects
    )


def test_services_repeat_platform_authorization_and_delete_confirmation() -> None:
    ordinary = AccountFactory(is_staff=True)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Protected Draft",
        lifecycle=Organization.Lifecycle.DRAFT,
    )

    with pytest.raises(PermissionDenied):
        update_organization_profile(
            actor=ordinary,
            organization_id=organization.id,
            details=OrganizationCreationDetails(name="Bypass Update"),
            correlation_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        delete_empty_draft_organization(
            actor=ordinary,
            organization_id=organization.id,
            confirmation_name=organization.name,
            acknowledged=True,
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="exactly as shown"):
        delete_empty_draft_organization(
            actor=administrator,
            organization_id=organization.id,
            confirmation_name="Wrong name",
            acknowledged=True,
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="Acknowledge"):
        delete_empty_draft_organization(
            actor=administrator,
            organization_id=organization.id,
            confirmation_name=organization.name,
            acknowledged=False,
            correlation_id=uuid4(),
        )

    organization.refresh_from_db()
    assert organization.name == "Protected Draft"
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_delete_audit_failure_rolls_back_and_returns_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Retained Draft",
        lifecycle=Organization.Lifecycle.DRAFT,
    )

    def unavailable_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private audit failure")

    monkeypatch.setattr("maru.organizations.services.append_audit", unavailable_audit)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/delete/",
        {"confirmation_name": organization.name, "acknowledge": True},
    )

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be deleted" in content
    assert "synthetic private audit failure" not in content
    assert Organization.objects.filter(id=organization.id).exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_record_has_a_safe_database_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def unavailable_record(slug: str) -> Organization:
        del slug
        raise DatabaseError("synthetic private database detail")

    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable_record)
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/unavailable/")

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be loaded" in content
    assert "No organization data" in content
    assert "was changed" in content
    assert "synthetic private database detail" not in content
