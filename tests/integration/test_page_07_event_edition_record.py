from datetime import date
from uuid import uuid4

import pytest
from django.db import DatabaseError
from django.test import override_settings
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.models import EventEdition
from maru.events.serializers import EditionBasicSerializer
from maru.events.services import (
    EventEditionDetails,
    create_event_edition,
    transition_edition,
)
from maru.identity.models import Account
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
)
from maru.organizations.representation import (
    activate_executive_board,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from maru.participation.models import Participation
from maru.registration.models import Registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _record_url(edition: EventEdition) -> str:
    return (
        f"/admin/organizations/{edition.organization.slug}/series/"
        f"{edition.series.slug}/editions/{edition.slug}/"
    )


def _profile_payload(
    edition: EventEdition,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": edition.name,
        "starts_on": edition.starts_on.isoformat(),
        "ends_on": edition.ends_on.isoformat(),
        "time_zone": edition.time_zone,
        "language_codes": list(edition.language_codes),
        "currency_codes": ", ".join(edition.currency_codes),
        "expected_aggregate_version": edition.aggregate_version,
    }
    payload.update(changes)
    return payload


def _api_payload(edition: EventEdition, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": edition.name,
        "starts_on": edition.starts_on.isoformat(),
        "ends_on": edition.ends_on.isoformat(),
        "time_zone": edition.time_zone,
        "language_codes": list(edition.language_codes),
        "currency_codes": list(edition.currency_codes),
        "expected_aggregate_version": edition.aggregate_version,
    }
    payload.update(changes)
    return payload


def _administrator_client() -> tuple:
    administrator = AccountFactory(
        display_name="Synthetic Edition Steward",
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_login(administrator)
    return administrator, client


def _create_edition(*, actor: object, series: ConventionSeries) -> EventEdition:
    return create_event_edition(
        actor=actor,  # type: ignore[arg-type]
        organization_id=series.organization_id,
        series_id=series.id,
        details=EventEditionDetails(
            name="Synthetic MaruCon 2031",
            starts_on=date(2031, 8, 14),
            ends_on=date(2031, 8, 17),
            time_zone="Europe/Vienna",
            language_codes=("de", "en"),
            currency_codes=("EUR",),
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="web",
    ).edition


def _domain_write_counts() -> dict[str, int]:
    return {
        "capability_grants": CapabilityGrant.objects.count(),
        "role_assignments": RoleAssignment.objects.count(),
        "memberships": OrganizationMembership.objects.count(),
        "participations": Participation.objects.count(),
        "registrations": Registration.objects.count(),
        "audit_events": AuditEvent.objects.count(),
        "domain_events": DomainEvent.objects.count(),
        "outbox_messages": OutboxMessage.objects.count(),
    }


def _activate_board_controller(
    *, administrator: Account, organization: Organization
) -> Account:
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic accountable governance.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    controllers = tuple(
        AccountFactory(display_name=display_name)
        for display_name in (
            "Synthetic Board Context Controller One",
            "Synthetic Board Context Controller Two",
        )
    )
    for controller in controllers:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic accountable controller.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel="test",
        )
    representation.refresh_from_db()
    activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate the synthetic Executive Board.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    return controllers[0]


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_record_is_scoped_detailed_and_does_not_select_on_get() -> None:
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory(
        organization=OrganizationFactory(
            name="Synthetic Maru Organizers",
            slug="synthetic-maru",
        ),
        name="Synthetic MaruCon",
        slug="synthetic-marucon",
    )
    edition = _create_edition(actor=administrator, series=series)

    response = client.get(_record_url(edition))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-page="event-edition-record"' in content
    assert 'href="#main-content">Skip to main content</a>' in content
    assert 'id="main-content"' in content
    assert "Synthetic MaruCon 2031" in content
    assert "Europe/Vienna" in content
    assert "de, en" in content
    assert "EUR" in content
    assert 'class="baseline-count">Record version 1' in content
    assert response.context_data["edition"].aggregate_version == 1
    assert 'name="expected_aggregate_version"' in content
    assert 'name="slug"' not in content
    assert 'name="lifecycle"' not in content
    assert "Use Synthetic MaruCon 2031" in content
    assert content.count('aria-current="page"') == 1
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert "Created event edition" in content
    assert "by Synthetic Edition Steward" in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_working_edition_context_requires_explicit_post_and_never_grants_access() -> (
    None
):
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory()
    target = _create_edition(actor=administrator, series=series)
    other = EventEditionFactory(
        organization=series.organization,
        series=series,
        name="Other Synthetic Edition",
    )
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(other.id)
    session.save()
    expected_domain_counts = _domain_write_counts()

    viewed = client.get(_record_url(target))
    select_url = f"{_record_url(target)}select/"
    clear_url = f"{_record_url(target)}clear/"

    assert viewed.status_code == 200
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(other.id)
    assert client.get(select_url).status_code == 405
    assert client.get(clear_url).status_code == 405
    assert f'action="{select_url}"' in viewed.content.decode()
    assert "csrfmiddlewaretoken" in viewed.content.decode()
    assert _domain_write_counts() == expected_domain_counts

    rejected_select = client.post(
        select_url,
        {"edition_id": str(target.id)},
        follow=True,
    )
    assert rejected_select.status_code == 200
    assert (
        "Remove unsupported input fields: edition_id"
        in rejected_select.content.decode()
    )
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(other.id)
    assert _domain_write_counts() == expected_domain_counts

    selected = client.post(select_url, follow=True)
    assert selected.status_code == 200
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(target.id)
    selected_content = selected.content.decode()
    assert "This edition is selected" in selected_content
    assert "never grants access" in selected_content
    assert f'action="{clear_url}"' in selected_content
    assert _domain_write_counts() == expected_domain_counts

    rejected_clear = client.post(clear_url, {"scope": "forged"}, follow=True)
    assert rejected_clear.status_code == 200
    assert "Remove unsupported input fields: scope" in rejected_clear.content.decode()
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(target.id)
    assert _domain_write_counts() == expected_domain_counts

    cleared = client.post(clear_url, follow=True)
    assert cleared.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert _domain_write_counts() == expected_domain_counts


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_canonical_board_context_actions_change_only_the_session() -> None:
    administrator, _ = _administrator_client()
    organization = OrganizationFactory(
        name="Synthetic Board Context Organization",
        slug="synthetic-board-context",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    series = ConventionSeriesFactory(organization=organization)
    target = EventEditionFactory(
        organization=organization,
        series=series,
        name="Synthetic Board Context Target",
    )
    controller = _activate_board_controller(
        administrator=administrator,
        organization=organization,
    )
    client = APIClient()
    client.force_login(controller)
    select_url = f"{_record_url(target)}select/"
    clear_url = f"{_record_url(target)}clear/"
    expected_domain_counts = _domain_write_counts()
    assert (
        RoleAssignment.objects.filter(
            principal=controller,
            organization=organization,
            role_bundle__code="executive-board",
            revoked_at__isnull=True,
        ).count()
        == 1
    )

    selected = client.post(select_url, follow=True)
    assert selected.status_code == 200
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(target.id)
    assert _domain_write_counts() == expected_domain_counts

    rejected_clear = client.post(clear_url, {"scope": "forged"}, follow=True)
    assert rejected_clear.status_code == 200
    assert "Remove unsupported input fields: scope" in rejected_clear.content.decode()
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(target.id)
    assert _domain_write_counts() == expected_domain_counts

    cleared = client.post(clear_url, follow=True)
    assert cleared.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert _domain_write_counts() == expected_domain_counts


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_scoped_viewer_can_select_only_the_exact_authorized_edition() -> None:
    actor = AccountFactory(is_staff=False, is_superuser=False)
    authorized = EventEditionFactory()
    sibling = EventEditionFactory(
        organization=authorized.organization,
        series=authorized.series,
    )
    foreign = EventEditionFactory()
    CapabilityGrantFactory(
        organization=authorized.organization,
        edition=authorized,
        principal=actor,
        capability_code="events.view_basic",
    )
    client = APIClient()
    client.force_login(actor)
    expected_domain_counts = _domain_write_counts()

    viewed = client.get(_record_url(authorized))
    selected = client.post(f"{_record_url(authorized)}select/", follow=True)

    assert viewed.status_code == 200
    assert selected.status_code == 200
    assert client.session[ADMIN_EDITION_SESSION_KEY] == str(authorized.id)
    assert "This edition is selected" in selected.content.decode()
    assert _domain_write_counts() == expected_domain_counts

    for denied in (sibling, foreign):
        response = client.post(f"{_record_url(denied)}select/")
        assert response.status_code == 403
        assert client.session[ADMIN_EDITION_SESSION_KEY] == str(authorized.id)
        assert _domain_write_counts() == expected_domain_counts

    cleared = client.post(f"{_record_url(authorized)}clear/", follow=True)
    assert cleared.status_code == 200
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    assert _domain_write_counts() == expected_domain_counts


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_context_and_profile_posts_enforce_csrf() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()
    edition = _create_edition(actor=administrator, series=series)
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(administrator)

    selected = client.post(f"{_record_url(edition)}select/")
    updated = client.post(
        _record_url(edition),
        _profile_payload(edition, name="Forged"),
    )

    assert selected.status_code == 403
    assert updated.status_code == 403
    assert ADMIN_EDITION_SESSION_KEY not in client.session
    edition.refresh_from_db()
    assert edition.name != "Forged"
    assert edition.aggregate_version == 1


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_profile_update_is_versioned_and_activity_is_value_minimized() -> None:
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory()
    edition = _create_edition(actor=administrator, series=series)
    original_slug = edition.slug

    response = client.post(
        _record_url(edition),
        _profile_payload(
            edition,
            name="Synthetic MaruCon Alpine 2031",
            starts_on="2031-08-15",
            ends_on="2031-08-18",
            currency_codes="EUR, CHF",
        ),
        follow=True,
    )

    assert response.status_code == 200
    edition.refresh_from_db()
    assert edition.name == "Synthetic MaruCon Alpine 2031"
    assert edition.slug == original_slug
    assert edition.organization_id == series.organization_id
    assert edition.series_id == series.id
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    assert edition.lifecycle_version == 0
    assert edition.aggregate_version == 2
    assert edition.currency_codes == ["EUR", "CHF"]

    assert AuditEvent.objects.count() == 2
    assert DomainEvent.objects.count() == 2
    assert OutboxMessage.objects.count() == 2
    update_event = DomainEvent.objects.get(
        event_name="events.edition.details_updated.v1"
    )
    assert update_event.aggregate_version == 2
    assert update_event.payload["changed_fields"] == (
        "name,starts_on,ends_on,currency_codes"
    )
    assert "Alpine" not in str(update_event.payload)
    content = response.content.decode()
    assert "Updated event edition" in content
    assert "Changed: name, start date, end date, currencies" in content
    assert str(administrator.id) not in content


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_record_rejects_stale_and_unknown_inputs() -> None:
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory()
    edition = _create_edition(actor=administrator, series=series)
    stale_payload = _profile_payload(
        edition,
        name="Stale attempted title",
        expected_aggregate_version=1,
    )
    transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=administrator,
        reason="Begin synthetic preparation.",
        correlation_id=uuid4(),
    )

    stale = client.post(_record_url(edition), stale_payload)
    edition.refresh_from_db()
    unknown = client.post(
        _record_url(edition),
        _profile_payload(
            edition,
            series_id=str(series.id),
            lifecycle="live",
            aggregate_version=999,
        ),
    )

    assert stale.status_code == 409
    assert "changed after the page was loaded" in stale.content.decode()
    assert unknown.status_code == 200
    assert "Remove unsupported input fields" in unknown.content.decode()
    edition.refresh_from_db()
    assert edition.name != "Stale attempted title"
    assert edition.lifecycle == EventEdition.Lifecycle.PREPARING
    assert edition.aggregate_version == 2


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_ready_and_closed_edition_profiles_are_read_only() -> None:
    administrator, client = _administrator_client()
    series = ConventionSeriesFactory()
    edition = _create_edition(actor=administrator, series=series)
    transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=administrator,
        reason="Prepare synthetic edition.",
        correlation_id=uuid4(),
    )
    transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.READY,
        actor=administrator,
        reason="Synthetic readiness complete.",
        correlation_id=uuid4(),
    )
    edition.refresh_from_db()

    ready = client.get(_record_url(edition))
    rejected = client.post(_record_url(edition), _profile_payload(edition))
    assert ready.status_code == 200
    assert rejected.status_code == 409
    ready_content = ready.content.decode()
    assert "Edition profile is read-only" in ready_content
    assert 'name="expected_aggregate_version"' not in ready_content
    assert "view this event-edition record" in ready_content

    EventEdition.objects.filter(id=edition.id).update(
        lifecycle=EventEdition.Lifecycle.PREPARING,
        lifecycle_version=edition.lifecycle_version + 1,
        aggregate_version=edition.aggregate_version + 1,
    )
    Organization.objects.filter(id=series.organization_id).update(
        lifecycle=Organization.Lifecycle.CLOSED
    )
    edition.refresh_from_db()
    closed = client.get(_record_url(edition))
    assert "is Closed" in closed.content.decode()
    assert 'name="expected_aggregate_version"' not in closed.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_record_authorization_scope_and_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary = AccountFactory(is_staff=True)
    denied_client = APIClient()
    denied_client.force_login(ordinary)

    def unexpected_lookup(*args: object, **kwargs: object) -> Organization:
        del args, kwargs
        raise AssertionError("denied requests must not resolve edition scope")

    monkeypatch.setattr("maru.core.views._organization_for_record", unexpected_lookup)
    assert (
        denied_client.get(
            "/admin/organizations/hidden/series/hidden/editions/hidden/"
        ).status_code
        == 403
    )
    monkeypatch.undo()

    _, client = _administrator_client()
    edition = EventEditionFactory()
    wrong = OrganizationFactory(slug="wrong-organization")
    mismatch = client.get(
        f"/admin/organizations/{wrong.slug}/series/{edition.series.slug}/"
        f"editions/{edition.slug}/"
    )
    assert mismatch.status_code == 404

    def unavailable(*args: object, **kwargs: object) -> Organization:
        del args, kwargs
        raise DatabaseError("synthetic private record failure")

    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable)
    failed = client.get(
        "/admin/organizations/unavailable/series/unavailable/editions/unavailable/"
    )
    assert failed.status_code == 503
    assert "The event edition could not be loaded" in failed.content.decode()
    assert "synthetic private record failure" not in failed.content.decode()


