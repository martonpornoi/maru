"""Non-database contracts for Venues browser adapter branches."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from maru.identity.models import Account
from maru.venues import views
from maru.venues.models import VenueProperty
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueBookingEnvelope,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCommandError,
    VenueIndependentApprovalError,
    VenueResourceUnavailableError,
    VenueRetryConflictError,
    VenueStateConflictError,
    VenueVersionConflictError,
)

_FACTORY = RequestFactory()


def _actor(*, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        email="venue-browser@example.invalid",
        is_active=active,
    )


def _request(method: str = "post", data: dict[str, object] | None = None):
    request = getattr(_FACTORY, method)("/", data=data or {})
    request.user = _actor()
    request.correlation_id = str(uuid4())
    return request


def _edition() -> SimpleNamespace:
    organization = SimpleNamespace(id=uuid4(), slug="organizer")
    series = SimpleNamespace(id=uuid4(), slug="series")
    return SimpleNamespace(
        id=uuid4(),
        slug="edition",
        name="Convention 2027",
        organization=organization,
        organization_id=organization.id,
        series=series,
        series_id=series.id,
        time_zone="Europe/Budapest",
    )


def _form(*, valid: bool = True) -> MagicMock:
    now = timezone.now()
    values = {
        "retry_key": uuid4(),
        "reason": "Exercise the browser adapter.",
        "expected_version": 2,
        "slug": "riverside-hotel",
        "kind": "photo",
        "site_code": "main",
        "site_name": "Main site",
        "building_code": "hall",
        "building_name": "Hall",
        "space_code": "room",
        "space_name": "Room",
        "space_kind": "function_room",
        "configuration_code": "theatre",
        "configuration_name": "Theatre",
        "seated_capacity": 10,
        "standing_capacity": 20,
        "table_capacity": 8,
        "fire_capacity": 25,
        "code": "combined",
        "name": "Combined rooms",
        "member_space_ids": (uuid4(), uuid4()),
        "source_reference": "provider://artifact",
        "owner_name": "Provider",
        "license_basis": "Contract",
        "usage_scope": "Venue listing",
        "public_reference": "https://media.example.invalid/public.webp",
        "space_id": uuid4(),
        "layout_code": "attendee-plan",
        "version": 1,
        "title": "Attendee plan",
        "visibility": "public",
        "checksum_sha256": "a" * 64,
        "public_name": "Accessible twin",
        "minimum_occupants": 1,
        "maximum_occupants": 2,
        "room_type_id": uuid4(),
        "night": date(2027, 8, 1),
        "room_capacity": 10,
        "release_at": now,
        "property_id": uuid4(),
        "responsible_department_id": uuid4(),
        "local_name": "Main venue",
        "venue_selection_id": uuid4(),
        "source_space_id": uuid4(),
        "source_combination_id": None,
        "selected_configuration_id": uuid4(),
        "intervals": (),
        "internal_title": "Production title",
        "public_title": "Public title",
        "capacity_mode": "seated",
        "expected_attendance": 8,
        "public_layout_id": None,
    }
    form = MagicMock()
    form.is_valid.return_value = valid
    form.cleaned_data = values
    form.changes = {"public_name": "Updated venue"}
    form.capacity = None
    form.intervals = ()
    form.envelope = VenueBookingEnvelope(now, now, now, now)
    return form


def test_request_context_and_strict_get_helpers() -> None:
    request = _request("get")
    assert views._actor(request) is request.user
    request.user = _actor(active=False)
    with pytest.raises(PermissionDenied):
        views._actor(request)

    edition = _edition()
    with patch.object(views.admin.site, "each_context", return_value={"site": "Maru"}):
        context = views._page_context(
            request,
            edition=edition,
            personal=True,
            title="Venue",
        )
    assert context["edition"] is edition
    assert context["maru_personal_surface"] is True

    assert views._strict_get(_request("get")) is None
    invalid = _FACTORY.get("/", {"future": "value"})
    assert views._strict_get(invalid).status_code == 400
    assert views._plain_error("bad", status=409)["Cache-Control"] == "private, no-store"


def test_scope_policy_resolution_is_explicit_and_closed() -> None:
    actor = _actor()
    edition = _edition()
    for capability, selection_id, resolver_name in (
        ("venues.manage_space_schedule", uuid4(), "resolve_edition_space_target"),
        (views.EDITION_SELECT_CAPABILITY, None, "resolve_edition_target"),
        (views.PROPERTY_MANAGE_CAPABILITY, None, "resolve_organization_target"),
    ):
        with (
            patch.object(views, resolver_name, return_value=object()),
            patch.object(views, "decide", return_value=SimpleNamespace(allowed=True)),
        ):
            assert views._allowed(
                actor=actor,
                capability_code=capability,
                edition=edition,
                space_selection_id=selection_id,
            )
        with (
            patch.object(views, resolver_name, return_value=None),
            patch.object(views, "decide") as decide,
        ):
            assert not views._allowed(
                actor=actor,
                capability_code=capability,
                edition=edition,
                space_selection_id=selection_id,
            )
            decide.assert_not_called()

    with (
        patch.object(views, "_allowed", return_value=False),
        pytest.raises(PermissionDenied),
    ):
        views._require_allowed(
            actor=actor,
            capability_code="venues.view_workspace",
            edition=edition,
        )


def test_command_error_maps_validation_conflicts_and_closed_failures() -> None:
    form = forms.Form()
    form.fields["name"] = forms.CharField()
    form.cleaned_data = {}
    assert views._command_error(form, ValidationError({"name": ["Bad name"]})) == 400
    assert views._command_error(form, ValidationError("Bad input")) == 400

    for error in (
        VenueIndependentApprovalError(),
        VenueCapacityConflictError(),
        VenueAvailabilityConflictError(),
        VenueBookingOverlapError(),
        VenueVersionConflictError(),
        VenueRetryConflictError(),
        VenueStateConflictError(),
        VenueCommandError(),
    ):
        assert views._command_error(form, error) == 409
    with pytest.raises(PermissionDenied):
        views._command_error(form, VenueAuthorizationDeniedError())
    with pytest.raises(Http404):
        views._command_error(form, VenueResourceUnavailableError())
    unexpected = RuntimeError("unexpected")
    with pytest.raises(RuntimeError, match="unexpected"):
        views._command_error(form, unexpected)


def test_catalog_choices_scope_every_owned_query() -> None:
    edition = _edition()

    def ordered() -> MagicMock:
        queryset = MagicMock()
        queryset.order_by.return_value = ()
        return queryset

    def related() -> MagicMock:
        queryset = MagicMock()
        queryset.select_related.return_value.order_by.return_value = ()
        return queryset

    with (
        patch.object(views.VenueProperty.objects, "filter", return_value=ordered()),
        patch.object(
            views.EditionVenueSelection.objects, "filter", return_value=related()
        ),
        patch.object(views.VenueSpace.objects, "filter", return_value=ordered()),
        patch.object(
            views.VenueSpaceCombination.objects, "filter", return_value=ordered()
        ),
        patch.object(
            views.VenueSpaceConfiguration.objects, "filter", return_value=related()
        ),
        patch.object(views.Department.objects, "filter", return_value=ordered()),
    ):
        assert views._catalog_choices(edition=edition) == ((), (), (), (), (), ())


def test_action_response_helpers_cover_invalid_success_and_conflict() -> None:
    request = _request()
    edition = _edition()
    form = _form(valid=False)
    with patch.object(
        views, "_property_response", return_value=HttpResponse("invalid")
    ):
        response = views._property_action_response(
            request,
            edition=edition,
            property_id=uuid4(),
            form_name="form",
            form=form,
            command=lambda: None,
            success_message="Done",
        )
    assert response.content == b"invalid"

    form.is_valid.return_value = True
    with (
        patch.object(views.messages, "success"),
        patch.object(views, "redirect", return_value=HttpResponse(status=302)),
    ):
        response = views._property_action_response(
            request,
            edition=edition,
            property_id=uuid4(),
            form_name="form",
            form=form,
            command=lambda: None,
            success_message="Done",
        )
    assert response.status_code == 302

    with (
        patch.object(views, "_command_error", return_value=409),
        patch.object(
            views, "_space_response", return_value=HttpResponse("conflict", status=409)
        ),
    ):
        response = views._space_action_response(
            request,
            actor=_actor(),
            edition=edition,
            space_selection_id=uuid4(),
            form_name="form",
            form=form,
            command=lambda: (_ for _ in ()).throw(VenueStateConflictError()),
            success_message="Done",
        )
    assert response.status_code == 409


def test_property_mutation_endpoints_build_complete_commands() -> None:
    actor = _actor()
    edition = _edition()
    property_id = uuid4()
    request = _request()
    form = _form()

    def action_response(*_args: object, command, **_kwargs: object) -> HttpResponse:
        command()
        return HttpResponse("ok")

    specs = (
        (
            views.venue_property_update,
            "VenuePropertyUpdateForm",
            "update_venue_property",
            {},
        ),
        (
            views.venue_catalog_path_create,
            "VenueCatalogPathForm",
            "create_venue_space_catalog_path",
            {},
        ),
        (
            views.venue_combination_create,
            "VenueCombinationForm",
            "create_venue_space_combination",
            {},
        ),
        (views.venue_media_add, "VenueMediaAddForm", "add_venue_property_media", {}),
        (
            views.venue_media_approve,
            "VenueReviewForm",
            "approve_venue_property_media",
            {"media_id": uuid4()},
        ),
        (views.venue_layout_add, "VenueLayoutAddForm", "add_venue_layout_version", {}),
        (
            views.venue_layout_approve,
            "VenueReviewForm",
            "approve_venue_layout_version",
            {"layout_id": uuid4()},
        ),
        (
            views.venue_room_type_create,
            "AccommodationRoomTypeForm",
            "create_accommodation_room_type",
            {},
        ),
        (
            views.venue_inventory_set,
            "AccommodationInventoryForm",
            "set_accommodation_night_inventory",
            {},
        ),
    )
    for endpoint, form_name, command_name, extra in specs:
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_require_allowed"),
            patch.object(views, form_name, return_value=form),
            patch.object(
                views, "_property_action_response", side_effect=action_response
            ),
            patch.object(views.VenueSpace.objects, "filter", return_value=()),
            patch.object(
                views.AccommodationRoomType.objects, "filter", return_value=()
            ),
            patch.object(
                views, command_name, return_value=SimpleNamespace(object_id=uuid4())
            ) as command,
        ):
            response = endpoint(
                request,
                "organizer",
                "series",
                "edition",
                property_id,
                **extra,
            )
        assert response.status_code == 200
        assert command.called


def test_edition_space_and_booking_endpoints_dispatch_commands() -> None:
    actor = _actor()
    edition = _edition()
    request = _request()
    form = _form()
    selection_id, booking_id = uuid4(), uuid4()

    def action_response(*_args: object, command, **_kwargs: object) -> HttpResponse:
        command()
        return HttpResponse("ok")

    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(views, "_require_allowed"),
        patch.object(views, "_catalog_choices", return_value=((), (), (), (), (), ())),
        patch.object(views, "VenueEditionSelectionForm", return_value=form),
        patch.object(views, "select_venue_for_edition"),
        patch.object(views.messages, "success"),
        patch.object(views, "redirect", return_value=HttpResponse(status=302)),
    ):
        assert (
            views.venue_edition_select(
                request, "organizer", "series", "edition"
            ).status_code
            == 302
        )

    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(views, "_require_allowed"),
        patch.object(views, "_catalog_choices", return_value=((), (), (), (), (), ())),
        patch.object(views, "VenueSpaceSelectionForm", return_value=form),
        patch.object(views, "select_space_for_edition"),
        patch.object(views.messages, "success"),
        patch.object(views, "redirect", return_value=HttpResponse(status=302)),
    ):
        assert (
            views.venue_space_select(
                request, "organizer", "series", "edition"
            ).status_code
            == 302
        )

    specs = (
        (
            views.venue_availability_set,
            "VenueAvailabilityForm",
            "set_edition_space_availability",
            {},
        ),
        (views.venue_booking_create, "VenueBookingForm", "create_venue_booking", {}),
        (
            views.venue_booking_reschedule,
            "VenueBookingForm",
            "reschedule_venue_booking",
            {"booking_id": booking_id},
        ),
    )
    for endpoint, form_name, command_name, extra in specs:
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_require_allowed"),
            patch.object(views, "_layouts_for_booking", return_value=()),
            patch.object(views, form_name, return_value=form),
            patch.object(views, "_space_action_response", side_effect=action_response),
            patch.object(views, command_name) as command,
        ):
            response = endpoint(
                request,
                "organizer",
                "series",
                "edition",
                selection_id,
                **extra,
            )
        assert response.status_code == 200
        assert command.called

    for action, command_name in (
        ("approve", "approve_venue_booking"),
        ("publish", "publish_venue_booking"),
        ("withdraw", "withdraw_venue_booking_publication"),
        ("cancel", "cancel_venue_booking"),
    ):
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_require_allowed"),
            patch.object(views, "VenueBookingStateForm", return_value=form),
            patch.object(views, "_space_action_response", side_effect=action_response),
            patch.object(views, command_name) as command,
        ):
            response = views.venue_booking_command(
                request,
                "organizer",
                "series",
                "edition",
                selection_id,
                booking_id,
                action,
            )
        assert response.status_code == 200
        assert command.called

    with pytest.raises(Http404):
        views.venue_booking_command(
            request,
            "organizer",
            "series",
            "edition",
            selection_id,
            booking_id,
            "future",
        )


def test_booking_projection_helpers_require_a_real_space() -> None:
    edition = _edition()
    queryset = MagicMock()
    queryset.filter.return_value.first.return_value = None
    with (
        patch.object(views.EditionSpaceSelection, "objects", queryset),
        pytest.raises(Http404),
    ):
        views._layouts_for_booking(
            edition=edition,
            space_selection_id=uuid4(),
        )

    form = _form()
    values = views._booking_command_values(form)
    assert values["expected_attendance"] == 8

    record = VenueProperty(aggregate_version=7)
    initial = views._property_initial(record)
    assert initial["expected_version"] == 7


def _query_chain(result: tuple[object, ...] = ()) -> MagicMock:
    queryset = MagicMock()
    queryset.select_related.return_value = queryset
    queryset.prefetch_related.return_value = queryset
    queryset.exclude.return_value = queryset
    queryset.order_by.return_value = result
    queryset.first.return_value = result[0] if result else None
    return queryset


def test_workspace_projection_builds_forms_only_for_selectors() -> None:
    request, actor, edition = _request("get"), _actor(), _edition()
    active_form = _form()
    with (
        patch.object(views, "list_venue_properties", return_value=()),
        patch.object(views, "list_venue_workspace", return_value=()),
        patch.object(views, "_catalog_choices", return_value=((), (), (), (), (), ())),
        patch.object(views, "_allowed", side_effect=(True, True)),
        patch.object(views, "VenueEditionSelectionForm"),
        patch.object(views, "VenueSpaceSelectionForm"),
        patch.object(views, "_page_context", return_value={}),
        patch.object(views, "_response", return_value=HttpResponse("workspace")),
    ):
        response = views._workspace_response(
            request,
            actor=actor,
            edition=edition,
            active_form_name="venue_selection_form",
            active_form=active_form,
        )
    assert response.content == b"workspace"

    with (
        patch.object(views, "list_venue_properties", return_value=()),
        patch.object(views, "list_venue_workspace", return_value=()),
        patch.object(views, "_catalog_choices", return_value=((), (), (), (), (), ())),
        patch.object(views, "_allowed", side_effect=(False, False)),
        patch.object(views, "_page_context", return_value={}),
        patch.object(views, "_response", return_value=HttpResponse("workspace")),
    ):
        views._workspace_response(request, actor=actor, edition=edition)


def test_property_visibility_and_projection_cover_review_form_branches() -> None:
    request, actor, edition = _request("get"), _actor(), _edition()
    property_id = uuid4()
    visible = SimpleNamespace(id=property_id)
    with (
        patch.object(views, "list_venue_properties", return_value=()),
        pytest.raises(Http404),
    ):
        views._property_record(
            request=request,
            actor=actor,
            edition=edition,
            property_id=property_id,
        )

    with (
        patch.object(views, "list_venue_properties", return_value=(visible,)),
        patch.object(
            views.VenueProperty.objects, "filter", return_value=_query_chain()
        ),
        pytest.raises(Http404),
    ):
        views._property_record(
            request=request,
            actor=actor,
            edition=edition,
            property_id=property_id,
        )

    record = VenueProperty(id=property_id, public_name="Riverside", aggregate_version=1)
    pending_media = SimpleNamespace(
        id=uuid4(),
        review_status=views.VenuePropertyMedia.ReviewStatus.PENDING,
        aggregate_version=1,
    )
    approved_media = SimpleNamespace(
        id=uuid4(),
        review_status=views.VenuePropertyMedia.ReviewStatus.APPROVED,
        aggregate_version=2,
    )
    pending_layout = SimpleNamespace(
        id=uuid4(),
        review_status=views.VenueLayoutVersion.ReviewStatus.PENDING,
        aggregate_version=1,
    )
    approved_layout = SimpleNamespace(
        id=uuid4(),
        review_status=views.VenueLayoutVersion.ReviewStatus.APPROVED,
        aggregate_version=2,
    )
    inventory = SimpleNamespace(
        room_type_id=uuid4(),
        night=date(2027, 8, 1),
        room_capacity=8,
        release_at=timezone.now(),
        provider_reference="provider-1",
        aggregate_version=2,
    )

    managers = (
        (views.VenueSpace.objects, ()),
        (views.VenueSpaceCombination.objects, ()),
        (views.VenuePropertyMedia.objects, (pending_media, approved_media)),
        (views.VenueLayoutVersion.objects, (pending_layout, approved_layout)),
        (views.AccommodationRoomType.objects, ()),
        (views.AccommodationNightInventory.objects, (inventory,)),
    )
    contexts = [
        patch.object(manager, "filter", return_value=_query_chain(result))
        for manager, result in managers
    ]
    with (
        patch.object(views, "_property_record", return_value=record),
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        contexts[4],
        contexts[5],
        patch.object(views, "_allowed", side_effect=(True, True)),
        patch.object(views, "_page_context", return_value={}),
        patch.object(views, "_response", return_value=HttpResponse("property")),
    ):
        response = views._property_response(
            request,
            actor=actor,
            edition=edition,
            property_id=property_id,
            active_form_name="media_review_form",
            active_form=_form(),
            active_object_id=pending_media.id,
        )
    assert response.content == b"property"

    contexts = [
        patch.object(manager, "filter", return_value=_query_chain(result))
        for manager, result in managers
    ]
    with (
        patch.object(views, "_property_record", return_value=record),
        contexts[0],
        contexts[1],
        contexts[2],
        contexts[3],
        contexts[4],
        contexts[5],
        patch.object(views, "_allowed", side_effect=(True, True)),
        patch.object(views, "_page_context", return_value={}),
        patch.object(views, "_response", return_value=HttpResponse("property")),
    ):
        views._property_response(
            request,
            actor=actor,
            edition=edition,
            property_id=property_id,
            active_form_name="layout_review_form",
            active_form=_form(),
            active_object_id=pending_layout.id,
        )


def test_space_projection_missing_space_and_active_form_overrides() -> None:
    request, actor, edition = _request("get"), _actor(), _edition()
    selection_id = uuid4()
    schedule = SimpleNamespace(
        availability=(), space=SimpleNamespace(local_name="Hall")
    )
    with (
        patch.object(views, "load_space_schedule", return_value=schedule),
        patch.object(
            views.EditionSpaceSelection.objects, "filter", return_value=_query_chain()
        ),
        pytest.raises(Http404),
    ):
        views._space_response(
            request,
            actor=actor,
            edition=edition,
            space_selection_id=selection_id,
        )

    space = SimpleNamespace(id=selection_id, aggregate_version=2)
    booking = SimpleNamespace(
        id=uuid4(),
        lifecycle=views.VenueBooking.Lifecycle.ACTIVE,
        aggregate_version=3,
    )
    for active_name, active_booking_id in (
        ("availability_form", None),
        ("reschedule_form", booking.id),
        ("state_form_approve", booking.id),
    ):
        with (
            patch.object(views, "load_space_schedule", return_value=schedule),
            patch.object(
                views.EditionSpaceSelection.objects,
                "filter",
                return_value=_query_chain((space,)),
            ),
            patch.object(views, "_allowed", side_effect=(False, False)),
            patch.object(views, "_approved_layouts", return_value=()),
            patch.object(
                views.VenueBooking.objects,
                "filter",
                return_value=_query_chain((booking,)),
            ),
            patch.object(views, "_page_context", return_value={}),
            patch.object(views, "_response", return_value=HttpResponse("space")),
        ):
            response = views._space_response(
                request,
                actor=actor,
                edition=edition,
                space_selection_id=selection_id,
                active_form_name=active_name,
                active_form=_form(),
                active_booking_id=active_booking_id,
            )
        assert response.content == b"space"


def test_page_adapters_translate_strict_query_and_dependency_failures() -> None:
    actor, edition = _actor(), _edition()
    selection_id, property_id = uuid4(), uuid4()
    get_with_query = _request("get")
    get_with_query.GET = {"future": "value"}
    strict_specs = (
        (views.venue_workspace, ("organizer", "series", "edition")),
        (views.venue_property_create_page, ("organizer", "series", "edition")),
        (
            views.venue_property_detail_page,
            ("organizer", "series", "edition", property_id),
        ),
        (
            views.venue_space_schedule_page,
            ("organizer", "series", "edition", selection_id),
        ),
        (views.my_maru_schedule_index, ()),
        (views.my_maru_venue_schedule, ("organizer", "series", "edition")),
    )
    for endpoint, args in strict_specs:
        assert endpoint(get_with_query, *args).status_code == 400

    request = _request("get")
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(
            views, "_workspace_response", side_effect=VenueAuthorizationDeniedError()
        ),
        pytest.raises(PermissionDenied),
    ):
        views.venue_workspace(request, "organizer", "series", "edition")
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(views, "_workspace_response", side_effect=DatabaseError()),
    ):
        assert (
            views.venue_workspace(request, "organizer", "series", "edition").status_code
            == 503
        )

    for error, exception_type in (
        (VenueAuthorizationDeniedError(), PermissionDenied),
        (VenueResourceUnavailableError(), Http404),
    ):
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_space_response", side_effect=error),
            pytest.raises(exception_type),
        ):
            views.venue_space_schedule_page(
                request, "organizer", "series", "edition", selection_id
            )
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(views, "_space_response", side_effect=DatabaseError()),
    ):
        assert (
            views.venue_space_schedule_page(
                request, "organizer", "series", "edition", selection_id
            ).status_code
            == 503
        )

    with (
        patch.object(
            views,
            "my_maru_schedule_editions",
            side_effect=VenueAuthorizationDeniedError(),
        ),
        pytest.raises(PermissionDenied),
    ):
        views.my_maru_schedule_index(request)
    for error, exception_type in (
        (VenueAuthorizationDeniedError(), PermissionDenied),
        (DatabaseError(), None),
    ):
        contexts = (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "my_maru_schedule_for_edition", side_effect=error),
        )
        with contexts[0], contexts[1], contexts[2]:
            if exception_type is not None:
                with pytest.raises(exception_type):
                    views.my_maru_venue_schedule(
                        request, "organizer", "series", "edition"
                    )
            else:
                assert (
                    views.my_maru_venue_schedule(
                        request, "organizer", "series", "edition"
                    ).status_code
                    == 503
                )


def test_route_and_property_record_success_and_missing_branches() -> None:
    route_query = MagicMock()
    route_query.select_related.return_value.filter.return_value.first.return_value = (
        None
    )
    with (
        patch.object(views.EventEdition, "objects", route_query),
        pytest.raises(Http404),
    ):
        views._edition_route(
            organization_slug="organizer",
            series_slug="series",
            edition_slug="edition",
        )

    request, actor, edition = _request("get"), _actor(), _edition()
    property_id = uuid4()
    record = VenueProperty(id=property_id, public_name="Riverside")
    with (
        patch.object(
            views,
            "list_venue_properties",
            return_value=(SimpleNamespace(id=property_id),),
        ),
        patch.object(
            views.VenueProperty.objects,
            "filter",
            return_value=_query_chain((record,)),
        ),
    ):
        assert (
            views._property_record(
                request=request,
                actor=actor,
                edition=edition,
                property_id=property_id,
            )
            is record
        )


def test_property_create_page_and_post_cover_invalid_conflict_and_success() -> None:
    actor, edition = _actor(), _edition()
    request = _request("get")
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_route_edition", return_value=edition),
        patch.object(views, "_require_allowed"),
        patch.object(views, "VenuePropertyCreateForm"),
        patch.object(views, "_page_context", return_value={}),
        patch.object(views, "_response", return_value=HttpResponse("create")),
    ):
        assert (
            views.venue_property_create_page(
                request, "organizer", "series", "edition"
            ).content
            == b"create"
        )

    for valid, command_error, expected_status in (
        (False, None, 400),
        (True, VenueStateConflictError(), 409),
        (True, None, 302),
    ):
        form = _form(valid=valid)
        result = SimpleNamespace(object_id=uuid4())
        command = patch.object(
            views,
            "create_venue_property",
            return_value=result,
            side_effect=command_error,
        )
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_require_allowed"),
            patch.object(views, "VenuePropertyCreateForm", return_value=form),
            command,
            patch.object(views, "_command_error", return_value=409),
            patch.object(views.messages, "success"),
            patch.object(views, "redirect", return_value=HttpResponse(status=302)),
            patch.object(views, "_page_context", return_value={}),
            patch.object(
                views,
                "_response",
                side_effect=lambda *_args, status=200, **_kwargs: HttpResponse(
                    status=status
                ),
            ),
        ):
            response = views.venue_property_create(
                _request("post"), "organizer", "series", "edition"
            )
        assert response.status_code == expected_status


def test_property_detail_translates_authorization_and_database_failures() -> None:
    actor, edition = _actor(), _edition()
    request = _request("get")
    property_id = uuid4()
    for error, exception_type in (
        (VenueAuthorizationDeniedError(), PermissionDenied),
        (DatabaseError(), None),
    ):
        with (
            patch.object(views, "_actor", return_value=actor),
            patch.object(views, "_route_edition", return_value=edition),
            patch.object(views, "_property_response", side_effect=error),
        ):
            if exception_type is not None:
                with pytest.raises(exception_type):
                    views.venue_property_detail_page(
                        request,
                        "organizer",
                        "series",
                        "edition",
                        property_id,
                    )
            else:
                assert (
                    views.venue_property_detail_page(
                        request,
                        "organizer",
                        "series",
                        "edition",
                        property_id,
                    ).status_code
                    == 503
                )
