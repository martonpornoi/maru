"""Venue catalog, exact scheduling, and minimized projection coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.authorization.models import ScopedResourceBinding
from maru.authorization.provenance_readiness import (
    _FUNCTION_DEFINITION_SHA256,
    _function_definition_fingerprint,
)
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.venues import queries as venue_queries
from maru.venues.authorization import resolve_edition_space_target
from maru.venues.bindings import edition_space_binding_id
from maru.venues.models import (
    AccommodationRoomType,
    EditionSpaceSelection,
    VenueBooking,
    VenueBookingHistory,
    VenueProperty,
    VenueSpace,
    VenueSpaceConfiguration,
)
from maru.venues.queries import public_schedule_for_edition
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueAvailabilityInterval,
    VenueBookingEnvelope,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueIndependentApprovalError,
    VenuePropertyProfile,
    VenueSpaceCatalogInput,
    approve_venue_booking,
    create_venue_booking,
    create_venue_property,
    create_venue_space_catalog_path,
    publish_venue_booking,
    select_space_for_edition,
    select_venue_for_edition,
    set_edition_space_availability,
    update_venue_property,
)
from maru.workforce.models import Department
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _Scope:
    edition: EventEdition
    department: Department
    manager: Account
    selector: Account
    scheduler: Account
    approver: Account
    publisher: Account


def _grant_organization(actor: Account, scope: _Scope, capability: str) -> None:
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        principal=actor,
        capability_code=capability,
    )


def _grant_edition(actor: Account, scope: _Scope, capability: str) -> None:
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=actor,
        capability_code=capability,
    )


def _grant_space(
    actor: Account,
    scope: _Scope,
    space_selection: EditionSpaceSelection,
    capability: str,
) -> None:
    binding = ScopedResourceBinding.objects.get(
        resource_kind=ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE,
        resource_id=space_selection.id,
    )
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        resource_binding=binding,
        principal=actor,
        capability_code=capability,
    )


def _scope(
    *,
    starts_on: date | None = None,
    name: str | None = None,
) -> _Scope:
    edition_values: dict[str, object] = {}
    if starts_on is not None:
        edition_values.update(
            starts_on=starts_on,
            ends_on=starts_on + timedelta(days=3),
        )
    if name is not None:
        edition_values["name"] = name
    edition = EventEditionFactory(**edition_values)
    department = create_department_for_test(
        edition=edition,
        name="Venue Operations",
        expected_code="venue-operations",
    )
    scope = _Scope(
        edition=edition,
        department=department,
        manager=AccountFactory(),
        selector=AccountFactory(),
        scheduler=AccountFactory(),
        approver=AccountFactory(),
        publisher=AccountFactory(),
    )
    _grant_organization(scope.manager, scope, "venues.manage_properties")
    _grant_organization(scope.manager, scope, "venues.view_properties")
    _grant_edition(scope.selector, scope, "venues.select_for_edition")
    _grant_edition(scope.selector, scope, "venues.view_workspace")
    return scope


def _selected_space(scope: _Scope) -> EditionSpaceSelection:
    created = create_venue_property(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        slug="riverside-convention-hotel",
        profile=VenuePropertyProfile(
            kind=VenueProperty.Kind.MIXED,
            legal_name="Riverside Convention Hotel Limited",
            provider_name="Riverside Hospitality",
            public_name="Riverside Convention Hotel",
            public_description="The event hotel and convention venue.",
            internal_notes="Private contract and escalation notes.",
            location_name="Budapest",
            postal_address="Private provider address",
            country_code="HU",
            website_url="https://venue.example.invalid",
            public_contact="Convention desk",
            contact_name="Private provider contact",
            contact_email="provider@example.invalid",
            contact_phone="+3612345678",
        ),
        reason="Create the reusable property catalog record.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    update_venue_property(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=created.object_id,
        expected_version=created.resulting_version,
        changes={"lifecycle": VenueProperty.Lifecycle.ACTIVE},
        reason="Provider diligence is complete.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    property_record = VenueProperty.objects.get(id=created.object_id)
    catalog = create_venue_space_catalog_path(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=property_record.id,
        catalog=VenueSpaceCatalogInput(
            site_code="main-site",
            site_name="Main site",
            building_code="conference-wing",
            building_name="Conference wing",
            space_code="grand-hall",
            space_name="Grand Hall",
            space_kind=VenueSpace.Kind.FUNCTION_ROOM,
            configuration_code="theatre",
            configuration_name="Theatre",
            seated_capacity=100,
            standing_capacity=140,
            table_capacity=60,
            fire_capacity=150,
            public_description="Main programme hall.",
            accessibility_features="Step-free attendee entrance.",
            known_barriers="",
            equipment_facts="House sound and projection.",
        ),
        reason="Register the initial physical room and configuration.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    source_space = VenueSpace.objects.get(id=catalog.object_id)
    configuration = VenueSpaceConfiguration.objects.get(space=source_space)
    venue_selection = select_venue_for_edition(
        actor=scope.selector,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        property_id=property_record.id,
        responsible_department_id=scope.department.id,
        local_name="Convention Hotel",
        public_description_override="The convention's main venue.",
        public_contact_override="Convention information desk",
        opening_restrictions="Attendee areas follow the published programme.",
        reason="Select this property for the edition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    selected = select_space_for_edition(
        actor=scope.selector,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        venue_selection_id=venue_selection.object_id,
        source_space_id=source_space.id,
        source_combination_id=None,
        selected_configuration_id=configuration.id,
        local_name="Main Stage",
        capacity=None,
        public_access_info="Step-free route from the lobby.",
        opening_restrictions="Open only during published events.",
        reason="Select the main programme space.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return EditionSpaceSelection.objects.get(id=selected.object_id)


def _configure_schedule(scope: _Scope, space: EditionSpaceSelection) -> datetime:
    _grant_space(scope.scheduler, scope, space, "venues.manage_space_schedule")
    _grant_space(scope.approver, scope, space, "venues.manage_space_schedule")
    _grant_space(scope.publisher, scope, space, "venues.publish_space_schedule")
    start = timezone.now().replace(second=0, microsecond=0) + timedelta(days=7)
    set_edition_space_availability(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        expected_version=space.aggregate_version,
        intervals=(
            VenueAvailabilityInterval(
                starts_at=start,
                ends_at=start + timedelta(hours=12),
                opening_restriction="Staff access before public opening.",
            ),
        ),
        reason="Set the contracted operational availability.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return start


def _local_minute(value: datetime, *, edition: EventEdition) -> str:
    return value.astimezone(ZoneInfo(edition.time_zone)).strftime("%Y-%m-%dT%H:%M")


def _booking_form_data(
    *,
    edition: EventEdition,
    start: datetime,
    attendance: int = 80,
    internal_title: str = "Private browser production title",
) -> dict[str, str]:
    return {
        "retry_key": str(uuid4()),
        "kind": VenueBooking.Kind.PANEL,
        "external_reference": "private-browser-reference",
        "internal_title": internal_title,
        "public_title": "Browser opening panel",
        "public_description": "Attendee-safe browser schedule item.",
        "capacity_mode": VenueBooking.CapacityMode.SEATED,
        "expected_attendance": str(attendance),
        "setup_starts_at": _local_minute(
            start + timedelta(minutes=10),
            edition=edition,
        ),
        "effective_starts_at": _local_minute(
            start + timedelta(minutes=20),
            edition=edition,
        ),
        "effective_ends_at": _local_minute(
            start + timedelta(minutes=50),
            edition=edition,
        ),
        "teardown_ends_at": _local_minute(
            start + timedelta(minutes=60),
            edition=edition,
        ),
        "public_layout_id": "",
        "reason": "Exercise the same-shell venue booking workflow.",
    }


def _publish_schedule(scope: _Scope) -> EditionSpaceSelection:
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    created = _create_booking(scope, space, start=start)
    approved = approve_venue_booking(
        actor=scope.approver,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=created.resulting_version,
        reason="Approve the attendee schedule fixture independently.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    publish_venue_booking(
        actor=scope.publisher,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=approved.resulting_version,
        reason="Publish the attendee schedule fixture independently.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return space


def _create_booking(
    scope: _Scope,
    space: EditionSpaceSelection,
    *,
    start: datetime,
    attendance: int = 80,
    internal_title: str = "Private production title",
):
    return create_venue_booking(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        kind=VenueBooking.Kind.PANEL,
        external_reference="private-programme-reference",
        internal_title=internal_title,
        public_title="Opening panel",
        public_description="Welcome to the convention.",
        capacity_mode=VenueBooking.CapacityMode.SEATED,
        expected_attendance=attendance,
        envelope=VenueBookingEnvelope(
            setup_starts_at=start,
            effective_starts_at=start + timedelta(hours=1),
            effective_ends_at=start + timedelta(hours=2),
            teardown_ends_at=start + timedelta(hours=3),
        ),
        public_layout_id=None,
        reason="Reserve the room and its operational envelope.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_published_schedule_projects_only_effective_public_fields() -> None:
    scope = _scope()
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    created = _create_booking(scope, space, start=start)
    approved = approve_venue_booking(
        actor=scope.approver,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=created.resulting_version,
        reason="Operational review is complete.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    publish_venue_booking(
        actor=scope.publisher,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=approved.resulting_version,
        reason="Publish the attendee-safe schedule item.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    projection = public_schedule_for_edition(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
    )
    assert len(projection) == 1
    payload = asdict(projection[0])
    assert payload["starts_at"] == start + timedelta(hours=1)
    assert payload["ends_at"] == start + timedelta(hours=2)
    assert payload["title"] == "Opening panel"
    assert payload["access_info"] == "Step-free route from the lobby."
    assert "setup_starts_at" not in payload
    assert "teardown_ends_at" not in payload
    assert "internal_title" not in payload
    assert "external_reference" not in payload
    assert "expected_attendance" not in payload


def test_hard_availability_capacity_and_physical_overlap_fail_closed() -> None:
    scope = _scope()
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    _create_booking(scope, space, start=start)

    with pytest.raises(VenueBookingOverlapError):
        _create_booking(
            scope,
            space,
            start=start + timedelta(minutes=30),
            internal_title="Conflicting booking",
        )
    with pytest.raises(VenueCapacityConflictError):
        _create_booking(
            scope,
            space,
            start=start + timedelta(hours=4),
            attendance=101,
            internal_title="Over capacity",
        )
    with pytest.raises(VenueAvailabilityConflictError):
        _create_booking(
            scope,
            space,
            start=start + timedelta(hours=10),
            internal_title="Outside contracted availability",
        )

    turnover = _create_booking(
        scope,
        space,
        start=start + timedelta(hours=2),
        internal_title="Turnover-safe booking",
    )
    assert VenueBooking.objects.filter(id=turnover.object_id).exists()


def test_exact_binding_scope_and_append_only_history_are_database_enforced() -> None:
    scope = _scope()
    space = _selected_space(scope)
    target = resolve_edition_space_target(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
    )
    assert target is not None
    assert target.resource_binding_id == edition_space_binding_id(space.id)
    assert target.department_id == scope.department.id

    other_edition = EventEditionFactory(
        organization=scope.edition.organization,
        series=scope.edition.series,
    )
    assert (
        resolve_edition_space_target(
            organization_id=scope.edition.organization_id,
            edition_id=other_edition.id,
            space_selection_id=space.id,
        )
        is None
    )
    other_department = create_department_for_test(
        edition=scope.edition,
        name="Other Venue Team",
        expected_code="other-venue-team",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        EditionSpaceSelection.objects.filter(id=space.id).update(
            responsible_department=other_department
        )

    start = _configure_schedule(scope, space)
    booking = _create_booking(scope, space, start=start)
    history = VenueBookingHistory.objects.get(booking_id=booking.object_id, sequence=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        VenueBookingHistory.objects.filter(id=history.id).update(
            reason="Rewritten scheduling history"
        )


def test_independent_approval_and_publication_are_required() -> None:
    scope = _scope()
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    created = _create_booking(scope, space, start=start)
    with pytest.raises(VenueIndependentApprovalError):
        approve_venue_booking(
            actor=scope.scheduler,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            space_selection_id=space.id,
            booking_id=created.object_id,
            expected_version=created.resulting_version,
            reason="The creator cannot approve this booking.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    approved = approve_venue_booking(
        actor=scope.approver,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=created.object_id,
        expected_version=created.resulting_version,
        reason="Approve independently.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    _grant_space(scope.approver, scope, space, "venues.publish_space_schedule")
    with pytest.raises(VenueIndependentApprovalError):
        publish_venue_booking(
            actor=scope.approver,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            space_selection_id=space.id,
            booking_id=created.object_id,
            expected_version=approved.resulting_version,
            reason="The approver cannot publish the same booking.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_platform_admin_has_no_automatic_venue_subject_authority() -> None:
    edition = EventEditionFactory()
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    with pytest.raises(VenueAuthorizationDeniedError):
        create_venue_property(
            actor=platform_admin,
            organization_id=edition.organization_id,
            slug="not-authorized",
            profile=VenuePropertyProfile(
                kind=VenueProperty.Kind.VENUE,
                legal_name="No automatic authority",
                public_name="No automatic authority",
                location_name="Budapest",
                postal_address="Address",
                country_code="HU",
            ),
            reason="Platform status must not grant convention authority.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )


def test_my_maru_schedule_renders_canonical_home_and_shared_navigation() -> None:
    edition = EventEditionFactory()
    attendee = AccountFactory()
    ParticipationFactory(account=attendee, edition=edition)
    client = Client()
    client.force_login(attendee)

    response = client.get(
        reverse(
            "my-maru-venue-schedule",
            args=(
                edition.organization.slug,
                edition.series.slug,
                edition.slug,
            ),
        )
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert f'href="{reverse("my-maru-home")}"' in content
    assert content.count('id="nav-sidebar"') == 1
    assert content.count('id="nav-filter"') == 1
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]


def test_venue_html_authorizes_before_constructing_or_parsing_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    unauthorized = AccountFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(unauthorized)

    def fail_if_form_is_constructed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("authorization must precede form construction")

    monkeypatch.setattr(
        "maru.venues.views.VenuePropertyCreateForm",
        fail_if_form_is_constructed,
    )
    path = reverse(
        "venue-property-create",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
        ),
    )

    malformed = client.post(path, {"unexpected": "do not parse"})
    plausible = client.post(
        path,
        {
            "retry_key": str(uuid4()),
            "slug": "still-not-authorized",
            "kind": VenueProperty.Kind.VENUE,
        },
    )

    assert malformed.status_code == 403
    assert plausible.status_code == 403


def test_same_shell_booking_enforces_capacity_conflict_and_dual_control() -> None:
    scope = _scope()
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    for actor in (scope.scheduler, scope.approver, scope.publisher):
        _grant_space(actor, scope, space, "venues.view_space_schedule")

    client = Client()
    client.force_login(scope.scheduler)
    page_path = reverse(
        "venue-space-schedule-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            space.id,
        ),
    )
    page = client.get(page_path)
    assert page.status_code == 200
    assert "Create an operational booking" in page.content.decode()
    assert page.content.decode().count('id="nav-sidebar"') == 1
    assert "private" in page.headers["Cache-Control"]
    assert "no-store" in page.headers["Cache-Control"]

    create_path = reverse(
        "venue-booking-create",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            space.id,
        ),
    )
    capacity_failure = client.post(
        create_path,
        _booking_form_data(
            edition=scope.edition,
            start=start,
            attendance=101,
            internal_title="Over-capacity browser booking",
        ),
    )
    assert capacity_failure.status_code == 409
    assert "exceeds the selected capacity" in capacity_failure.content.decode()

    created_response = client.post(
        create_path,
        _booking_form_data(edition=scope.edition, start=start),
    )
    assert created_response.status_code == 302
    booking = VenueBooking.objects.get(
        space_selection=space,
        internal_title="Private browser production title",
    )

    overlap_failure = client.post(
        create_path,
        _booking_form_data(
            edition=scope.edition,
            start=start,
            internal_title="Overlapping browser booking",
        ),
    )
    assert overlap_failure.status_code == 409
    assert "physical room is occupied" in overlap_failure.content.decode()

    approve_path = reverse(
        "venue-booking-command-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            space.id,
            booking.id,
            "approve",
        ),
    )
    same_actor_approval = client.post(
        approve_path,
        {
            "retry_key": str(uuid4()),
            "expected_version": str(booking.aggregate_version),
            "reason": "The creator must not approve this booking.",
        },
    )
    assert same_actor_approval.status_code == 409
    assert "different authorized person" in same_actor_approval.content.decode()

    client.force_login(scope.approver)
    approved_response = client.post(
        approve_path,
        {
            "retry_key": str(uuid4()),
            "expected_version": str(booking.aggregate_version),
            "reason": "Approve independently through the browser.",
        },
    )
    assert approved_response.status_code == 302
    booking.refresh_from_db()

    _grant_space(scope.approver, scope, space, "venues.publish_space_schedule")
    publish_path = reverse(
        "venue-booking-command-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            space.id,
            booking.id,
            "publish",
        ),
    )
    same_actor_publication = client.post(
        publish_path,
        {
            "retry_key": str(uuid4()),
            "expected_version": str(booking.aggregate_version),
            "reason": "The approver must not publish the same booking.",
        },
    )
    assert same_actor_publication.status_code == 409
    assert "different authorized person" in same_actor_publication.content.decode()

    client.force_login(scope.publisher)
    published_response = client.post(
        publish_path,
        {
            "retry_key": str(uuid4()),
            "expected_version": str(booking.aggregate_version),
            "reason": "Publish independently through the browser.",
        },
    )
    assert published_response.status_code == 302


def test_my_schedule_index_is_relationship_scoped_recent_and_not_starved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _scope(
        starts_on=date(2030, 8, 1),
        name="Older eligible convention",
    )
    newer = _scope(
        starts_on=date(2031, 8, 1),
        name="Newest eligible convention",
    )
    foreign = _scope(
        starts_on=date(2032, 8, 1),
        name="Foreign unpublished relationship label",
    )
    _publish_schedule(older)
    _publish_schedule(newer)
    _publish_schedule(foreign)

    attendee = AccountFactory()
    ParticipationFactory(account=attendee, edition=older.edition)
    ParticipationFactory(account=attendee, edition=newer.edition)
    monkeypatch.setattr(venue_queries, "MAX_PERSONAL_SCHEDULE_EDITIONS", 1)
    client = Client()
    client.force_login(attendee)

    response = client.get(reverse("my-maru-schedule-index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Newest eligible convention" in content
    assert "Older eligible convention" not in content
    assert "Foreign unpublished relationship label" not in content
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]


def test_public_api_is_minimized_and_staff_api_authorizes_before_parsing() -> None:
    scope = _scope()
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(platform_admin)
    path = f"/api/v1/organizations/{scope.edition.organization_id}/venue-properties"
    with override_settings(ROOT_URLCONF="maru.venues.urls"):
        response = client.post(
            path,
            {"unknown": "body must not be parsed as authorized"},
            format="json",
        )
    assert response.status_code == 403
    assert response.data["code"] == "venue_authorization_denied"
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]

    attendee = AccountFactory()
    ParticipationFactory(account=attendee, edition=scope.edition)
    client.force_authenticate(attendee)
    with override_settings(ROOT_URLCONF="maru.venues.urls"):
        my_response = client.get(
            "/api/v1/my/organizations/"
            f"{scope.edition.organization_id}/editions/{scope.edition.id}/"
            "venue-schedule"
        )
    assert my_response.status_code == 200
    assert "private" in my_response.headers["Cache-Control"]
    assert "no-store" in my_response.headers["Cache-Control"]

    client.force_authenticate(None)
    with override_settings(ROOT_URLCONF="maru.venues.urls"):
        public_response = client.get(
            "/api/v1/public/organizations/"
            f"{scope.edition.organization_id}/editions/{scope.edition.id}/"
            "venue-schedule"
        )
    assert public_response.status_code == 200
    assert "private" not in public_response.headers.get("Cache-Control", "")


def test_accommodation_catalog_has_no_guest_identity_and_events_use_outbox() -> None:
    guest_like_fields = {"guest", "account", "registration", "email", "name"}
    field_names = {field.name for field in AccommodationRoomType._meta.fields}
    assert not (field_names & guest_like_fields)

    scope = _scope()
    _selected_space(scope)
    venue_events = DomainEvent.objects.filter(aggregate_type__startswith="venues.")
    assert venue_events.exists()
    assert (
        OutboxMessage.objects.filter(event__in=venue_events).count()
        == venue_events.count()
    )


def test_venue_authorization_functions_match_readiness_fingerprints() -> None:
    identities = (
        "maru_authorization_capability_min_scope(text)",
        "maru_validate_scoped_resource_binding()",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT required.identity,
                   procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_catalog.pg_get_function_result(procedure.oid)
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
               AND namespace.nspname = 'public'
              JOIN pg_catalog.pg_language AS language
                ON language.oid = procedure.prolang
             ORDER BY required.identity
            """,
            [list(identities)],
        )
        rows = cursor.fetchall()
    installed = {
        str(row[0]): _function_definition_fingerprint(tuple(row[1:])) for row in rows
    }
    assert installed == {
        identity: _FUNCTION_DEFINITION_SHA256[identity] for identity in identities
    }