def test_edition_profile_put_api_shares_command_and_strict_conflicts() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    series = ConventionSeriesFactory()
    edition = _create_edition(actor=administrator, series=series)
    client = APIClient()
    client.force_authenticate(administrator)
    url = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"

    updated = client.put(
        url,
        _api_payload(edition, name="Synthetic API Edition 2031"),
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Synthetic API Edition 2031"
    assert updated.json()["aggregate_version"] == 2

    unknown = client.put(
        url,
        _api_payload(
            edition,
            expected_aggregate_version=2,
            organization_id=str(edition.organization_id),
            slug="forged",
        ),
        format="json",
    )
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "unknown_input_field"

    invalid_time_zone = client.put(
        url,
        _api_payload(
            edition,
            expected_aggregate_version=2,
            time_zone="../etc/passwd",
        ),
        format="json",
    )
    assert invalid_time_zone.status_code == 400
    assert invalid_time_zone.json()["code"] == "invalid_time_zone"

    stale = client.put(
        url,
        _api_payload(edition, expected_aggregate_version=1),
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_edition_version"
    assert stale.headers["Content-Type"].startswith("application/problem+json")


def test_edition_profile_put_direct_grant_has_an_explicit_response_ceiling() -> None:
    organizer = AccountFactory()
    edition = EventEditionFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=organizer,
        capability_code="events.change_profile",
    )
    client = APIClient()
    client.force_authenticate(organizer)

    response = client.put(
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}",
        _api_payload(edition, name="Direct-grant Synthetic Edition"),
        format="json",
    )

    assert response.status_code == 200
    assert set(response.json()) == set(EditionBasicSerializer.Meta.fields)
    assert response.json()["name"] == "Direct-grant Synthetic Edition"


