from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.organizations.forms import ConventionSeriesCreationForm
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.organizations.services import (
    CONVENTION_SERIES_CREATION_FIELDS,
    ConventionSeriesCreationDetails,
    create_convention_series,
)
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import Department, PositionAssignment
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_organization_record_shows_only_its_series_and_contextual_add() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    ConventionSeriesFactory(
        organization=organization,
        name="Synthetic MaruCon",
        slug="synthetic-marucon",
    )
    ConventionSeriesFactory(
        organization=organization,
        name="Synthetic Retreat",
        slug="synthetic-retreat",
        is_active=False,
    )
    other = OrganizationFactory()
    ConventionSeriesFactory(
        organization=other,
        name="Other Tenant Brand",
        slug="other-tenant-brand",
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/synthetic-maru/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Convention series" in content
    assert 'href="/admin/organizations/synthetic-maru/series/new/"' in content
    assert "+ Add series" in content
    assert "Synthetic MaruCon" in content
    assert "synthetic-marucon" in content
    assert "Synthetic Retreat" in content
    assert "Inactive" in content
    assert "Other Tenant Brand" not in content
    assert content.count('class="baseline-sidebar-row"') == 1


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_empty_and_closed_organization_record_states_are_explicit() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    draft = OrganizationFactory(
        slug="empty-draft",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    closed = OrganizationFactory(
        slug="closed-organizer",
        lifecycle=Organization.Lifecycle.CLOSED,
    )
    client = APIClient()
    client.force_login(administrator)

    draft_response = client.get(f"/admin/organizations/{draft.slug}/")
    closed_response = client.get(f"/admin/organizations/{closed.slug}/")

    assert "No convention series yet" in draft_response.content.decode()
    closed_content = closed_response.content.decode()
    assert "A Closed organization cannot add a new convention series" in closed_content
    assert f"/admin/organizations/{closed.slug}/series/new/" not in closed_content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_platform_administrator_can_open_scoped_series_creation() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/synthetic-maru/series/new/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="create-convention-series"' in content
    assert "Create convention series" in content
    assert "Synthetic Maru Organizers" in content
    assert 'href="/admin/organizations/synthetic-maru/"' in content
    for field_name in (
        "name",
        "description",
        "website_url",
        "contact_email",
        "availability",
    ):
        assert f'name="{field_name}"' in content
    assert content.count("Required</span>") == 1
    assert 'name="organization"' not in content
    assert 'name="organization_id"' not in content
    assert 'name="slug"' not in content
    assert '<option value="active" selected>Active</option>' in content
    assert "One recurring brand, no edition" in content
    assert "does not make this platform account part" in content
    assert content.count('class="baseline-sidebar-row"') == 1


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_creation_authorizes_before_parent_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lookup(slug: str) -> Organization:
        del slug
        raise AssertionError("denied requests must not query the organization")

    monkeypatch.setattr("maru.core.views._organization_for_record", unexpected_lookup)
    anonymous = APIClient().get("/admin/organizations/hidden/series/new/")
    ordinary = AccountFactory(is_staff=True)
    client = APIClient()
    client.force_login(ordinary)

    denied_get = client.get("/admin/organizations/hidden/series/new/")
    denied_post = client.post(
        "/admin/organizations/hidden/series/new/",
        {"name": "Hidden Brand"},
    )

    assert anonymous.status_code == 302
    assert anonymous["Location"] == (
        "/accounts/login/?next=/admin/organizations/hidden/series/new/"
    )
    assert denied_get.status_code == 403
    assert denied_post.status_code == 403
    assert not ConventionSeries.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_authorized_unknown_parent_is_not_found() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(administrator)

    assert client.get("/admin/organizations/missing/series/new/").status_code == 404
    assert (
        client.post(
            "/admin/organizations/missing/series/new/",
            {"name": "Missing Brand"},
        ).status_code
        == 404
    )


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_closed_parent_has_a_non_mutating_conflict_state() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Closed Synthetic Organizer",
        slug="closed-synthetic",
        lifecycle=Organization.Lifecycle.CLOSED,
    )
    client = APIClient()
    client.force_login(administrator)

    initial = client.get(f"/admin/organizations/{organization.slug}/series/new/")
    submitted = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {"name": "Too Late Convention"},
    )

    assert initial.status_code == 409
    assert submitted.status_code == 409
    content = submitted.content.decode()
    assert "Series creation is unavailable" in content
    assert "cannot add a new convention series" in content
    assert 'name="name"' not in content
    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_name_only_creation_is_active_audited_and_side_effect_free() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    other = OrganizationFactory(slug="crafted-parent")
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        "/admin/organizations/synthetic-maru/series/new/",
        {
            "name": "  Synthetic   MaruCon  ",
            "organization": str(other.id),
            "organization_id": str(other.id),
            "slug": "crafted-slug",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [("/admin/organizations/synthetic-maru/", 302)]
    series = ConventionSeries.objects.get()
    assert series.organization == organization
    assert series.name == "Synthetic MaruCon"
    assert series.slug == "synthetic-marucon"
    assert series.description == ""
    assert series.website_url == ""
    assert series.contact_email == ""
    assert series.is_active is True

    audit = AuditEvent.objects.get()
    assert audit.principal_id == administrator.id
    assert audit.organization_id == organization.id
    assert audit.target_id == series.id
    assert audit.operation == "organizations.convention_series.create"
    assert audit.capability_code == "organizations.create_series"
    assert audit.changed_fields == list(CONVENTION_SERIES_CREATION_FIELDS)
    assert audit.safe_metadata == {}
    audit_text = "|".join((*audit.changed_fields, str(audit.safe_metadata)))
    assert "Synthetic MaruCon" not in audit_text

    assert not OrganizationMembership.objects.exists()
    assert not CapabilityGrant.objects.exists()
    assert not RoleBundle.objects.exists()
    assert not RoleAssignment.objects.exists()
    assert not EventEdition.objects.exists()
    assert not Department.objects.exists()
    assert not Participation.objects.exists()
    assert not Registration.objects.exists()
    assert not PositionAssignment.objects.exists()

    content = response.content.decode()
    assert "Synthetic MaruCon was created as a convention series." in content
    assert "Synthetic MaruCon" in content
    assert "synthetic-marucon" in content
    assert "Active" in content
    assert client.get(response.request["PATH_INFO"]).status_code == 200
    assert "was created as a convention series" not in (
        client.get(f"/admin/organizations/{organization.slug}/").content.decode()
    )


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_complete_optional_series_profile_can_start_inactive() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        slug="synthetic-organizer",
        lifecycle=Organization.Lifecycle.ACTIVE,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {
            "name": "Synthetic Night Convention",
            "description": "  A continuing synthetic convention brand.  ",
            "website_url": "series.example.invalid",
            "contact_email": "hello@example.invalid",
            "availability": "inactive",
        },
    )

    assert response.status_code == 302
    series = ConventionSeries.objects.get()
    assert series.description == "A continuing synthetic convention brand."
    assert series.website_url == "https://series.example.invalid"
    assert series.contact_email == "hello@example.invalid"
    assert series.is_active is False


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("name", " "),
        ("name", "x" * 161),
        ("description", "x" * 2001),
        ("website_url", "not a URL"),
        ("contact_email", "not an email"),
        ("availability", "unknown"),
    ],
)
def test_invalid_series_field_creates_nothing(field_name: str, value: str) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {"name": "Valid Synthetic Name", field_name: value},
    )

    assert response.status_code == 200
    assert "errorlist" in response.content.decode()
    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_slug_collision_is_scoped_bounded_and_has_unicode_fallback() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        slug="first-organizer",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    other = OrganizationFactory(
        slug="other-organizer",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    ConventionSeriesFactory(
        organization=organization,
        name="Synthetic Gathering",
        slug="synthetic-gathering",
    )
    ConventionSeriesFactory(
        organization=other,
        name="Synthetic Gathering",
        slug="synthetic-gathering",
    )
    client = APIClient()
    client.force_login(administrator)

    first = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {"name": "Synthetic Gathering"},
    )
    reused = client.post(
        f"/admin/organizations/{other.slug}/series/new/",
        {"name": "A" * 160},
    )
    unicode_fallback = client.post(
        f"/admin/organizations/{other.slug}/series/new/",
        {"name": "猫会"},
    )

    assert first.status_code == 302
    assert reused.status_code == 302
    assert unicode_fallback.status_code == 302
    assert ConventionSeries.objects.get(
        organization=organization,
        name="Synthetic Gathering",
        slug="synthetic-gathering-2",
    )
    assert (
        len(ConventionSeries.objects.get(organization=other, name="A" * 160).slug) == 80
    )
    assert (
        ConventionSeries.objects.get(organization=other, name="猫会").slug == "series"
    )


