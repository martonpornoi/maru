from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.models import EditionCreationReceipt, EventEdition
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import Department, PositionAssignment
from tests.factories import AccountFactory, ConventionSeriesFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _create_url(series: ConventionSeries) -> str:
    return (
        f"/admin/organizations/{series.organization.slug}/series/{series.slug}/"
        "editions/new/"
    )


def _payload(*, key: UUID | None = None, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Synthetic MaruCon 2031",
        "starts_on": "2031-08-14",
        "ends_on": "2031-08-17",
        "time_zone": "Europe/Vienna",
        "language_codes": ["de", "en"],
        "currency_codes": "EUR",
        "adoption_profile_code": "full_convention",
        "idempotency_key": str(key or uuid4()),
    }
    payload.update(changes)
    return payload


def _administrator_client() -> tuple:
    administrator = AccountFactory(
        display_name="Synthetic Platform Administrator",
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)
    return administrator, client


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_page_inherits_visible_locale_defaults_and_has_strict_scope() -> None:
    _, client = _administrator_client()
    organization = OrganizationFactory(
        name="Synthetic Maru Organizers",
        slug="synthetic-maru",
        default_time_zone="Europe/Vienna",
        default_language_codes=["de", "en"],
    )
    series = ConventionSeriesFactory(
        organization=organization,
        name="Synthetic MaruCon",
        slug="synthetic-marucon",
    )

    response = client.get(_create_url(series))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="create-event-edition"' in content
    assert 'href="#main-content">Skip to main content</a>' in content
    assert 'id="main-content"' in content
    assert "Create event edition" in content
    assert '<option value="Europe/Vienna" selected>' in content
    assert '<option value="de" selected>' in content
    assert '<option value="en" selected>' in content
    assert 'name="currency_codes"' in content
    assert 'name="adoption_profile_code"' in content
    assert "Choose what this edition will use" in content
    assert 'name="idempotency_key"' in content
    assert 'name="slug"' not in content
    assert 'name="lifecycle"' not in content
    assert 'name="organization_id"' not in content
    assert 'name="series_id"' not in content
    assert content.count('aria-current="page"') == 1
    assert "Platform access, not participation" not in content
    assert '<summary id="maru-access-heading">' in content
    assert "does not store its own sharing list" in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_is_atomic_audited_explicit_context_and_non_participating() -> None:
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory(
        organization=OrganizationFactory(
            slug="synthetic-maru",
            lifecycle=Organization.Lifecycle.ACTIVE,
        ),
        slug="synthetic-marucon",
    )
    key = uuid4()

    response = client.post(_create_url(series), _payload(key=key))

    edition = EventEdition.objects.get()
    assert response.status_code == 302
    assert response["Location"] == (
        f"/admin/organizations/{series.organization.slug}/series/{series.slug}/"
        f"editions/{edition.slug}/"
    )
    assert edition.organization_id == series.organization_id
    assert edition.series_id == series.id
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    assert edition.lifecycle_version == 0
    assert edition.aggregate_version == 1
    assert edition.adoption_profile_code == "full_convention"
    assert edition.language_codes == ["de", "en"]
    assert edition.currency_codes == ["EUR"]
    assert ADMIN_EDITION_SESSION_KEY not in client.session

    receipt = EditionCreationReceipt.objects.get()
    audit = AuditEvent.objects.get()
    event = DomainEvent.objects.get()
    outbox = OutboxMessage.objects.get()
    assert receipt.edition_id == edition.id
    assert receipt.idempotency_key == key
    assert audit.principal_id == administrator.id
    assert audit.operation == "events.edition.create"
    assert event.event_name == "events.edition.created.v1"
    assert event.aggregate_version == 1
    assert outbox.event_id == event.id
    assert "Synthetic MaruCon 2031" not in str(event.payload)

    assert not OrganizationMembership.objects.filter(account=administrator).exists()
    assert not Participation.objects.filter(account=administrator).exists()
    assert not Registration.objects.filter(account=administrator).exists()
    assert not CapabilityGrant.objects.filter(principal=administrator).exists()
    assert not RoleAssignment.objects.filter(principal=administrator).exists()
    assert not Department.objects.exists()
    assert not PositionAssignment.objects.filter(account=administrator).exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_validation_preserves_retry_key_and_rejects_unknown_fields() -> None:
    _, client = _administrator_client()
    series = ConventionSeriesFactory()
    key = uuid4()

    invalid = client.post(
        _create_url(series),
        _payload(key=key, ends_on="2031-09-20"),
    )
    unknown = client.post(
        _create_url(series),
        _payload(
            key=uuid4(),
            organization_id=str(series.organization_id),
            lifecycle="live",
            slug="forged",
        ),
    )

    assert invalid.status_code == 200
    invalid_content = invalid.content.decode()
    assert "cannot exceed 31 days" in invalid_content
    assert f'value="{key}"' in invalid_content
    assert unknown.status_code == 200
    assert "Remove unsupported input fields" in unknown.content.decode()
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
@pytest.mark.parametrize(
    ("closed", "active", "expected_text"),
    [
        (True, True, "is Closed"),
        (False, False, "is Inactive"),
    ],
)
def test_creation_blocked_state_is_non_mutating_and_keeps_navigation_current(
    closed: bool,
    active: bool,
    expected_text: str,
) -> None:
    _, client = _administrator_client()
    organization = OrganizationFactory(
        lifecycle=(
            Organization.Lifecycle.CLOSED if closed else Organization.Lifecycle.ACTIVE
        )
    )
    series = ConventionSeriesFactory(organization=organization, is_active=active)

    get_response = client.get(_create_url(series))
    post_response = client.post(_create_url(series), _payload())

    assert get_response.status_code == 409
    assert post_response.status_code == 409
    content = get_response.content.decode()
    assert "Edition creation is unavailable" in content
    assert expected_text in content
    assert 'name="idempotency_key"' not in content
    assert content.count('aria-current="page"') == 1
    assert "does not store its own sharing list" in content
    assert not EventEdition.objects.exists()
    assert not AuditEvent.objects.exists()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_authorizes_before_lookup_and_hides_mismatched_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary = AccountFactory(is_staff=True)
    denied_client = APIClient()
    denied_client.force_login(ordinary)

    def unexpected_lookup(*args: object, **kwargs: object) -> Organization:
        del args, kwargs
        raise AssertionError("denied requests must not resolve scoped parents")

    monkeypatch.setattr("maru.core.views._organization_for_record", unexpected_lookup)
    assert (
        denied_client.get(
            "/admin/organizations/hidden/series/hidden/editions/new/"
        ).status_code
        == 403
    )
    monkeypatch.undo()

    _, client = _administrator_client()
    series = ConventionSeriesFactory()
    wrong = OrganizationFactory(slug="wrong-owner")
    mismatch = client.get(
        f"/admin/organizations/{wrong.slug}/series/{series.slug}/editions/new/"
    )
    assert mismatch.status_code == 404


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_database_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _, client = _administrator_client()

    def unavailable(*args: object, **kwargs: object) -> Organization:
        del args, kwargs
        raise DatabaseError("synthetic private database failure")

    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable)
    response = client.get(
        "/admin/organizations/unavailable/series/unavailable/editions/new/"
    )

    assert response.status_code == 503
    content = response.content.decode()
    assert "The convention series could not be loaded" in content
    assert "synthetic private database failure" not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_creation_runtime_write_failure_is_safe_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _administrator_client()
    series = ConventionSeriesFactory()

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic private edition effect failure")

    monkeypatch.setattr("maru.events.services.publish_domain_event", unavailable)
    response = client.post(_create_url(series), _payload())

    assert response.status_code == 503
    assert "could not be created" in response.content.decode()
    assert "synthetic private" not in response.content.decode()
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()