def test_edition_profile_put_rolls_back_and_returns_safe_503_on_effect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(name="Original Synthetic Edition")
    client = APIClient()
    client.force_authenticate(administrator)

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic private edition update failure")

    monkeypatch.setattr("maru.events.services.publish_domain_event", unavailable)
    response = client.put(
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}",
        _api_payload(edition, name="Must Roll Back"),
        format="json",
    )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "synthetic private" not in response.content.decode()
    edition.refresh_from_db()
    assert edition.name == "Original Synthetic Edition"
    assert edition.aggregate_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_edition_api_lookup_failure_is_a_safe_stable_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    client = APIClient()
    client.force_authenticate(administrator)

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private edition lookup failure")

    monkeypatch.setattr("maru.events.api.get_object_or_404", unavailable)
    response = client.get(
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"
    )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "synthetic private" not in response.content.decode()


@override_settings(ROOT_URLCONF="maru.baseline_urls")
def test_edition_record_context_and_context_actions_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _administrator_client()
    edition = EventEditionFactory()

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise DatabaseError("synthetic private context failure")

    monkeypatch.setattr("maru.core.views.selected_admin_edition", unavailable)
    record = client.get(_record_url(edition))
    assert record.status_code == 503
    assert "The event edition could not be loaded" in record.content.decode()
    assert "synthetic private" not in record.content.decode()

    monkeypatch.undo()
    monkeypatch.setattr("maru.core.views._organization_for_record", unavailable)
    selected = client.post(f"{_record_url(edition)}select/")
    cleared = client.post(f"{_record_url(edition)}clear/")
    assert selected.status_code == 503
    assert cleared.status_code == 503
    assert "synthetic private" not in selected.content.decode()
    assert "synthetic private" not in cleared.content.decode()
