from uuid import uuid4

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.organizations.models import ConventionSeries, Organization
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _record_url(series: ConventionSeries) -> str:
    return f"/admin/organizations/{series.organization.slug}/series/{series.slug}/"


def _profile_payload(
    series: ConventionSeries,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": series.name,
        "description": series.description,
        "website_url": series.website_url,
        "contact_email": series.contact_email,
        "availability": "active" if series.is_active else "inactive",
        "expected_profile_version": series.profile_version,
    }
    payload.update(changes)
    return payload


def _administrator_client(*, display_name: str = "Synthetic Platform Admin") -> tuple:
    administrator = AccountFactory(
        display_name=display_name,
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)
    return administrator, client


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_is_scoped_reachable_and_progressive() -> None:
    _, client = _administrator_client()
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
    )
    series = ConventionSeriesFactory(
        organization=organization,
        name="Synthetic MaruCon",
        slug="synthetic-marucon",
    )
    EventEditionFactory(
        organization=organization,
        series=series,
        name="Synthetic MaruCon 2031",
        slug="synthetic-marucon-2031",
    )
    foreign = EventEditionFactory(name="Foreign Private Edition")

    organization_page = client.get(f"/admin/organizations/{organization.slug}/")
    response = client.get(_record_url(series))

    assert organization_page.status_code == 200
    assert _record_url(series) in organization_page.content.decode()
    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="convention-series-record"' in content
    assert 'href="#main-content">Skip to main content</a>' in content
    assert 'id="main-content"' in content
    assert "Synthetic MaruCon 2031" in content
    assert foreign.name not in content
    assert "Convention editions" in content
    assert f'href="{_record_url(series)}editions/new/"' in content
    assert 'name="expected_profile_version"' in content
    assert 'value="1"' in content
    assert content.count('aria-current="page"') == 1
    assert "Series record" in content
    assert "Last changed:" in content
    assert '<summary id="maru-access-heading">' in content
    assert "does not store its own sharing list" in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_update_is_versioned_audited_and_value_minimized() -> None:
    administrator, client = _administrator_client(display_name="Synthetic Steward")
    series = ConventionSeriesFactory(
        name="Synthetic MaruCon",
        slug="stable-marucon",
    )
    original_organization_id = series.organization_id

    response = client.post(
        _record_url(series),
        _profile_payload(
            series,
            name="  Synthetic   MaruCon Europe  ",
            description="A private-looking value that belongs only on the record.",
            website_url="marucon.example.invalid",
            contact_email="team@example.invalid",
            availability="inactive",
        ),
        follow=True,
    )

    assert response.status_code == 200
    series.refresh_from_db()
    assert series.name == "Synthetic MaruCon Europe"
    assert series.slug == "stable-marucon"
    assert series.organization_id == original_organization_id
    assert series.website_url == "https://marucon.example.invalid"
    assert series.is_active is False
    assert series.profile_version == 2

    audit = AuditEvent.objects.get()
    event = DomainEvent.objects.get()
    outbox = OutboxMessage.objects.get()
    assert audit.principal_id == administrator.id
    assert audit.operation == "organizations.convention_series.update"
    assert audit.changed_fields == [
        "name",
        "description",
        "website_url",
        "contact_email",
        "is_active",
        "profile_version",
    ]
    assert event.event_name == "organizations.convention_series.updated.v1"
    assert event.aggregate_id == series.id
    assert event.aggregate_version == 2
    assert event.payload["changed_fields"] == (
        "name,description,website_url,contact_email,is_active"
    )
    assert outbox.event_id == event.id
    evidence = f"{audit.safe_metadata}|{event.payload}|{audit.changed_fields}"
    assert "private-looking" not in evidence
    assert "team@example.invalid" not in evidence

    content = response.content.decode()
    assert "Updated convention series" in content
    assert "by Synthetic Steward" in content
    assert "Changed: name, description, website, contact email, availability" in content
    assert str(administrator.id) not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_noop_and_unknown_input_write_nothing() -> None:
    _, client = _administrator_client()
    series = ConventionSeriesFactory()

    no_op = client.post(_record_url(series), _profile_payload(series))
    unknown = client.post(
        _record_url(series),
        _profile_payload(series, organization_id=str(uuid4()), slug="forged"),
    )

    assert no_op.status_code == 302
    assert unknown.status_code == 200
    assert "Remove unsupported input fields" in unknown.content.decode()
    series.refresh_from_db()
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_rejects_stale_version_with_conflict() -> None:
    _, client = _administrator_client()
    series = ConventionSeriesFactory()
    ConventionSeries.objects.filter(id=series.id).update(
        name="Concurrent synthetic name",
        profile_version=F("profile_version") + 1,
    )
    series.refresh_from_db()

    response = client.post(
        _record_url(series),
        _profile_payload(
            series,
            name="Stale attempted name",
            expected_profile_version=1,
        ),
    )

    assert response.status_code == 409
    content = response.content.decode()
    assert "changed after the page was loaded" in content
    assert "Stale attempted name" in content
    series.refresh_from_db()
    assert series.name != "Stale attempted name"
    assert series.profile_version == 2
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_closed_parent_and_inactive_series_states_are_truthful() -> None:
    _, client = _administrator_client()
    closed = OrganizationFactory(lifecycle=Organization.Lifecycle.CLOSED)
    closed_series = ConventionSeriesFactory(organization=closed)
    inactive = ConventionSeriesFactory(is_active=False)

    closed_response = client.get(_record_url(closed_series))
    inactive_response = client.get(_record_url(inactive))

    assert closed_response.status_code == 200
    closed_content = closed_response.content.decode()
    assert "Series profile is read-only" in closed_content
    assert 'name="expected_profile_version"' not in closed_content
    assert "/editions/new/" not in closed_content
    assert "does not store its own sharing list" in closed_content

    assert inactive_response.status_code == 200
    inactive_content = inactive_response.content.decode()
    assert "No editions; series is Inactive" in inactive_content
    assert "/editions/new/" not in inactive_content
    assert 'name="expected_profile_version"' in inactive_content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_authorizes_before_lookup_and_enforces_route_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary = AccountFactory(is_staff=True)
    client = APIClient()
    client.force_login(ordinary)

    def unexpected_lookup(*args: object, **kwargs: object) -> ConventionSeries:
        del args, kwargs
        raise AssertionError("denied requests must not resolve scoped records")

    monkeypatch.setattr("maru.core.views._organization_for_record", unexpected_lookup)
    denied = client.get("/admin/organizations/hidden/series/hidden/")
    assert denied.status_code == 403
    monkeypatch.undo()

    _, administrator_client = _administrator_client()
    series = ConventionSeriesFactory()
    wrong_organization = OrganizationFactory(slug="wrong-parent")
    mismatch = administrator_client.get(
        f"/admin/organizations/{wrong_organization.slug}/series/{series.slug}/"
    )
    assert mismatch.status_code == 404


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_database_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _administrator_client()

    def unavailable(*args: object, **kwargs: object) -> Organization:
        del args, kwargs
        raise DatabaseError("synthetic private database message")

    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable)
    response = client.get("/admin/organizations/unavailable/series/unavailable/")

    assert response.status_code == 503
    content = response.content.decode()
    assert "The convention series could not be loaded" in content
    assert "synthetic private database message" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_series_record_runtime_write_failure_is_safe_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _administrator_client()
    series = ConventionSeriesFactory(name="Original Synthetic Series")

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic private series effect failure")

    monkeypatch.setattr(
        "maru.organizations.services.publish_domain_event",
        unavailable,
    )
    response = client.post(
        _record_url(series),
        _profile_payload(series, name="Must Roll Back"),
    )

    assert response.status_code == 503
    assert "could not be updated" in response.content.decode()
    assert "synthetic private" not in response.content.decode()
    series.refresh_from_db()
    assert series.name == "Original Synthetic Series"
    assert series.profile_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_series_database_guard_rejects_unversioned_profile_and_identity_changes() -> (
    None
):
    series = ConventionSeriesFactory()
    with transaction.atomic(), pytest.raises(IntegrityError):
        ConventionSeries.objects.filter(id=series.id).update(name="Raw bypass")
    with transaction.atomic(), pytest.raises(IntegrityError):
        ConventionSeries.objects.filter(id=series.id).update(slug="raw-bypass")
