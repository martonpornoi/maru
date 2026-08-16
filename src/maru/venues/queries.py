"""Policy-scoped venue reads and minimized attendee schedule projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.queries import participations_for_account

from .authorization import resolve_edition_space_target
from .inputs import normalized_reason, normalized_source_channel
from .models import (
    EditionSpaceAvailabilityWindow,
    EditionSpaceSelection,
    VenueBooking,
    VenueLayoutVersion,
    VenueProperty,
)
from .services import (
    PROPERTY_VIEW_CAPABILITY,
    SPACE_VIEW_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    VenueAuthorizationDeniedError,
    VenueResourceUnavailableError,
)

MAX_PUBLIC_SCHEDULE_ITEMS = 2_000
MAX_PERSONAL_SCHEDULE_EDITIONS = 500
_ATTENDEE_PARTICIPATION_STATUSES = ("confirmed", "active", "completed")


@dataclass(frozen=True, slots=True)
class VenuePropertySummary:
    id: UUID
    slug: str
    kind: str
    legal_name: str
    provider_name: str
    public_name: str
    public_description: str
    internal_notes: str
    location_name: str
    postal_address: str
    country_code: str
    website_url: str
    public_contact: str
    contact_name: str
    contact_email: str
    contact_phone: str
    lifecycle: str
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class VenueWorkspaceSpace:
    id: UUID
    venue_selection_id: UUID
    venue_name: str
    local_name: str
    configuration_name: str
    seated_capacity: int
    standing_capacity: int
    table_capacity: int
    fire_capacity: int
    availability_version: int
    active_booking_count: int
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class VenueAvailabilityProjection:
    starts_at: datetime
    ends_at: datetime
    opening_restriction: str


@dataclass(frozen=True, slots=True)
class VenueBookingProjection:
    id: UUID
    kind: str
    external_reference: str
    internal_title: str
    public_title: str
    public_description: str
    capacity_mode: str
    expected_attendance: int
    setup_starts_at: datetime
    effective_starts_at: datetime
    effective_ends_at: datetime
    teardown_ends_at: datetime
    review_state: str
    publication_state: str
    lifecycle: str
    public_layout_reference: str
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class VenueSpaceSchedule:
    space: VenueWorkspaceSpace
    availability: tuple[VenueAvailabilityProjection, ...]
    bookings: tuple[VenueBookingProjection, ...]


@dataclass(frozen=True, slots=True)
class PublicVenueScheduleItem:
    booking_id: UUID
    space_selection_id: UUID
    venue_name: str
    space_name: str
    kind: str
    title: str
    description: str
    starts_at: datetime
    ends_at: datetime
    access_info: str
    layout_reference: str
    layout_title: str


def _active_account(actor: Account) -> None:
    if actor.pk is None or not actor.is_active:
        raise VenueAuthorizationDeniedError()


def _audit_restricted_read(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    capability_code: str,
    operation: str,
    target_type: str,
    target_id: UUID,
    decision_reason: str,
    obligations: frozenset[str],
    purpose: str,
    correlation_id: UUID | None,
    request_id: UUID | None,
    source_channel: str,
) -> None:
    evaluated_at = timezone.now()
    correlation_id = correlation_id or uuid4()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision_reason,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=normalized_source_channel(source_channel),
            obligations=tuple(sorted(obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": normalized_reason(purpose),
            },
            retention_class="venue-restricted",
        ),
        occurred_at=evaluated_at,
    )


def public_schedule_for_edition(
    *,
    organization_id: UUID,
    edition_id: UUID,
    starts_before: datetime | None = None,
    ends_after: datetime | None = None,
) -> tuple[PublicVenueScheduleItem, ...]:
    """Project only approved effective intervals and public-safe renditions."""

    if starts_before is not None and not timezone.is_aware(starts_before):
        raise ValueError("starts_before must be timezone-aware")
    if ends_after is not None and not timezone.is_aware(ends_after):
        raise ValueError("ends_after must be timezone-aware")
    bookings = VenueBooking.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        lifecycle=VenueBooking.Lifecycle.ACTIVE,
        review_state=VenueBooking.ReviewState.APPROVED,
        publication_state=VenueBooking.PublicationState.PUBLISHED,
        space_selection__lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
        space_selection__venue_selection__lifecycle="active",
        space_selection__venue_selection__property__lifecycle=(
            VenueProperty.Lifecycle.ACTIVE
        ),
    ).exclude(public_title="")
    if starts_before is not None:
        bookings = bookings.filter(effective_starts_at__lt=starts_before)
    if ends_after is not None:
        bookings = bookings.filter(effective_ends_at__gt=ends_after)
    bookings = bookings.select_related(
        "space_selection",
        "space_selection__venue_selection",
        "space_selection__venue_selection__property",
        "public_layout",
    ).order_by("effective_starts_at", "public_title", "id")[:MAX_PUBLIC_SCHEDULE_ITEMS]
    projected: list[PublicVenueScheduleItem] = []
    for booking in bookings:
        layout_reference = ""
        layout_title = ""
        layout = booking.public_layout
        if (
            layout is not None
            and layout.visibility == VenueLayoutVersion.Visibility.PUBLIC
            and layout.review_status == VenueLayoutVersion.ReviewStatus.APPROVED
            and layout.approved_reference
        ):
            layout_reference = layout.approved_reference
            layout_title = layout.title
        space = booking.space_selection
        venue = space.venue_selection
        projected.append(
            PublicVenueScheduleItem(
                booking_id=booking.id,
                space_selection_id=space.id,
                venue_name=venue.local_name,
                space_name=space.local_name,
                kind=booking.kind,
                title=booking.public_title,
                description=booking.public_description,
                starts_at=booking.effective_starts_at,
                ends_at=booking.effective_ends_at,
                access_info=space.public_access_info,
                layout_reference=layout_reference,
                layout_title=layout_title,
            )
        )
    return tuple(projected)


def authorize_my_maru_schedule_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> None:
    """Require one exact active attendee relationship without loading schedule data."""

    _active_account(actor)
    if (
        not participations_for_account(actor)
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status__in=_ATTENDEE_PARTICIPATION_STATUSES,
        )
        .exists()
    ):
        raise VenueAuthorizationDeniedError()


def my_maru_schedule_for_edition(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[PublicVenueScheduleItem, ...]:
    """Expose the same minimized schedule inside the authenticated attendee shell."""

    authorize_my_maru_schedule_scope(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    return public_schedule_for_edition(
        organization_id=organization_id,
        edition_id=edition_id,
    )


def my_maru_schedule_editions(*, actor: Account) -> tuple[EventEdition, ...]:
    """Discover editions with attendee-safe published schedule content."""

    _active_account(actor)
    attendee_edition_ids = (
        participations_for_account(actor)
        .filter(
            status__in=_ATTENDEE_PARTICIPATION_STATUSES,
        )
        .values_list("edition_id", flat=True)
    )
    scopes = tuple(
        VenueBooking.objects.filter(
            edition_id__in=attendee_edition_ids,
            lifecycle=VenueBooking.Lifecycle.ACTIVE,
            review_state=VenueBooking.ReviewState.APPROVED,
            publication_state=VenueBooking.PublicationState.PUBLISHED,
            space_selection__lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
            space_selection__venue_selection__lifecycle="active",
            space_selection__venue_selection__property__lifecycle=(
                VenueProperty.Lifecycle.ACTIVE
            ),
        )
        .exclude(public_title="")
        .values("organization_id", "edition_id")
        .annotate(schedule_starts_on=Max("edition__starts_on"))
        .order_by("-schedule_starts_on", "organization_id", "edition_id")[
            :MAX_PERSONAL_SCHEDULE_EDITIONS
        ]
    )
    edition_ids = tuple(cast(UUID, scope["edition_id"]) for scope in scopes)
    return tuple(
        EventEdition.objects.filter(id__in=edition_ids)
        .select_related("organization", "series")
        .order_by("-starts_on", "name", "id")
    )


@transaction.atomic
def list_venue_properties(
    *,
    actor: Account,
    organization_id: UUID,
    purpose: str = "venue_property_management",
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> tuple[VenuePropertySummary, ...]:
    _active_account(actor)
    target = resolve_organization_target(organization_id=organization_id)
    decision = decide(
        principal=actor,
        capability_code=PROPERTY_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise VenueAuthorizationDeniedError()
    projection = tuple(
        VenuePropertySummary(
            id=record.id,
            slug=record.slug,
            kind=record.kind,
            legal_name=record.legal_name,
            provider_name=record.provider_name,
            public_name=record.public_name,
            public_description=record.public_description,
            internal_notes=record.internal_notes,
            location_name=record.location_name,
            postal_address=record.postal_address,
            country_code=record.country_code,
            website_url=record.website_url,
            public_contact=record.public_contact,
            contact_name=record.contact_name,
            contact_email=record.contact_email,
            contact_phone=record.contact_phone,
            lifecycle=record.lifecycle,
            aggregate_version=record.aggregate_version,
        )
        for record in VenueProperty.objects.filter(
            organization_id=organization_id
        ).order_by("public_name", "id")
    )
    _audit_restricted_read(
        actor=actor,
        organization_id=organization_id,
        edition_id=None,
        capability_code=PROPERTY_VIEW_CAPABILITY,
        operation="venues.property_restricted_directory.read",
        target_type="organizations.organization",
        target_id=organization_id,
        decision_reason=decision.reason_code,
        obligations=decision.obligations,
        purpose=purpose,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    return projection


def list_venue_workspace(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[VenueWorkspaceSpace, ...]:
    _active_account(actor)
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=actor,
        capability_code=WORKSPACE_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise VenueAuthorizationDeniedError()
    rows = (
        EditionSpaceSelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
            venue_selection__lifecycle="active",
        )
        .select_related("venue_selection")
        .annotate(
            active_booking_count=Count(
                "bookings",
                filter=Q(bookings__lifecycle=VenueBooking.Lifecycle.ACTIVE),
            )
        )
        .order_by("venue_selection__local_name", "local_name", "id")
    )
    return tuple(
        VenueWorkspaceSpace(
            id=row.id,
            venue_selection_id=row.venue_selection_id,
            venue_name=row.venue_selection.local_name,
            local_name=row.local_name,
            configuration_name=row.configuration_name,
            seated_capacity=row.seated_capacity,
            standing_capacity=row.standing_capacity,
            table_capacity=row.table_capacity,
            fire_capacity=row.fire_capacity,
            availability_version=row.current_availability_version,
            active_booking_count=row.active_booking_count,
            aggregate_version=row.aggregate_version,
        )
        for row in rows
    )


@transaction.atomic
def load_space_schedule(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    purpose: str,
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueSpaceSchedule:
    _active_account(actor)
    target = resolve_edition_space_target(
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
    )
    decision = decide(
        principal=actor,
        capability_code=SPACE_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise VenueAuthorizationDeniedError()
    space = (
        EditionSpaceSelection.objects.filter(
            id=space_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("venue_selection")
        .annotate(
            active_booking_count=Count(
                "bookings",
                filter=Q(bookings__lifecycle=VenueBooking.Lifecycle.ACTIVE),
            )
        )
        .first()
    )
    if space is None:
        raise VenueResourceUnavailableError()
    availability = tuple(
        VenueAvailabilityProjection(
            starts_at=window.starts_at,
            ends_at=window.ends_at,
            opening_restriction=window.opening_restriction,
        )
        for window in EditionSpaceAvailabilityWindow.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection=space,
            availability_version=space.current_availability_version,
        ).order_by("starts_at", "id")
    )
    bookings = tuple(
        VenueBookingProjection(
            id=booking.id,
            kind=booking.kind,
            external_reference=booking.external_reference,
            internal_title=booking.internal_title,
            public_title=booking.public_title,
            public_description=booking.public_description,
            capacity_mode=booking.capacity_mode,
            expected_attendance=booking.expected_attendance,
            setup_starts_at=booking.setup_starts_at,
            effective_starts_at=booking.effective_starts_at,
            effective_ends_at=booking.effective_ends_at,
            teardown_ends_at=booking.teardown_ends_at,
            review_state=booking.review_state,
            publication_state=booking.publication_state,
            lifecycle=booking.lifecycle,
            public_layout_reference=(
                booking.public_layout.approved_reference
                if booking.public_layout is not None
                and booking.public_layout.review_status
                == VenueLayoutVersion.ReviewStatus.APPROVED
                else ""
            ),
            aggregate_version=booking.aggregate_version,
        )
        for booking in VenueBooking.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection=space,
        )
        .select_related("public_layout")
        .order_by("effective_starts_at", "id")
    )
    _audit_restricted_read(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=SPACE_VIEW_CAPABILITY,
        operation="venues.space_operational_schedule.read",
        target_type="venue.edition_space",
        target_id=space.id,
        decision_reason=decision.reason_code,
        obligations=decision.obligations,
        purpose=purpose,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    return VenueSpaceSchedule(
        space=VenueWorkspaceSpace(
            id=space.id,
            venue_selection_id=space.venue_selection_id,
            venue_name=space.venue_selection.local_name,
            local_name=space.local_name,
            configuration_name=space.configuration_name,
            seated_capacity=space.seated_capacity,
            standing_capacity=space.standing_capacity,
            table_capacity=space.table_capacity,
            fire_capacity=space.fire_capacity,
            availability_version=space.current_availability_version,
            active_booking_count=space.active_booking_count,
            aggregate_version=space.aggregate_version,
        ),
        availability=availability,
        bookings=bookings,
    )
