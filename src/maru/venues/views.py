"""Same-shell venue catalog, selection, schedule, and attendee journeys."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import TypedDict, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.db.models import F
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.venues.authorization import resolve_edition_space_target
from maru.venues.forms import (
    AccommodationInventoryForm,
    AccommodationRoomTypeForm,
    VenueAvailabilityForm,
    VenueBookingForm,
    VenueBookingStateForm,
    VenueCatalogPathForm,
    VenueCombinationForm,
    VenueEditionSelectionForm,
    VenueLayoutAddForm,
    VenueMediaAddForm,
    VenuePropertyCreateForm,
    VenuePropertyUpdateForm,
    VenueReviewForm,
    VenueSpaceSelectionForm,
)
from maru.venues.models import (
    AccommodationNightInventory,
    AccommodationRoomType,
    EditionSpaceSelection,
    EditionVenueSelection,
    VenueBooking,
    VenueLayoutVersion,
    VenueProperty,
    VenuePropertyMedia,
    VenueSpace,
    VenueSpaceCombination,
    VenueSpaceConfiguration,
)
from maru.venues.queries import (
    list_venue_properties,
    list_venue_workspace,
    load_space_schedule,
    my_maru_schedule_editions,
    my_maru_schedule_for_edition,
)
from maru.venues.services import (
    ACCOMMODATION_MANAGE_CAPABILITY,
    EDITION_SELECT_CAPABILITY,
    PROPERTY_MANAGE_CAPABILITY,
    SPACE_MANAGE_CAPABILITY,
    SPACE_PUBLISH_CAPABILITY,
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueBookingEnvelope,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCommandError,
    VenueIndependentApprovalError,
    VenuePropertyProfile,
    VenueResourceUnavailableError,
    VenueRetryConflictError,
    VenueSpaceCatalogInput,
    VenueStateConflictError,
    VenueVersionConflictError,
    add_venue_layout_version,
    add_venue_property_media,
    approve_venue_booking,
    approve_venue_layout_version,
    approve_venue_property_media,
    cancel_venue_booking,
    create_accommodation_room_type,
    create_venue_booking,
    create_venue_property,
    create_venue_space_catalog_path,
    create_venue_space_combination,
    publish_venue_booking,
    reschedule_venue_booking,
    select_space_for_edition,
    select_venue_for_edition,
    set_accommodation_night_inventory,
    set_edition_space_availability,
    update_venue_property,
    withdraw_venue_booking_publication,
)
from maru.workforce.models import Department

_PROPERTY_PROFILE_FIELDS = tuple(VenuePropertyProfile.__dataclass_fields__)
_PROPERTY_UPDATE_FIELDS = (
    "legal_name",
    "public_name",
    "provider_name",
    "public_description",
    "internal_notes",
    "location_name",
    "postal_address",
    "country_code",
    "website_url",
    "public_contact",
    "contact_name",
    "contact_email",
    "contact_phone",
    "lifecycle",
)


class _BookingCommandValues(TypedDict):
    kind: str
    external_reference: str
    internal_title: str
    public_title: str
    public_description: str
    capacity_mode: str
    expected_attendance: int
    envelope: VenueBookingEnvelope
    public_layout_id: UUID | None
    reason: str
    idempotency_key: UUID


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied("The venue workspace is unavailable.")
    return request.user


def _correlation_id(request: HttpRequest) -> UUID:
    return UUID(str(request.correlation_id))  # type: ignore[attr-defined]


def _edition_route(
    *, organization_slug: str, series_slug: str, edition_slug: str
) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            organization__slug=organization_slug,
            series__slug=series_slug,
            slug=edition_slug,
            series__organization_id=F("organization_id"),
        )
        .first()
    )
    if edition is None:
        raise Http404
    return edition


def _page_context(
    request: HttpRequest,
    *,
    edition: EventEdition | None = None,
    personal: bool,
    **values: object,
) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(values)
    context["has_permission"] = True
    context["maru_personal_surface"] = personal
    if edition is not None:
        context.update(
            organization=edition.organization,
            convention_series=edition.series,
            edition=edition,
        )
    return context


def _response(
    request: HttpRequest,
    template_name: str,
    context: dict[str, object],
    *,
    status: int = 200,
) -> HttpResponse:
    response = TemplateResponse(request, template_name, context, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _plain_error(message: str, *, status: int) -> HttpResponse:
    response = HttpResponse(message, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _strict_get(request: HttpRequest) -> HttpResponse | None:
    if request.GET:
        return _plain_error("Unsupported query parameters.", status=400)
    return None


def _allowed(
    *,
    actor: Account,
    capability_code: str,
    edition: EventEdition,
    space_selection_id: UUID | None = None,
) -> bool:
    if space_selection_id is not None:
        target = resolve_edition_space_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection_id=space_selection_id,
        )
    elif capability_code in {
        EDITION_SELECT_CAPABILITY,
        "venues.view_workspace",
    }:
        target = resolve_edition_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    else:
        target = resolve_organization_target(
            organization_id=edition.organization_id,
        )
    return bool(
        target is not None
        and decide(
            principal=actor,
            capability_code=capability_code,
            resource=target,
        ).allowed
    )


def _require_allowed(
    *,
    actor: Account,
    capability_code: str,
    edition: EventEdition,
    space_selection_id: UUID | None = None,
) -> None:
    if not _allowed(
        actor=actor,
        capability_code=capability_code,
        edition=edition,
        space_selection_id=space_selection_id,
    ):
        raise PermissionDenied("The venue workflow is unavailable.")


def _command_error(form: forms.Form, error: Exception) -> int:  # noqa: PLR0912
    if isinstance(error, VenueAuthorizationDeniedError):
        raise PermissionDenied("The venue workflow is unavailable.") from error
    if isinstance(error, VenueResourceUnavailableError):
        raise Http404 from error
    if isinstance(error, ValidationError):
        if hasattr(error, "message_dict"):
            for field_name, field_errors in error.message_dict.items():
                target = field_name if field_name in form.fields else None
                for field_error in field_errors:
                    form.add_error(target, field_error)
        else:
            for field_error in error.messages:
                form.add_error(None, field_error)
        return 400
    if isinstance(error, VenueIndependentApprovalError):
        form.add_error(
            None,
            "A different authorized person must perform this independent step.",
        )
        return 409
    if isinstance(error, VenueCapacityConflictError):
        form.add_error(None, "Expected attendance exceeds the selected capacity.")
        return 409
    if isinstance(error, VenueAvailabilityConflictError):
        form.add_error(None, "The complete booking envelope is outside availability.")
        return 409
    if isinstance(error, VenueBookingOverlapError):
        form.add_error(None, "The physical room is occupied during this envelope.")
        return 409
    if isinstance(
        error,
        (
            VenueVersionConflictError,
            VenueRetryConflictError,
            VenueStateConflictError,
            VenueCommandError,
        ),
    ):
        form.add_error(None, "Venue state changed. Reload before trying again.")
        return 409
    raise error


def _property_initial(record: VenueProperty) -> dict[str, object]:
    return {
        "retry_key": str(uuid4()),
        "expected_version": record.aggregate_version,
        **{
            field_name: getattr(record, field_name)
            for field_name in _PROPERTY_UPDATE_FIELDS
        },
    }


def _catalog_choices(
    *, edition: EventEdition
) -> tuple[
    tuple[VenueProperty, ...],
    tuple[EditionVenueSelection, ...],
    tuple[VenueSpace, ...],
    tuple[VenueSpaceCombination, ...],
    tuple[VenueSpaceConfiguration, ...],
    tuple[Department, ...],
]:
    properties = tuple(
        VenueProperty.objects.filter(
            organization_id=edition.organization_id,
            lifecycle=VenueProperty.Lifecycle.ACTIVE,
        ).order_by("public_name", "id")
    )
    venue_selections = tuple(
        EditionVenueSelection.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            lifecycle=EditionVenueSelection.Lifecycle.ACTIVE,
        )
        .select_related("property")
        .order_by("local_name", "id")
    )
    selected_property_ids = tuple(item.property_id for item in venue_selections)
    spaces = tuple(
        VenueSpace.objects.filter(
            organization_id=edition.organization_id,
            property_id__in=selected_property_ids,
            is_active=True,
        ).order_by("property__public_name", "name", "id")
    )
    combinations = tuple(
        VenueSpaceCombination.objects.filter(
            organization_id=edition.organization_id,
            property_id__in=selected_property_ids,
            is_active=True,
        ).order_by("property__public_name", "name", "id")
    )
    configurations = tuple(
        VenueSpaceConfiguration.objects.filter(
            organization_id=edition.organization_id,
            space__property_id__in=selected_property_ids,
            lifecycle=VenueSpaceConfiguration.Lifecycle.ACTIVE,
        )
        .select_related("space")
        .order_by("space__name", "name", "version", "id")
    )
    departments = tuple(
        Department.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            retired_at__isnull=True,
        ).order_by("name", "id")
    )
    return (
        properties,
        venue_selections,
        spaces,
        combinations,
        configurations,
        departments,
    )


def _workspace_response(
    request: HttpRequest,
    *,
    actor: Account,
    edition: EventEdition,
    active_form_name: str = "",
    active_form: forms.Form | None = None,
    status: int = 200,
) -> HttpResponse:
    properties = list_venue_properties(
        actor=actor,
        organization_id=edition.organization_id,
        purpose="venue_property_workspace",
        correlation_id=_correlation_id(request),
        source_channel="browser",
    )
    spaces_projection = list_venue_workspace(
        actor=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    (
        property_records,
        venue_selections,
        source_spaces,
        combinations,
        configurations,
        departments,
    ) = _catalog_choices(edition=edition)
    can_manage_properties = _allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    can_select = _allowed(
        actor=actor,
        capability_code=EDITION_SELECT_CAPABILITY,
        edition=edition,
    )
    forms_context: dict[str, forms.Form] = {}
    if can_select:
        forms_context["venue_selection_form"] = VenueEditionSelectionForm(
            initial={"retry_key": str(uuid4())},
            properties=property_records,
            departments=departments,
        )
        forms_context["space_selection_form"] = VenueSpaceSelectionForm(
            initial={"retry_key": str(uuid4())},
            venue_selections=venue_selections,
            spaces=source_spaces,
            combinations=combinations,
            configurations=configurations,
        )
    if active_form_name and active_form is not None:
        forms_context[active_form_name] = active_form
    return _response(
        request,
        "venues/workspace.html",
        _page_context(
            request,
            edition=edition,
            personal=False,
            title="Venues and spaces",
            properties=tuple(asdict(record) for record in properties),
            spaces=tuple(asdict(space) for space in spaces_projection),
            venue_selections=venue_selections,
            can_manage_properties=can_manage_properties,
            can_select=can_select,
            **forms_context,
        ),
        status=status,
    )


def _property_record(
    *,
    request: HttpRequest,
    actor: Account,
    edition: EventEdition,
    property_id: UUID,
) -> VenueProperty:
    visible = list_venue_properties(
        actor=actor,
        organization_id=edition.organization_id,
        purpose="venue_property_detail",
        correlation_id=_correlation_id(request),
        source_channel="browser",
    )
    if property_id not in {record.id for record in visible}:
        raise Http404
    record = (
        VenueProperty.objects.filter(
            id=property_id,
            organization_id=edition.organization_id,
        )
        .select_related("created_by", "last_modified_by")
        .first()
    )
    if record is None:
        raise Http404
    return record


def _property_response(
    request: HttpRequest,
    *,
    actor: Account,
    edition: EventEdition,
    property_id: UUID,
    active_form_name: str = "",
    active_form: forms.Form | None = None,
    active_object_id: UUID | None = None,
    status: int = 200,
) -> HttpResponse:
    record = _property_record(
        request=request,
        actor=actor,
        edition=edition,
        property_id=property_id,
    )
    spaces = tuple(
        VenueSpace.objects.filter(
            organization_id=edition.organization_id,
            property=record,
        )
        .select_related("site", "building")
        .prefetch_related("configurations")
        .order_by("site__name", "building__name", "name", "id")
    )
    combinations = tuple(
        VenueSpaceCombination.objects.filter(
            organization_id=edition.organization_id,
            property=record,
        )
        .prefetch_related("members__space")
        .order_by("name", "id")
    )
    media = tuple(
        VenuePropertyMedia.objects.filter(
            organization_id=edition.organization_id,
            property=record,
        )
        .select_related("submitted_by", "reviewed_by")
        .order_by("kind", "created_at", "id")
    )
    layouts = tuple(
        VenueLayoutVersion.objects.filter(
            organization_id=edition.organization_id,
            space__property=record,
        )
        .select_related("space", "submitted_by", "reviewed_by")
        .order_by("space__name", "layout_code", "version", "id")
    )
    room_types = tuple(
        AccommodationRoomType.objects.filter(
            organization_id=edition.organization_id,
            property=record,
        ).order_by("public_name", "id")
    )
    inventories = tuple(
        AccommodationNightInventory.objects.filter(
            organization_id=edition.organization_id,
            room_type__property=record,
        )
        .select_related("room_type")
        .order_by("room_type__public_name", "night", "id")
    )
    can_manage = _allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    can_manage_accommodation = _allowed(
        actor=actor,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        edition=edition,
    )
    forms_context: dict[str, object] = {}
    if can_manage:
        forms_context.update(
            property_form=VenuePropertyUpdateForm(initial=_property_initial(record)),
            catalog_form=VenueCatalogPathForm(initial={"retry_key": str(uuid4())}),
            combination_form=VenueCombinationForm(
                initial={"retry_key": str(uuid4())},
                spaces=spaces,
            ),
            media_form=VenueMediaAddForm(
                initial={"retry_key": str(uuid4())},
                edition_time_zone=edition.time_zone,
            ),
            layout_form=VenueLayoutAddForm(
                initial={"retry_key": str(uuid4())},
                spaces=spaces,
            ),
        )
    if can_manage_accommodation:
        forms_context.update(
            room_type_form=AccommodationRoomTypeForm(
                initial={"retry_key": str(uuid4())}
            ),
            inventory_form=AccommodationInventoryForm(
                initial={"retry_key": str(uuid4())},
                room_types=room_types,
                edition_time_zone=edition.time_zone,
            ),
        )
    media_rows = []
    for media_item in media:
        review_form: forms.Form | None = None
        if (
            can_manage
            and media_item.review_status == VenuePropertyMedia.ReviewStatus.PENDING
        ):
            review_form = VenueReviewForm(
                initial={
                    "retry_key": str(uuid4()),
                    "expected_version": media_item.aggregate_version,
                }
            )
        if (
            active_form_name == "media_review_form"
            and active_object_id == media_item.id
        ):
            review_form = active_form
        media_rows.append({"record": media_item, "review_form": review_form})
    layout_rows = []
    for layout_item in layouts:
        review_form = None
        if (
            can_manage
            and layout_item.review_status == VenueLayoutVersion.ReviewStatus.PENDING
        ):
            review_form = VenueReviewForm(
                initial={
                    "retry_key": str(uuid4()),
                    "expected_version": layout_item.aggregate_version,
                }
            )
        if (
            active_form_name == "layout_review_form"
            and active_object_id == layout_item.id
        ):
            review_form = active_form
        layout_rows.append({"record": layout_item, "review_form": review_form})
    inventory_rows = []
    for inventory_item in inventories:
        inventory_form: forms.Form | None = None
        if can_manage_accommodation:
            inventory_form = AccommodationInventoryForm(
                initial={
                    "retry_key": str(uuid4()),
                    "room_type_id": str(inventory_item.room_type_id),
                    "night": inventory_item.night,
                    "room_capacity": inventory_item.room_capacity,
                    "release_at": inventory_item.release_at,
                    "provider_reference": inventory_item.provider_reference,
                    "expected_version": inventory_item.aggregate_version,
                },
                room_types=room_types,
                edition_time_zone=edition.time_zone,
            )
        inventory_rows.append({"record": inventory_item, "form": inventory_form})
    if (
        active_form_name
        and active_form is not None
        and active_form_name
        not in {
            "media_review_form",
            "layout_review_form",
        }
    ):
        forms_context[active_form_name] = active_form
    return _response(
        request,
        "venues/property_detail.html",
        _page_context(
            request,
            edition=edition,
            personal=False,
            title=record.public_name,
            property=record,
            spaces=spaces,
            combinations=combinations,
            media_rows=media_rows,
            layout_rows=layout_rows,
            room_types=room_types,
            inventory_rows=inventory_rows,
            can_manage=can_manage,
            can_manage_accommodation=can_manage_accommodation,
            **forms_context,
        ),
        status=status,
    )


def _approved_layouts(space: EditionSpaceSelection) -> tuple[VenueLayoutVersion, ...]:
    member_ids = space.physical_members.values_list("source_space_id", flat=True)
    return tuple(
        VenueLayoutVersion.objects.filter(
            organization_id=space.organization_id,
            space_id__in=member_ids,
            visibility=VenueLayoutVersion.Visibility.PUBLIC,
            review_status=VenueLayoutVersion.ReviewStatus.APPROVED,
        )
        .exclude(approved_reference="")
        .order_by("title", "version", "id")
    )


def _local_minute(value: datetime, *, edition: EventEdition) -> str:
    return value.astimezone(ZoneInfo(edition.time_zone)).strftime("%Y-%m-%dT%H:%M")


def _booking_initial(booking: VenueBooking) -> dict[str, object]:
    return {
        "retry_key": str(uuid4()),
        "expected_version": booking.aggregate_version,
        "kind": booking.kind,
        "external_reference": booking.external_reference,
        "internal_title": booking.internal_title,
        "public_title": booking.public_title,
        "public_description": booking.public_description,
        "capacity_mode": booking.capacity_mode,
        "expected_attendance": booking.expected_attendance,
        "setup_starts_at": booking.setup_starts_at,
        "effective_starts_at": booking.effective_starts_at,
        "effective_ends_at": booking.effective_ends_at,
        "teardown_ends_at": booking.teardown_ends_at,
        "public_layout_id": str(booking.public_layout_id or ""),
    }


def _space_response(
    request: HttpRequest,
    *,
    actor: Account,
    edition: EventEdition,
    space_selection_id: UUID,
    active_form_name: str = "",
    active_form: forms.Form | None = None,
    active_booking_id: UUID | None = None,
    status: int = 200,
) -> HttpResponse:
    schedule = load_space_schedule(
        actor=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        space_selection_id=space_selection_id,
        purpose="venue_space_schedule_page",
        correlation_id=_correlation_id(request),
        source_channel="browser",
    )
    space = (
        EditionSpaceSelection.objects.filter(
            id=space_selection_id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        .select_related("venue_selection")
        .prefetch_related("physical_members")
        .first()
    )
    if space is None:
        raise Http404
    can_manage = _allowed(
        actor=actor,
        capability_code=SPACE_MANAGE_CAPABILITY,
        edition=edition,
        space_selection_id=space.id,
    )
    can_publish = _allowed(
        actor=actor,
        capability_code=SPACE_PUBLISH_CAPABILITY,
        edition=edition,
        space_selection_id=space.id,
    )
    layouts = _approved_layouts(space)
    availability_text = "\n".join(
        "|".join(
            (
                _local_minute(item.starts_at, edition=edition),
                _local_minute(item.ends_at, edition=edition),
                item.opening_restriction,
            )
        ).rstrip("|")
        for item in schedule.availability
    )
    availability_form: VenueAvailabilityForm | None = None
    booking_form: VenueBookingForm | None = None
    if can_manage:
        availability_form = VenueAvailabilityForm(
            initial={
                "retry_key": str(uuid4()),
                "expected_version": space.aggregate_version,
                "intervals_text": availability_text,
            },
            edition_time_zone=edition.time_zone,
        )
        booking_form = VenueBookingForm(
            initial={"retry_key": str(uuid4())},
            layouts=layouts,
            edition_time_zone=edition.time_zone,
        )
    if active_form_name == "availability_form":
        availability_form = cast(VenueAvailabilityForm, active_form)
    if active_form_name == "booking_form":
        booking_form = cast(VenueBookingForm, active_form)
    bookings = tuple(
        VenueBooking.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection=space,
        )
        .select_related("created_by", "last_modified_by", "approved_by", "published_by")
        .prefetch_related("history_entries")
        .order_by("effective_starts_at", "id")
    )
    booking_rows = []
    for booking in bookings:
        reschedule_form = None
        state_forms: dict[str, forms.Form] = {}
        if can_manage and booking.lifecycle == VenueBooking.Lifecycle.ACTIVE:
            reschedule_form = VenueBookingForm(
                initial=_booking_initial(booking),
                layouts=layouts,
                edition_time_zone=edition.time_zone,
            )
            for action in ("approve", "cancel"):
                state_forms[action] = VenueBookingStateForm(
                    initial={
                        "retry_key": str(uuid4()),
                        "expected_version": booking.aggregate_version,
                    }
                )
        if can_publish and booking.lifecycle == VenueBooking.Lifecycle.ACTIVE:
            for action in ("publish", "withdraw"):
                state_forms[action] = VenueBookingStateForm(
                    initial={
                        "retry_key": str(uuid4()),
                        "expected_version": booking.aggregate_version,
                    }
                )
        if active_booking_id == booking.id and active_form is not None:
            if active_form_name == "reschedule_form":
                reschedule_form = cast(VenueBookingForm, active_form)
            elif active_form_name.startswith("state_form_"):
                state_forms[active_form_name.removeprefix("state_form_")] = active_form
        booking_rows.append(
            {
                "record": booking,
                "reschedule_form": reschedule_form,
                "state_forms": state_forms,
            }
        )
    return _response(
        request,
        "venues/space_schedule.html",
        _page_context(
            request,
            edition=edition,
            personal=False,
            title=schedule.space.local_name,
            schedule=schedule,
            space_selection=space,
            availability_form=availability_form,
            booking_form=booking_form,
            booking_rows=booking_rows,
            can_manage=can_manage,
            can_publish=can_publish,
        ),
        status=status,
    )


def _route_edition(
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> EventEdition:
    return _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


@login_required(login_url="staff-login")
@require_GET
def venue_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        actor = _actor(request)
        edition = _route_edition(organization_slug, series_slug, edition_slug)
        return _workspace_response(request, actor=actor, edition=edition)
    except VenueAuthorizationDeniedError as error:
        raise PermissionDenied("The venue workspace is unavailable.") from error
    except DatabaseError:
        return _plain_error("Venue records are temporarily unavailable.", status=503)


@login_required(login_url="staff-login")
@require_GET
def venue_property_create_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenuePropertyCreateForm(initial={"retry_key": str(uuid4())})
    return _response(
        request,
        "venues/property_create.html",
        _page_context(
            request,
            edition=edition,
            personal=False,
            title="Register venue property",
            form=form,
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def venue_property_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenuePropertyCreateForm(request.POST)
    status = 400
    if form.is_valid():
        profile = VenuePropertyProfile(
            **{
                field_name: str(form.cleaned_data.get(field_name, ""))
                for field_name in _PROPERTY_PROFILE_FIELDS
            }
        )
        try:
            result = create_venue_property(
                actor=actor,
                organization_id=edition.organization_id,
                slug=str(form.cleaned_data["slug"]),
                profile=profile,
                reason=str(form.cleaned_data["reason"]),
                idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
                correlation_id=_correlation_id(request),
                source_channel="browser",
            )
        except Exception as error:  # noqa: BLE001
            status = _command_error(form, error)
        else:
            messages.success(request, "The reusable venue property was created.")
            return redirect(
                "venue-property-detail-page",
                organization_slug,
                series_slug,
                edition_slug,
                result.object_id,
            )
    return _response(
        request,
        "venues/property_create.html",
        _page_context(
            request,
            edition=edition,
            personal=False,
            title="Register venue property",
            form=form,
        ),
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def venue_property_detail_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        return _property_response(
            request,
            actor=_actor(request),
            edition=_route_edition(organization_slug, series_slug, edition_slug),
            property_id=property_id,
        )
    except VenueAuthorizationDeniedError as error:
        raise PermissionDenied("The venue property is unavailable.") from error
    except DatabaseError:
        return _plain_error(
            "The venue property is temporarily unavailable.",
            status=503,
        )


def _property_action_response(
    request: HttpRequest,
    *,
    edition: EventEdition,
    property_id: UUID,
    form_name: str,
    form: forms.Form,
    command: Callable[[], object],
    success_message: str,
    active_object_id: UUID | None = None,
) -> HttpResponse:
    status = 400
    if form.is_valid():
        try:
            command()
        except Exception as error:  # noqa: BLE001
            status = _command_error(form, error)
        else:
            messages.success(request, success_message)
            return redirect(
                "venue-property-detail-page",
                edition.organization.slug,
                edition.series.slug,
                edition.slug,
                property_id,
            )
    return _property_response(
        request,
        actor=_actor(request),
        edition=edition,
        property_id=property_id,
        active_form_name=form_name,
        active_form=form,
        active_object_id=active_object_id,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_property_update(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenuePropertyUpdateForm(request.POST)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="property_form",
        form=form,
        command=lambda: update_venue_property(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            changes=form.changes,
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The venue property profile was updated.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_catalog_path_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenueCatalogPathForm(request.POST)

    def command() -> object:
        values = form.cleaned_data
        catalog = VenueSpaceCatalogInput(
            site_code=str(values["site_code"]),
            site_name=str(values["site_name"]),
            building_code=str(values["building_code"]),
            building_name=str(values["building_name"]),
            space_code=str(values["space_code"]),
            space_name=str(values["space_name"]),
            space_kind=str(values["space_kind"]),
            configuration_code=str(values["configuration_code"]),
            configuration_name=str(values["configuration_name"]),
            seated_capacity=cast(int, values["seated_capacity"]),
            standing_capacity=cast(int, values["standing_capacity"]),
            table_capacity=cast(int, values["table_capacity"]),
            fire_capacity=cast(int, values["fire_capacity"]),
            public_description=str(values.get("public_description", "")),
            accessibility_features=str(values.get("accessibility_features", "")),
            known_barriers=str(values.get("known_barriers", "")),
            equipment_facts=str(values.get("equipment_facts", "")),
        )
        return create_venue_space_catalog_path(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            catalog=catalog,
            reason=str(values["reason"]),
            idempotency_key=cast(UUID, values["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        )

    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="catalog_form",
        form=form,
        command=command,
        success_message="The site, building, space, and configuration were created.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_combination_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    spaces = VenueSpace.objects.filter(
        organization_id=edition.organization_id,
        property_id=property_id,
        is_active=True,
    )
    form = VenueCombinationForm(request.POST, spaces=spaces)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="combination_form",
        form=form,
        command=lambda: create_venue_space_combination(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            code=str(form.cleaned_data["code"]),
            name=str(form.cleaned_data["name"]),
            member_space_ids=cast(
                tuple[UUID, ...],
                form.cleaned_data["member_space_ids"],
            ),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The physical-space combination was created.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_media_add(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenueMediaAddForm(request.POST, edition_time_zone=edition.time_zone)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="media_form",
        form=form,
        command=lambda: add_venue_property_media(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            kind=str(form.cleaned_data["kind"]),
            source_reference=str(form.cleaned_data["source_reference"]),
            owner_name=str(form.cleaned_data["owner_name"]),
            license_basis=str(form.cleaned_data["license_basis"]),
            usage_scope=str(form.cleaned_data["usage_scope"]),
            attribution=str(form.cleaned_data.get("attribution", "")),
            expires_at=cast(datetime | None, form.cleaned_data.get("expires_at")),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The venue media reference was submitted for review.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_media_approve(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
    media_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenueReviewForm(request.POST)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="media_review_form",
        form=form,
        command=lambda: approve_venue_property_media(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            media_id=media_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            public_reference=str(form.cleaned_data.get("public_reference", "")),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The independent media review was recorded.",
        active_object_id=media_id,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_layout_add(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    spaces = VenueSpace.objects.filter(
        organization_id=edition.organization_id,
        property_id=property_id,
        is_active=True,
    )
    form = VenueLayoutAddForm(request.POST, spaces=spaces)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="layout_form",
        form=form,
        command=lambda: add_venue_layout_version(
            actor=actor,
            organization_id=edition.organization_id,
            space_id=cast(UUID, form.cleaned_data["space_id"]),
            layout_code=str(form.cleaned_data["layout_code"]),
            version=cast(int, form.cleaned_data["version"]),
            title=str(form.cleaned_data["title"]),
            visibility=str(form.cleaned_data["visibility"]),
            source_reference=str(form.cleaned_data["source_reference"]),
            checksum_sha256=str(form.cleaned_data["checksum_sha256"]),
            notes=str(form.cleaned_data.get("notes", "")),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The layout version was submitted for review.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_layout_approve(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
    layout_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = VenueReviewForm(request.POST)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="layout_review_form",
        form=form,
        command=lambda: approve_venue_layout_version(
            actor=actor,
            organization_id=edition.organization_id,
            layout_id=layout_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            approved_reference=str(form.cleaned_data.get("public_reference", "")),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The independent layout review was recorded.",
        active_object_id=layout_id,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_room_type_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        edition=edition,
    )
    form = AccommodationRoomTypeForm(request.POST)
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="room_type_form",
        form=form,
        command=lambda: create_accommodation_room_type(
            actor=actor,
            organization_id=edition.organization_id,
            property_id=property_id,
            code=str(form.cleaned_data["code"]),
            public_name=str(form.cleaned_data["public_name"]),
            description=str(form.cleaned_data.get("description", "")),
            accessible_features=str(form.cleaned_data.get("accessible_features", "")),
            minimum_occupants=cast(int, form.cleaned_data["minimum_occupants"]),
            maximum_occupants=cast(int, form.cleaned_data["maximum_occupants"]),
            provider_reference=str(form.cleaned_data.get("provider_reference", "")),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The accommodation room type was created.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_inventory_set(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    property_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        edition=edition,
    )
    room_types = AccommodationRoomType.objects.filter(
        organization_id=edition.organization_id,
        property_id=property_id,
        is_active=True,
    )
    form = AccommodationInventoryForm(
        request.POST,
        room_types=room_types,
        edition_time_zone=edition.time_zone,
    )
    return _property_action_response(
        request,
        edition=edition,
        property_id=property_id,
        form_name="inventory_form",
        form=form,
        command=lambda: set_accommodation_night_inventory(
            actor=actor,
            organization_id=edition.organization_id,
            room_type_id=cast(UUID, form.cleaned_data["room_type_id"]),
            night=form.cleaned_data["night"],
            room_capacity=cast(int, form.cleaned_data["room_capacity"]),
            release_at=form.cleaned_data["release_at"],
            provider_reference=str(form.cleaned_data.get("provider_reference", "")),
            expected_version=cast(
                int | None,
                form.cleaned_data.get("expected_version"),
            ),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The room-night inventory version was recorded.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_edition_select(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=EDITION_SELECT_CAPABILITY,
        edition=edition,
    )
    properties, _selections, _spaces, _combinations, _configs, departments = (
        _catalog_choices(edition=edition)
    )
    form = VenueEditionSelectionForm(
        request.POST,
        properties=properties,
        departments=departments,
    )
    status = 400
    if form.is_valid():
        try:
            select_venue_for_edition(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                property_id=cast(UUID, form.cleaned_data["property_id"]),
                responsible_department_id=cast(
                    UUID,
                    form.cleaned_data["responsible_department_id"],
                ),
                local_name=str(form.cleaned_data["local_name"]),
                public_description_override=str(
                    form.cleaned_data.get("public_description_override", "")
                ),
                public_contact_override=str(
                    form.cleaned_data.get("public_contact_override", "")
                ),
                opening_restrictions=str(
                    form.cleaned_data.get("opening_restrictions", "")
                ),
                reason=str(form.cleaned_data["reason"]),
                idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
                correlation_id=_correlation_id(request),
                source_channel="browser",
            )
        except Exception as error:  # noqa: BLE001
            status = _command_error(form, error)
        else:
            messages.success(request, "The property was selected for this edition.")
            return redirect(
                "venue-workspace",
                organization_slug,
                series_slug,
                edition_slug,
            )
    return _workspace_response(
        request,
        actor=actor,
        edition=edition,
        active_form_name="venue_selection_form",
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_space_select(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=EDITION_SELECT_CAPABILITY,
        edition=edition,
    )
    properties, selections, spaces, combinations, configurations, _departments = (
        _catalog_choices(edition=edition)
    )
    del properties
    form = VenueSpaceSelectionForm(
        request.POST,
        venue_selections=selections,
        spaces=spaces,
        combinations=combinations,
        configurations=configurations,
    )
    status = 400
    if form.is_valid():
        try:
            select_space_for_edition(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                venue_selection_id=cast(
                    UUID,
                    form.cleaned_data["venue_selection_id"],
                ),
                source_space_id=cast(
                    UUID | None,
                    form.cleaned_data.get("source_space_id"),
                ),
                source_combination_id=cast(
                    UUID | None,
                    form.cleaned_data.get("source_combination_id"),
                ),
                selected_configuration_id=cast(
                    UUID | None,
                    form.cleaned_data.get("selected_configuration_id"),
                ),
                local_name=str(form.cleaned_data["local_name"]),
                capacity=form.capacity,
                public_access_info=str(form.cleaned_data.get("public_access_info", "")),
                opening_restrictions=str(
                    form.cleaned_data.get("opening_restrictions", "")
                ),
                reason=str(form.cleaned_data["reason"]),
                idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
                correlation_id=_correlation_id(request),
                source_channel="browser",
            )
        except Exception as error:  # noqa: BLE001
            status = _command_error(form, error)
        else:
            messages.success(
                request,
                "The physical space was selected for this edition.",
            )
            return redirect(
                "venue-workspace",
                organization_slug,
                series_slug,
                edition_slug,
            )
    return _workspace_response(
        request,
        actor=actor,
        edition=edition,
        active_form_name="space_selection_form",
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def venue_space_schedule_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    space_selection_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        return _space_response(
            request,
            actor=_actor(request),
            edition=_route_edition(organization_slug, series_slug, edition_slug),
            space_selection_id=space_selection_id,
        )
    except VenueAuthorizationDeniedError as error:
        raise PermissionDenied("The venue schedule is unavailable.") from error
    except VenueResourceUnavailableError as error:
        raise Http404 from error
    except DatabaseError:
        return _plain_error("Venue schedule is temporarily unavailable.", status=503)


def _space_action_response(
    request: HttpRequest,
    *,
    actor: Account,
    edition: EventEdition,
    space_selection_id: UUID,
    form_name: str,
    form: forms.Form,
    command: Callable[[], object],
    success_message: str,
    active_booking_id: UUID | None = None,
) -> HttpResponse:
    status = 400
    if form.is_valid():
        try:
            command()
        except Exception as error:  # noqa: BLE001
            status = _command_error(form, error)
        else:
            messages.success(request, success_message)
            return redirect(
                "venue-space-schedule-page",
                edition.organization.slug,
                edition.series.slug,
                edition.slug,
                space_selection_id,
            )
    return _space_response(
        request,
        actor=actor,
        edition=edition,
        space_selection_id=space_selection_id,
        active_form_name=form_name,
        active_form=form,
        active_booking_id=active_booking_id,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_availability_set(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    space_selection_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=SPACE_MANAGE_CAPABILITY,
        edition=edition,
        space_selection_id=space_selection_id,
    )
    form = VenueAvailabilityForm(
        request.POST,
        edition_time_zone=edition.time_zone,
    )
    return _space_action_response(
        request,
        actor=actor,
        edition=edition,
        space_selection_id=space_selection_id,
        form_name="availability_form",
        form=form,
        command=lambda: set_edition_space_availability(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection_id=space_selection_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            intervals=form.intervals,
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="Hard availability was replaced with a new version.",
    )


def _layouts_for_booking(
    *, edition: EventEdition, space_selection_id: UUID
) -> tuple[VenueLayoutVersion, ...]:
    space = EditionSpaceSelection.objects.filter(
        id=space_selection_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    ).first()
    if space is None:
        raise Http404
    return _approved_layouts(space)


def _booking_command_values(form: VenueBookingForm) -> _BookingCommandValues:
    return {
        "kind": str(form.cleaned_data["kind"]),
        "external_reference": str(form.cleaned_data.get("external_reference", "")),
        "internal_title": str(form.cleaned_data["internal_title"]),
        "public_title": str(form.cleaned_data.get("public_title", "")),
        "public_description": str(form.cleaned_data.get("public_description", "")),
        "capacity_mode": str(form.cleaned_data["capacity_mode"]),
        "expected_attendance": cast(int, form.cleaned_data["expected_attendance"]),
        "envelope": form.envelope,
        "public_layout_id": cast(
            UUID | None,
            form.cleaned_data.get("public_layout_id"),
        ),
        "reason": str(form.cleaned_data["reason"]),
        "idempotency_key": cast(UUID, form.cleaned_data["retry_key"]),
    }


@login_required(login_url="staff-login")
@require_POST
def venue_booking_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    space_selection_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=SPACE_MANAGE_CAPABILITY,
        edition=edition,
        space_selection_id=space_selection_id,
    )
    form = VenueBookingForm(
        request.POST,
        layouts=_layouts_for_booking(
            edition=edition,
            space_selection_id=space_selection_id,
        ),
        edition_time_zone=edition.time_zone,
    )
    return _space_action_response(
        request,
        actor=actor,
        edition=edition,
        space_selection_id=space_selection_id,
        form_name="booking_form",
        form=form,
        command=lambda: create_venue_booking(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection_id=space_selection_id,
            correlation_id=_correlation_id(request),
            source_channel="browser",
            **_booking_command_values(form),
        ),
        success_message="The operational booking was created as a draft.",
    )


@login_required(login_url="staff-login")
@require_POST
def venue_booking_reschedule(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    space_selection_id: UUID,
    booking_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    _require_allowed(
        actor=actor,
        capability_code=SPACE_MANAGE_CAPABILITY,
        edition=edition,
        space_selection_id=space_selection_id,
    )
    form = VenueBookingForm(
        request.POST,
        layouts=_layouts_for_booking(
            edition=edition,
            space_selection_id=space_selection_id,
        ),
        edition_time_zone=edition.time_zone,
    )
    return _space_action_response(
        request,
        actor=actor,
        edition=edition,
        space_selection_id=space_selection_id,
        form_name="reschedule_form",
        form=form,
        command=lambda: reschedule_venue_booking(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection_id=space_selection_id,
            booking_id=booking_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
            **_booking_command_values(form),
        ),
        success_message="The booking envelope was rescheduled for fresh review.",
        active_booking_id=booking_id,
    )


@login_required(login_url="staff-login")
@require_POST
def venue_booking_command(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    space_selection_id: UUID,
    booking_id: UUID,
    action: str,
) -> HttpResponse:
    commands = {
        "approve": approve_venue_booking,
        "publish": publish_venue_booking,
        "withdraw": withdraw_venue_booking_publication,
        "cancel": cancel_venue_booking,
    }
    command = commands.get(action)
    if command is None:
        raise Http404
    actor = _actor(request)
    edition = _route_edition(organization_slug, series_slug, edition_slug)
    capability_code = (
        SPACE_PUBLISH_CAPABILITY
        if action in {"publish", "withdraw"}
        else SPACE_MANAGE_CAPABILITY
    )
    _require_allowed(
        actor=actor,
        capability_code=capability_code,
        edition=edition,
        space_selection_id=space_selection_id,
    )
    form = VenueBookingStateForm(request.POST)
    return _space_action_response(
        request,
        actor=actor,
        edition=edition,
        space_selection_id=space_selection_id,
        form_name=f"state_form_{action}",
        form=form,
        command=lambda: command(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            space_selection_id=space_selection_id,
            booking_id=booking_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message=f"The booking {action} action was recorded.",
        active_booking_id=booking_id,
    )


@login_required(login_url="staff-login")
@require_GET
def my_maru_schedule_index(request: HttpRequest) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        editions = my_maru_schedule_editions(actor=_actor(request))
    except VenueAuthorizationDeniedError as error:
        raise PermissionDenied("The attendee schedule is unavailable.") from error
    return _response(
        request,
        "venues/my_schedule_index.html",
        _page_context(
            request,
            personal=True,
            title="My schedule",
            editions=editions,
        ),
    )


@login_required(login_url="staff-login")
@require_GET
def my_maru_venue_schedule(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        actor = _actor(request)
        edition = _route_edition(organization_slug, series_slug, edition_slug)
        items = my_maru_schedule_for_edition(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except VenueAuthorizationDeniedError as error:
        raise PermissionDenied("The attendee schedule is unavailable.") from error
    except DatabaseError:
        return _plain_error("The schedule is temporarily unavailable.", status=503)
    return _response(
        request,
        "venues/my_schedule.html",
        _page_context(
            request,
            edition=edition,
            personal=True,
            title=f"{edition.name} schedule",
            items=tuple(asdict(item) for item in items),
        ),
    )
