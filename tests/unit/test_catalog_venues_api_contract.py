from functools import cache
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.catalog.api import CatalogActivateApi, CatalogDetailApi
from maru.catalog.serializers import (
    CatalogOrderCreateSerializer,
    CatalogVariantAddSerializer,
)
from maru.catalog.urls import urlpatterns as catalog_urlpatterns
from maru.identity.models import Account
from maru.venues.api import MyMaruVenueScheduleView, VenueBookingCommandView
from maru.venues.serializers import (
    VenueAvailabilitySetSerializer,
    VenueBookingCreateSerializer,
    VenueBookingUpdateSerializer,
    VenueLayoutApproveSerializer,
    VenueMediaApproveSerializer,
    VenueSpaceCatalogCreateSerializer,
    VenueSpaceSelectionCreateSerializer,
)
from maru.venues.services import VenueAuthorizationDeniedError
from maru.venues.urls import urlpatterns as venue_urlpatterns

CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="catalog-venue-contract@example.test",
        is_active=True,
    )


@cache
def _schema() -> dict[str, object]:
    return SchemaGenerator(
        patterns=[*catalog_urlpatterns, *venue_urlpatterns]
    ).get_schema(request=None, public=True)


def _operations(prefix: str) -> list[dict[str, object]]:
    schema = _schema()
    paths = schema["paths"]
    assert isinstance(paths, dict)
    return [
        operation
        for path, path_operations in paths.items()
        if str(path).startswith(prefix)
        for operation in path_operations.values()
    ]


def _operation(path: str, method: str) -> dict[str, object]:
    schema = _schema()
    paths = schema["paths"]
    assert isinstance(paths, dict)
    path_operations = paths[path]
    assert isinstance(path_operations, dict)
    operation = path_operations[method]
    assert isinstance(operation, dict)
    return operation


