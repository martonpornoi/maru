"""Executable non-database contracts for the strict Venues API adapters."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.identity.models import Account
from maru.venues import api
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCommandError,
    VenueCommandResult,
    VenueIndependentApprovalError,
    VenueResourceUnavailableError,
    VenueRetryConflictError,
    VenueStateConflictError,
    VenueVersionConflictError,
)

_FACTORY = APIRequestFactory()


def _actor(*, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        email="venue-api@example.invalid",
        is_active=active,
    )


def _request(
    method: str,
    data: object | None = None,
    *,
    actor: Account | None = None,
    idempotency_key: str | None = None,
) -> object:
    headers = {}
    if idempotency_key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    request = getattr(_FACTORY, method)("/", data=data, format="json", **headers)
    request.correlation_id = str(uuid4())
    if actor is not None:
        force_authenticate(request, user=actor)
    return request


def _result(*, replayed: bool = False) -> VenueCommandResult:
    return VenueCommandResult(
        object_id=uuid4(),
        receipt_id=uuid4(),
        resulting_version=3,
        replayed=replayed,
    )


def test_account_idempotency_and_correlation_boundaries() -> None:
    actor = _actor()
    key = uuid4()
    raw = _request("post", {}, actor=actor, idempotency_key=str(key))
    request = Request(raw)
    assert api._account(request) is actor
    assert api._idempotency_key(request) == key
    assert api._correlation_id(request) == UUID(raw.correlation_id)

    raw.correlation_id = key
    assert api._correlation_id(request) == key
    del raw.correlation_id
    assert isinstance(api._correlation_id(request), UUID)

    for invalid in (None, "", "not-a-uuid", str(key).upper(), f" {key}"):
        malformed = Request(_request("post", {}, actor=actor, idempotency_key=invalid))
        with pytest.raises(ValidationError):
            api._idempotency_key(malformed)

    with pytest.raises(PermissionDenied):
        api._account(Request(_request("get")))
    with pytest.raises(PermissionDenied):
        api._account(Request(_request("get", actor=_actor(active=False))))


def test_authorizers_deny_closed_scopes_and_return_the_account() -> None:
    actor = _actor()
    request = Request(_request("get", actor=actor))
    organization_id, edition_id, space_id = uuid4(), uuid4(), uuid4()
    calls = (
        (
            api._authorize_organization,
            {"organization_id": organization_id, "capability_code": "view"},
        ),
        (
            api._authorize_edition,
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "capability_code": "view",
            },
        ),
        (
            api._authorize_space,
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "space_selection_id": space_id,
                "capability_code": "view",
            },
        ),
    )
    for helper, values in calls:
        with (
            patch.object(api, "resolve_organization_target", return_value=object()),
            patch.object(api, "resolve_edition_target", return_value=object()),
            patch.object(api, "resolve_edition_space_target", return_value=object()),
            patch.object(api, "decide", return_value=SimpleNamespace(allowed=True)),
        ):
            assert helper(request, **values) is actor
        with (
            patch.object(api, "resolve_organization_target", return_value=object()),
            patch.object(api, "resolve_edition_target", return_value=object()),
            patch.object(api, "resolve_edition_space_target", return_value=object()),
            patch.object(api, "decide", return_value=SimpleNamespace(allowed=False)),
            pytest.raises(PermissionDenied),
        ):
            helper(request, **values)


@pytest.mark.parametrize(
    ("error", "exception_type"),
    [
        (VenueAuthorizationDeniedError(), PermissionDenied),
        (VenueResourceUnavailableError(), NotFound),
        (VenueVersionConflictError(), api.VenueConflict),
        (VenueRetryConflictError(), api.VenueConflict),
        (VenueStateConflictError(), api.VenueConflict),
        (VenueIndependentApprovalError(), api.VenueConflict),
        (VenueAvailabilityConflictError(), api.VenueConflict),
        (VenueCapacityConflictError(), api.VenueConflict),
        (VenueBookingOverlapError(), api.VenueConflict),
        (DjangoValidationError({"field": ["invalid"]}), ValidationError),
        (DjangoValidationError("invalid"), ValidationError),
        (IntegrityError(), api.VenueConflict),
        (DatabaseError(), api.DependencyUnavailable),
        (VenueCommandError(), api.DependencyUnavailable),
    ],
)
def test_execute_translates_closed_failures(
    error: Exception,
    exception_type: type[Exception],
) -> None:
    with pytest.raises(exception_type):
        api._execute(lambda: (_ for _ in ()).throw(error))


def test_result_and_booking_envelope_adapters() -> None:
    created = api._result_response(_result(), created=True)
    assert created.status_code == 201
    replay = api._result_response(_result(replayed=True), created=True)
    assert replay.status_code == 200
    ordinary = api._result_response(_result())
    assert ordinary.status_code == 200

    now = timezone.now()
    envelope = api._booking_envelope(
        {
            "setup_starts_at": now,
            "effective_starts_at": now,
            "effective_ends_at": now,
            "teardown_ends_at": now,
        }
    )
    assert envelope.setup_starts_at == now


def _values() -> dict[str, object]:
    now = timezone.now()
    return {
        "slug": "riverside-hotel",
        "kind": "mixed",
        "legal_name": "Riverside Hotel Limited",
        "provider_name": "Riverside Hospitality",
        "public_name": "Riverside Hotel",
        "reason": "Exercise the strict adapter.",
        "expected_version": 2,
        "lifecycle": "active",
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
        "member_space_ids": [uuid4(), uuid4()],
        "source_reference": "provider://artifact",
        "owner_name": "Provider",
        "license_basis": "Contract",
        "usage_scope": "Venue listing",
        "public_reference": "https://media.example.invalid/public.webp",
        "layout_code": "attendee-plan",
        "version": 1,
        "title": "Attendee plan",
        "visibility": "public",
        "checksum_sha256": "a" * 64,
        "minimum_occupants": 1,
        "maximum_occupants": 2,
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
        "capacity": None,
        "intervals": [
            {
                "starts_at": now,
                "ends_at": now,
                "opening_restriction": "Staff only",
            }
        ],
        "internal_title": "Production title",
        "public_title": "Public title",
        "capacity_mode": "seated",
        "expected_attendance": 8,
        "setup_starts_at": now,
        "effective_starts_at": now,
        "effective_ends_at": now,
        "teardown_ends_at": now,
        "public_layout_id": None,
    }


def test_mutation_views_dispatch_complete_commands() -> None:
    actor = _actor()
    organization_id, edition_id = uuid4(), uuid4()
    property_id, space_id, selection_id = uuid4(), uuid4(), uuid4()
    media_id, layout_id, room_type_id, booking_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    specs = (
        (
            api.VenuePropertyCollectionView,
            "post",
            "create_venue_property",
            {"organization_id": organization_id},
        ),
        (
            api.VenuePropertyDetailView,
            "patch",
            "update_venue_property",
            {"organization_id": organization_id, "property_id": property_id},
        ),
        (
            api.VenueSpaceCatalogCollectionView,
            "post",
            "create_venue_space_catalog_path",
            {"organization_id": organization_id, "property_id": property_id},
        ),
        (
            api.VenueCombinationCollectionView,
            "post",
            "create_venue_space_combination",
            {"organization_id": organization_id, "property_id": property_id},
        ),
        (
            api.VenueMediaCollectionView,
            "post",
            "add_venue_property_media",
            {"organization_id": organization_id, "property_id": property_id},
        ),
        (
            api.VenueMediaApproveView,
            "post",
            "approve_venue_property_media",
            {
                "organization_id": organization_id,
                "property_id": property_id,
                "media_id": media_id,
            },
        ),
        (
            api.VenueLayoutCollectionView,
            "post",
            "add_venue_layout_version",
            {"organization_id": organization_id, "space_id": space_id},
        ),
        (
            api.VenueLayoutApproveView,
            "post",
            "approve_venue_layout_version",
            {"organization_id": organization_id, "layout_id": layout_id},
        ),
        (
            api.VenueRoomTypeCollectionView,
            "post",
            "create_accommodation_room_type",
            {"organization_id": organization_id, "property_id": property_id},
        ),
        (
            api.VenueNightInventoryView,
            "put",
            "set_accommodation_night_inventory",
            {"organization_id": organization_id, "room_type_id": room_type_id},
        ),
        (
            api.VenueWorkspaceCollectionView,
            "post",
            "select_venue_for_edition",
            {"organization_id": organization_id, "edition_id": edition_id},
        ),
        (
            api.VenueSpaceSelectionCollectionView,
            "post",
            "select_space_for_edition",
            {"organization_id": organization_id, "edition_id": edition_id},
        ),
        (
            api.VenueSpaceAvailabilityView,
            "put",
            "set_edition_space_availability",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "space_selection_id": selection_id,
            },
        ),
        (
            api.VenueBookingCollectionView,
            "post",
            "create_venue_booking",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "space_selection_id": selection_id,
            },
        ),
        (
            api.VenueBookingDetailView,
            "patch",
            "reschedule_venue_booking",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "space_selection_id": selection_id,
                "booking_id": booking_id,
            },
        ),
    )
    values = _values()
    for view, method, command_name, kwargs in specs:
        request = _request(
            method,
            values,
            actor=actor,
            idempotency_key=str(uuid4()),
        )
        with (
            patch.object(api, "_authorize_organization", return_value=actor),
            patch.object(api, "_authorize_edition", return_value=actor),
            patch.object(api, "_authorize_space", return_value=actor),
            patch.object(api, "_validated", return_value=values),
            patch.object(api, command_name, return_value=_result()) as command,
        ):
            response = view.as_view()(request, **kwargs)
        assert response.status_code in {200, 201}
        assert command.call_args.kwargs["actor"] is actor

    values["capacity"] = {
        "configuration_name": "Custom",
        "seated_capacity": 10,
        "standing_capacity": 20,
        "table_capacity": 8,
        "fire_capacity": 25,
    }
    with (
        patch.object(api, "_authorize_edition", return_value=actor),
        patch.object(api, "_validated", return_value=values),
        patch.object(
            api, "select_space_for_edition", return_value=_result()
        ) as command,
    ):
        api.VenueSpaceSelectionCollectionView.as_view()(
            _request("post", values, actor=actor, idempotency_key=str(uuid4())),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert command.call_args.kwargs["capacity"].configuration_name == "Custom"


def test_booking_command_dispatch_and_unknown_action() -> None:
    actor = _actor()
    ids = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "space_selection_id": uuid4(),
        "booking_id": uuid4(),
    }
    values = {"expected_version": 2, "reason": "Apply lifecycle command."}
    dependencies = {
        "approve": "approve_venue_booking",
        "publish": "publish_venue_booking",
        "withdraw": "withdraw_venue_booking_publication",
        "cancel": "cancel_venue_booking",
    }
    for action, dependency in dependencies.items():
        with (
            patch.object(api, "_authorize_space", return_value=actor),
            patch.object(api, "_validated", return_value=values),
            patch.object(api, dependency, return_value=_result()) as command,
        ):
            response = api.VenueBookingCommandView.as_view()(
                _request("post", values, actor=actor, idempotency_key=str(uuid4())),
                action=action,
                **ids,
            )
        assert response.status_code == 200
        assert command.called

    with patch.object(api, "_authorize_space", return_value=actor):
        response = api.VenueBookingCommandView.as_view()(
            _request("post", values, actor=actor, idempotency_key=str(uuid4())),
            action="future",
            **ids,
        )
    assert response.status_code == 404


def test_query_views_project_bounded_rows() -> None:
    actor = _actor()
    organization_id, edition_id, selection_id = uuid4(), uuid4(), uuid4()

    class _Projection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.data: list[object] = []

    specs = (
        (
            api.VenuePropertyCollectionView,
            "_authorize_organization",
            "list_venue_properties",
            "VenuePropertySummarySerializer",
            {"organization_id": organization_id},
        ),
        (
            api.VenueWorkspaceCollectionView,
            "_authorize_edition",
            "list_venue_workspace",
            "VenueWorkspaceSpaceSerializer",
            {"organization_id": organization_id, "edition_id": edition_id},
        ),
        (
            api.VenueSpaceScheduleView,
            "_authorize_space",
            "load_space_schedule",
            "VenueSpaceScheduleSerializer",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "space_selection_id": selection_id,
            },
        ),
    )
    for view, authorize_name, query_name, serializer_name, kwargs in specs:
        with (
            patch.object(api, authorize_name, return_value=actor),
            patch.object(api, query_name, return_value=()),
            patch.object(api, serializer_name, _Projection),
        ):
            response = view.as_view()(_request("get", actor=actor), **kwargs)
        assert response.status_code == 200
        assert response.data == []