def test_service_repeats_authorization_parent_lifecycle_and_model_validation() -> None:
    ordinary = AccountFactory(is_staff=True)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    draft = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    closed = OrganizationFactory(lifecycle=Organization.Lifecycle.CLOSED)

    with pytest.raises(PermissionDenied):
        create_convention_series(
            actor=ordinary,
            organization_id=draft.id,
            details=ConventionSeriesCreationDetails(name="Bypass Brand"),
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="Closed organization"):
        create_convention_series(
            actor=administrator,
            organization_id=closed.id,
            details=ConventionSeriesCreationDetails(name="Closed Brand"),
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        create_convention_series(
            actor=administrator,
            organization_id=draft.id,
            details=ConventionSeriesCreationDetails(
                name="Invalid Direct Brand",
                contact_email="not-an-email",
            ),
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        create_convention_series(
            actor=administrator,
            organization_id=draft.id,
            details=ConventionSeriesCreationDetails(
                name="Too Much Description",
                description="x" * 2001,
            ),
            correlation_id=uuid4(),
        )

    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_audit_failure_rolls_back_series_and_returns_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    def unavailable_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private audit failure")

    monkeypatch.setattr("maru.organizations.services.append_audit", unavailable_audit)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {"name": "Rolled Back Brand"},
    )

    assert response.status_code == 503
    content = response.content.decode()
    assert "The convention series could not be created" in content
    assert "synthetic private audit failure" not in content
    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_service_validation_is_mapped_to_field_and_form_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    def rejected_series(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValidationError(
            {
                "contact_email": ["Synthetic invalid contact."],
                "unknown_property": ["Synthetic series-wide error."],
            }
        )

    monkeypatch.setattr("maru.core.views.create_convention_series", rejected_series)
    client = APIClient()
    client.force_login(administrator)

    response = client.post(
        f"/admin/organizations/{organization.slug}/series/new/",
        {"name": "Rejected Brand"},
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Synthetic invalid contact." in content
    assert "Synthetic series-wide error." in content
    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


def test_service_reports_exhausted_series_slug_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    monkeypatch.setattr("maru.organizations.services.MAX_SLUG_CANDIDATES", 0)

    with pytest.raises(ValidationError, match="available series URL name"):
        create_convention_series(
            actor=administrator,
            organization_id=organization.id,
            details=ConventionSeriesCreationDetails(name="No Available Slug"),
            correlation_id=uuid4(),
        )

    assert not ConventionSeries.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_inventory_database_failure_has_a_safe_record_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    def unavailable_series(parent: Organization) -> list[ConventionSeries]:
        del parent
        raise DatabaseError("synthetic private inventory failure")

    monkeypatch.setattr("maru.core.views._series_for_organization", unavailable_series)
    client = APIClient()
    client.force_login(administrator)

    response = client.get(f"/admin/organizations/{organization.slug}/")

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be loaded" in content
    assert "synthetic private inventory failure" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_creation_has_safe_parent_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def unavailable_parent(slug: str) -> Organization:
        del slug
        raise DatabaseError("synthetic private parent failure")

    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable_parent)
    client = APIClient()
    client.force_login(administrator)

    response = client.get("/admin/organizations/unavailable/series/new/")

    assert response.status_code == 503
    content = response.content.decode()
    assert "The organization could not be loaded" in content
    assert "No convention series" in content
    assert "synthetic private parent failure" not in content


def test_series_creation_form_requires_validation_before_details() -> None:
    form = ConventionSeriesCreationForm({"name": ""})

    with pytest.raises(ValueError, match="Validate the series form"):
        form.creation_details()