def _component_for_request(operation: dict[str, object]) -> dict[str, object]:
    request_body = operation["requestBody"]
    assert isinstance(request_body, dict)
    content = request_body["content"]
    assert isinstance(content, dict)
    media = content["application/json"]
    assert isinstance(media, dict)
    request_schema = media["schema"]
    assert isinstance(request_schema, dict)
    reference = request_schema["$ref"]
    assert isinstance(reference, str)
    components = _schema()["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    component = schemas[reference.rsplit("/", 1)[-1]]
    assert isinstance(component, dict)
    return component


def _assert_required_idempotency(operation: dict[str, object]) -> None:
    parameters = operation["parameters"]
    assert isinstance(parameters, list)
    header = next(
        parameter for parameter in parameters if parameter["name"] == "Idempotency-Key"
    )
    assert header["in"] == "header"
    assert header["required"] is True
    assert header["schema"] == {
        "type": "string",
        "format": "uuid",
        "pattern": CANONICAL_UUID_PATTERN,
    }


def test_catalog_openapi_types_all_eleven_operations_and_requires_authentication() -> (
    None
):
    prefix = "/api/v1/catalog/"
    operations = _operations(prefix)

    assert len(operations) == 11
    assert len({operation["operationId"] for operation in operations}) == 11
    for operation in operations:
        responses = operation["responses"]
        assert isinstance(responses, dict)
        success = responses["200"]
        assert "content" in success
        assert {} not in operation["security"]

    mutations = [operation for operation in operations if "requestBody" in operation]
    assert len(mutations) == 8
    for operation in mutations:
        _assert_required_idempotency(operation)
        _component_for_request(operation)

    create_operation_ids = {
        "catalog_create_edition_catalog",
        "catalog_add_product",
        "catalog_add_variant",
        "catalog_place_order",
        "catalog_create_payment_intent",
    }
    for operation in mutations:
        responses = operation["responses"]
        assert isinstance(responses, dict)
        assert set(responses) == (
            {"200", "201"}
            if operation["operationId"] in create_operation_ids
            else {"200"}
        )


def test_catalog_openapi_documents_the_finite_stock_pair() -> None:
    path = (
        "/api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/"
        "products/{product_id}/variants/"
    )
    component = _component_for_request(_operation(path, "post"))
    assert component["additionalProperties"] is False
    assert component["dependentRequired"] == {
        "initial_stock": ["stock_ceiling"],
        "stock_ceiling": ["initial_stock"],
    }
    properties = component["properties"]
    assert isinstance(properties, dict)
    for field_name, partner_name in (
        ("initial_stock", "stock_ceiling"),
        ("stock_ceiling", "initial_stock"),
    ):
        field = properties[field_name]
        assert isinstance(field, dict)
        assert field["type"] == "integer"
        assert field["minimum"] == 0
        assert partner_name in field["description"]


def test_venues_openapi_types_all_twenty_one_operations() -> None:
    operations = [
        *_operations("/api/v1/my/"),
        *_operations("/api/v1/organizations/"),
        *_operations("/api/v1/public/"),
    ]
    assert len(operations) == 21
    assert len({operation["operationId"] for operation in operations}) == 21

    mutations = [operation for operation in operations if "requestBody" in operation]
    assert len(mutations) == 16
    for operation in mutations:
        _assert_required_idempotency(operation)
        _component_for_request(operation)
        responses = operation["responses"]
        assert isinstance(responses, dict)
        assert "200" in responses

    create_operation_ids = {
        "venues_create_property",
        "venues_create_space_path",
        "venues_create_space_combination",
        "venues_add_property_media",
        "venues_add_space_layout",
        "venues_create_accommodation_room_type",
        "venues_select_property_for_edition",
        "venues_select_space_for_edition",
        "venues_create_booking",
    }
    for operation in mutations:
        responses = operation["responses"]
        assert isinstance(responses, dict)
        assert set(responses) == (
            {"200", "201"}
            if operation["operationId"] in create_operation_ids
            else {"200"}
        )

    public = _operation(
        "/api/v1/public/organizations/{organization_id}/editions/{edition_id}/"
        "venue-schedule",
        "get",
    )
    assert {} in public["security"]
    for operation in operations:
        responses = operation["responses"]
        assert isinstance(responses, dict)
        assert "content" in responses["200"]
        if operation is not public:
            assert {} not in operation["security"]


def test_venues_openapi_uses_exact_booking_and_review_shapes() -> None:
    bookings = (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "venue-spaces/{space_selection_id}/bookings"
    )
    create = _component_for_request(_operation(bookings, "post"))
    update = _component_for_request(_operation(f"{bookings}/{{booking_id}}", "patch"))
    assert create["additionalProperties"] is False
    assert update["additionalProperties"] is False
    assert "expected_version" not in create["properties"]
    assert "expected_version" in update["required"]

    media = _component_for_request(
        _operation(
            "/api/v1/organizations/{organization_id}/venue-properties/"
            "{property_id}/media/{media_id}/approve",
            "post",
        )
    )
    layout = _component_for_request(
        _operation(
            "/api/v1/organizations/{organization_id}/venue-layouts/{layout_id}/approve",
            "post",
        )
    )
    assert "public_reference" in media["required"]
    assert "approved_reference" in layout["properties"]
    assert "public_reference" not in layout["properties"]


def test_anonymous_catalog_requests_stop_before_malformed_input_or_queries() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    malformed = APIRequestFactory().generic(
        "POST",
        "/api/v1/catalog/current",
        data='{ "malformed":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    with (
        patch("maru.catalog.api.authorize_catalog_edition_api_scope") as authorize,
        patch("maru.catalog.api.create_catalog") as command,
    ):
        response = CatalogDetailApi.as_view()(
            malformed,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.status_code == 403
    authorize.assert_not_called()
    command.assert_not_called()

    unknown_query = APIRequestFactory().get("/api/v1/catalog/current?unknown=1")
    with (
        patch("maru.catalog.api.available_products_for_actor") as query,
        patch("maru.catalog.api.EditionCatalog.objects.get") as catalog_query,
    ):
        response = CatalogDetailApi.as_view()(
            unknown_query,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.status_code == 403
    query.assert_not_called()
    catalog_query.assert_not_called()


@pytest.mark.parametrize(("replayed", "expected_status"), [(False, 201), (True, 200)])
def test_catalog_create_uses_distinct_creation_and_replay_statuses(
    replayed: bool, expected_status: int
) -> None:
    request = APIRequestFactory().post(
        "/api/v1/catalog/current",
        data={"currency": "EUR", "reason": "Create the exact edition catalog."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=_actor())
    result = SimpleNamespace(
        target_id=uuid4(),
        resulting_version=1,
        replayed=replayed,
    )
    with (
        patch("maru.catalog.api.authorize_catalog_edition_api_scope"),
        patch("maru.catalog.api.create_catalog", return_value=result),
    ):
        response = CatalogDetailApi.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )
    assert response.status_code == expected_status


def test_catalog_and_venues_reject_whitespace_padded_idempotency_keys() -> None:
    actor = _actor()
    catalog_request = APIRequestFactory().post(
        "/api/v1/catalog/current/activate",
        data={"expected_version": 1, "reason": "Activate the reviewed catalog."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f" {uuid4()} ",
    )
    force_authenticate(catalog_request, user=actor)
    with (
        patch("maru.catalog.api.authorize_catalog_edition_api_scope"),
        patch("maru.catalog.api.activate_catalog") as catalog_command,
    ):
        response = CatalogActivateApi.as_view()(
            catalog_request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )
    assert response.status_code == 400
    catalog_command.assert_not_called()

    venue_request = APIRequestFactory().post(
        "/api/v1/venues/bookings/current/commands/approve",
        data={"expected_version": 1, "reason": "Approve independently."},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f" {uuid4()} ",
    )
    force_authenticate(venue_request, user=actor)
    with (
        patch("maru.venues.api._authorize_space", return_value=actor),
        patch("maru.venues.api.approve_venue_booking") as venue_command,
    ):
        response = VenueBookingCommandView.as_view()(
            venue_request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            space_selection_id=uuid4(),
            booking_id=uuid4(),
            action="approve",
        )
    assert response.status_code == 400
    venue_command.assert_not_called()


def test_catalog_order_lines_and_venue_nested_inputs_are_strict() -> None:
    order = CatalogOrderCreateSerializer(
        data={
            "expected_version": 1,
            "lines": [{"variant_id": str(uuid4()), "quantity": 1, "unknown": True}],
        }
    )
    assert not order.is_valid()
    assert "unknown" in order.errors["lines"][0]

    capacity = VenueSpaceSelectionCreateSerializer(
        data={
            "venue_selection_id": str(uuid4()),
            "source_space_id": str(uuid4()),
            "local_name": "Grand hall",
            "capacity": {
                "configuration_name": "Theatre",
                "seated_capacity": 100,
                "standing_capacity": 150,
                "table_capacity": 80,
                "fire_capacity": 160,
                "unknown": True,
            },
            "reason": "Select the reviewed room configuration.",
        }
    )
    assert not capacity.is_valid()
    assert "unknown" in capacity.errors["capacity"]

    availability = VenueAvailabilitySetSerializer(
        data={
            "expected_version": 1,
            "intervals": [
                {
                    "starts_at": "2026-08-10T08:00:00Z",
                    "ends_at": "2026-08-10T18:00:00Z",
                    "unknown": True,
                }
            ],
            "reason": "Set the confirmed opening window.",
        }
    )
    assert not availability.is_valid()
    assert "unknown" in availability.errors["intervals"][0]


def test_catalog_stock_pair_and_venue_closed_shapes_validate_directly() -> None:
    base_variant = {
        "expected_version": 1,
        "reason": "Add the reviewed variant.",
        "sku": "shirt-blue",
        "name": "Blue shirt",
        "price_minor": 2500,
    }
    assert CatalogVariantAddSerializer(data=base_variant).is_valid()
    assert CatalogVariantAddSerializer(
        data={**base_variant, "initial_stock": 10, "stock_ceiling": 20}
    ).is_valid()
    for partial_stock in (
        {"initial_stock": 10},
        {"stock_ceiling": 20},
        {"initial_stock": None, "stock_ceiling": None},
    ):
        assert not CatalogVariantAddSerializer(
            data={**base_variant, **partial_stock}
        ).is_valid()

    invalid_kind = VenueSpaceCatalogCreateSerializer(
        data={
            "site_code": "main",
            "site_name": "Main site",
            "building_code": "hall",
            "building_name": "Hall",
            "space_code": "room",
            "space_name": "Room",
            "space_kind": "invented",
            "configuration_code": "theatre",
            "configuration_name": "Theatre",
            "seated_capacity": 20,
            "standing_capacity": 30,
            "table_capacity": 10,
            "fire_capacity": 30,
            "reason": "Add the physical room.",
        }
    )
    assert not invalid_kind.is_valid()
    assert "space_kind" in invalid_kind.errors

    assert "expected_version" not in VenueBookingCreateSerializer().fields
    assert VenueBookingUpdateSerializer().fields["expected_version"].required
    assert VenueMediaApproveSerializer().fields["public_reference"].required
    assert "approved_reference" in VenueLayoutApproveSerializer().fields
    assert "public_reference" not in VenueLayoutApproveSerializer().fields


def test_my_schedule_denial_precedes_unknown_query_validation() -> None:
    actor = _actor()
    request = APIRequestFactory().get("/api/v1/my/schedule?unknown=1")
    force_authenticate(request, user=actor)
    with (
        patch(
            "maru.venues.api.authorize_my_maru_schedule_scope",
            side_effect=VenueAuthorizationDeniedError,
        ) as authorize,
        patch("maru.venues.api.my_maru_schedule_for_edition") as query,
    ):
        response = MyMaruVenueScheduleView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )
    assert response.status_code == 403
    authorize.assert_called_once()
    query.assert_not_called()
