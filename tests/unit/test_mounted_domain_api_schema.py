"""Repository-level OpenAPI contracts for the newly mounted domain APIs."""

from collections.abc import Callable
from typing import Any, cast

import pytest
from drf_spectacular.generators import SchemaGenerator

from maru.core.openapi import (
    CANONICAL_UUID_PATTERN,
    REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS,
)

HTTP_METHODS = frozenset({"delete", "get", "patch", "post", "put"})
MUTATION_METHODS = frozenset({"delete", "patch", "post", "put"})
APPLICATION_PREFIX = (
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/applications"
)
CHARITY_PUBLIC_PATH = (
    "/api/v1/public/organizations/{organization_id}/editions/{edition_id}/charities"
)
CATALOG_PREFIX = "/api/v1/catalog/"
VENUE_PUBLIC_PATH = (
    "/api/v1/public/organizations/{organization_id}/editions/{edition_id}/"
    "venue-schedule"
)
VENUE_MY_PATH = (
    "/api/v1/my/organizations/{organization_id}/editions/{edition_id}/venue-schedule"
)
APPLICATION_BODYLESS_MUTATION = (
    f"{APPLICATION_PREFIX}/definitions/{{definition_id}}/submissions",
    "post",
)
LOGISTICS_RESTRICTED_CONTACT_READ = (
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "restricted-addresses/{address_id}/read",
    "post",
)

EXPECTED_OPERATION_COUNTS = {
    "applications": 10,
    "charities": 10,
    "catalog": 11,
    "venues": 21,
    "logistics": 32,
}
EXPECTED_MUTATION_COUNTS = {
    "applications": 6,
    "charities": 6,
    "catalog": 8,
    "venues": 16,
    "logistics": 25,
}
EXPECTED_REQUEST_BODY_COUNTS = {
    "applications": 5,
    "charities": 6,
    "catalog": 8,
    "venues": 16,
    "logistics": 26,
}
EXPECTED_CLOSED_REQUEST_COMPONENTS = frozenset(
    {
        "CharityPartnerCreate",
        "DefinitionConfigure",
        "LogisticsCatalogSubjectLocator",
        "LogisticsMovementSubjectLocator",
        "Movement",
        "OfferItemInput",
        "PatchedCharityPartnerUpdate",
        "PatchedVenuePropertyUpdate",
        "QuestionCondition",
        "QuestionOption",
        "StarterCreate",
        "SubmissionAnswer",
    }
)


def _is_application_path(path: str) -> bool:
    return path.startswith(APPLICATION_PREFIX)


def _is_charity_path(path: str) -> bool:
    return (
        path == CHARITY_PUBLIC_PATH
        or "/charity-partners" in path
        or "/charity-selections" in path
    )


def _is_catalog_path(path: str) -> bool:
    return path.startswith(CATALOG_PREFIX)


def _is_venue_path(path: str) -> bool:
    if path in {VENUE_PUBLIC_PATH, VENUE_MY_PATH}:
        return True
    if not path.startswith("/api/v1/organizations/{organization_id}/"):
        return False
    return path.endswith("/editions/{edition_id}/venues") or any(
        fragment in path
        for fragment in (
            "/accommodation-room-types/",
            "/venue-layouts/",
            "/venue-properties",
            "/venue-spaces",
        )
    )


def _is_logistics_path(path: str) -> bool:
    return "/logistics" in path or "/equipment-offers" in path


MODULE_PATH_PREDICATES: dict[str, Callable[[str], bool]] = {
    "applications": _is_application_path,
    "charities": _is_charity_path,
    "catalog": _is_catalog_path,
    "venues": _is_venue_path,
    "logistics": _is_logistics_path,
}


@pytest.fixture(scope="module")
def mounted_api_schema() -> dict[str, Any]:
    generated = SchemaGenerator().get_schema(
        request=None,
        public=True,
    )
    assert generated is not None
    return cast(dict[str, Any], generated)


def _domain_operations(
    schema: dict[str, Any],
) -> dict[str, list[tuple[str, str, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
        module: [] for module in MODULE_PATH_PREDICATES
    }
    for path, path_item in schema["paths"].items():
        matching_modules = [
            module
            for module, predicate in MODULE_PATH_PREDICATES.items()
            if predicate(path)
        ]
        if not matching_modules:
            continue
        assert len(matching_modules) == 1, (path, matching_modules)
        module = matching_modules[0]
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                grouped[module].append((path, method, cast(dict[str, Any], operation)))
    return grouped


def _assert_typed_schema(schema: dict[str, Any]) -> None:
    if isinstance(schema.get("$ref"), str):
        return
    if any(
        isinstance(schema.get(keyword), list) and bool(schema[keyword])
        for keyword in ("allOf", "anyOf", "oneOf")
    ):
        return

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        assert schema_type
        assert any(item != "null" for item in schema_type)
        return
    assert schema_type in {"array", "boolean", "integer", "number", "object", "string"}
    if schema_type == "array":
        items = schema.get("items")
        assert isinstance(items, dict)
        _assert_typed_schema(items)
    elif schema_type == "object":
        assert "properties" in schema or "additionalProperties" in schema


def _effective_security(
    schema: dict[str, Any],
    operation: dict[str, Any],
) -> list[dict[str, list[str]]]:
    return cast(
        list[dict[str, list[str]]],
        operation.get("security", schema.get("security", [])),
    )


def _request_object_schemas(
    *,
    schema: dict[str, Any],
    request_schema: dict[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], set[str]]:
    components = cast(dict[str, Any], schema["components"]["schemas"])
    objects: list[tuple[str, dict[str, Any]]] = []
    visited_components: set[str] = set()

    def visit(current: dict[str, Any], location: str) -> None:
        reference = current.get("$ref")
        if isinstance(reference, str):
            prefix = "#/components/schemas/"
            assert reference.startswith(prefix), reference
            component_name = reference.removeprefix(prefix)
            if component_name in visited_components:
                return
            visited_components.add(component_name)
            component = components.get(component_name)
            assert isinstance(component, dict), component_name
            visit(component, component_name)
            return

        schema_type = current.get("type")
        if (
            "properties" in current
            or schema_type == "object"
            or (isinstance(schema_type, list) and "object" in schema_type)
        ):
            objects.append((location, current))

        for keyword in ("allOf", "anyOf", "oneOf"):
            alternatives = current.get(keyword, [])
            assert isinstance(alternatives, list), (location, keyword)
            for index, alternative in enumerate(alternatives):
                assert isinstance(alternative, dict), (location, keyword, index)
                visit(alternative, f"{location}.{keyword}[{index}]")

        items = current.get("items")
        if isinstance(items, dict):
            visit(items, f"{location}.items")

        properties = current.get("properties", {})
        assert isinstance(properties, dict), location
        for property_name, property_schema in properties.items():
            assert isinstance(property_schema, dict), (location, property_name)
            visit(property_schema, f"{location}.{property_name}")

    visit(request_schema, "request")
    return objects, visited_components


def _operation_by_id(
    schema: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    matches = [
        operation
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS and operation.get("operationId") == operation_id
    ]
    assert len(matches) == 1, operation_id
    return cast(dict[str, Any], matches[0])


def test_mounted_domain_operations_are_complete_typed_and_correctly_private(
    mounted_api_schema: dict[str, Any],
) -> None:
    grouped = _domain_operations(mounted_api_schema)

    assert {module: len(operations) for module, operations in grouped.items()} == (
        EXPECTED_OPERATION_COUNTS
    )
    operation_ids = [
        operation["operationId"]
        for operations in grouped.values()
        for _path, _method, operation in operations
    ]
    assert len(operation_ids) == sum(EXPECTED_OPERATION_COUNTS.values()) == 84
    assert len(set(operation_ids)) == len(operation_ids)

    for operations in grouped.values():
        for path, _method, operation in operations:
            success_responses = [
                response
                for status, response in operation["responses"].items()
                if str(status).startswith("2")
            ]
            assert success_responses, path
            for response in success_responses:
                content = response.get("content")
                assert isinstance(content, dict), path
                json_content = content.get("application/json")
                assert isinstance(json_content, dict), path
                response_schema = json_content.get("schema")
                assert isinstance(response_schema, dict), path
                _assert_typed_schema(response_schema)

            security = _effective_security(mounted_api_schema, operation)
            if path in {CHARITY_PUBLIC_PATH, VENUE_PUBLIC_PATH}:
                assert not security or {} in security
            else:
                assert {"cookieAuth": []} in security, path
                assert {} not in security, path


def test_mounted_domain_mutations_require_bodies_and_retry_keys(
    mounted_api_schema: dict[str, Any],
) -> None:
    grouped = _domain_operations(mounted_api_schema)
    mutation_counts: dict[str, int] = {}
    request_body_counts: dict[str, int] = {}
    required_body_overrides: set[str] = set()

    for module, operations in grouped.items():
        mutations = [
            item
            for item in operations
            if item[1] in MUTATION_METHODS
            and (item[0], item[1]) != LOGISTICS_RESTRICTED_CONTACT_READ
        ]
        mutation_counts[module] = len(mutations)
        request_body_counts[module] = 0

        for path, method, operation in operations:
            request_body = operation.get("requestBody")
            if method not in MUTATION_METHODS:
                assert request_body is None, (path, method)
                continue

            retry_headers = [
                parameter
                for parameter in operation["parameters"]
                if parameter["in"] == "header"
                and parameter["name"] == "Idempotency-Key"
            ]
            if (path, method) == LOGISTICS_RESTRICTED_CONTACT_READ:
                assert retry_headers == []
            else:
                assert len(retry_headers) == 1, (path, method)
                retry_header = retry_headers[0]
                assert retry_header["required"] is True
                assert retry_header["schema"] == {
                    "type": "string",
                    "format": "uuid",
                    "pattern": CANONICAL_UUID_PATTERN,
                }

            if (path, method) == APPLICATION_BODYLESS_MUTATION:
                assert request_body is None
                continue

            assert isinstance(request_body, dict), (path, method)
            assert request_body["required"] is True
            if operation["operationId"] in REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS:
                required_body_overrides.add(operation["operationId"])
            json_content = request_body["content"]["application/json"]
            request_schema = json_content["schema"]
            assert isinstance(request_schema, dict)
            _assert_typed_schema(request_schema)
            request_body_counts[module] += 1

    assert mutation_counts == EXPECTED_MUTATION_COUNTS
    assert request_body_counts == EXPECTED_REQUEST_BODY_COUNTS
    assert sum(request_body_counts.values()) == 61
    assert required_body_overrides == REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS


def test_mounted_domain_request_objects_are_closed(
    mounted_api_schema: dict[str, Any],
) -> None:
    grouped = _domain_operations(mounted_api_schema)
    checked_bodies = 0
    reached_components: set[str] = set()

    for operations in grouped.values():
        for path, method, operation in operations:
            request_body = operation.get("requestBody")
            if not isinstance(request_body, dict):
                continue
            request_schema = request_body["content"]["application/json"]["schema"]
            assert isinstance(request_schema, dict), (path, method)
            objects, components = _request_object_schemas(
                schema=mounted_api_schema,
                request_schema=request_schema,
            )
            assert objects, (path, method)
            for location, object_schema in objects:
                assert object_schema.get("additionalProperties") is False, (
                    operation["operationId"],
                    location,
                )
            reached_components.update(components)
            checked_bodies += 1

    assert checked_bodies == sum(EXPECTED_REQUEST_BODY_COUNTS.values()) == 61
    assert reached_components >= EXPECTED_CLOSED_REQUEST_COMPONENTS


@pytest.mark.parametrize(
    ("operation_id", "component_name"),
    [
        ("charities_update_partner", "PatchedCharityPartnerUpdate"),
        ("venues_update_property", "PatchedVenuePropertyUpdate"),
    ],
)
def test_partial_updates_preserve_required_controls_and_forbid_no_ops(
    mounted_api_schema: dict[str, Any],
    operation_id: str,
    component_name: str,
) -> None:
    operation = _operation_by_id(mounted_api_schema, operation_id)
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": f"#/components/schemas/{component_name}"}

    component = mounted_api_schema["components"]["schemas"][component_name]
    assert set(component["required"]) == {"expected_version", "reason"}
    assert component["minProperties"] == 3
    assert component["additionalProperties"] is False


def test_domain_uuid_routes_and_canonical_request_fields_are_exact(
    mounted_api_schema: dict[str, Any],
) -> None:
    grouped = _domain_operations(mounted_api_schema)
    uuid_route_parameters = 0
    for operations in grouped.values():
        for path, method, operation in operations:
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "path":
                    continue
                name = parameter["name"]
                if name == "action":
                    continue
                assert name.endswith("_id"), (path, method, name)
                assert parameter["schema"] == {
                    "type": "string",
                    "format": "uuid",
                    "pattern": CANONICAL_UUID_PATTERN,
                }
                uuid_route_parameters += 1
    assert uuid_route_parameters > 0

    schemas = mounted_api_schema["components"]["schemas"]
    canonical_fields = [
        schemas["SubmissionAnswer"]["properties"]["question_id"],
        schemas["DefinitionConfigure"]["properties"]["owner_department_ids"]["items"],
        schemas["LogisticsCatalogSubjectLocator"]["properties"]["object_id"],
        schemas["Movement"]["properties"]["source_node_id"],
    ]
    for field_schema in canonical_fields:
        assert field_schema["format"] == "uuid"
        assert field_schema["pattern"] == CANONICAL_UUID_PATTERN


def test_mounted_logistics_components_keep_distinct_schema_identities(
    mounted_api_schema: dict[str, Any],
) -> None:
    schemas = mounted_api_schema["components"]["schemas"]

    assert schemas["Movement"]["properties"]["subject"] == {
        "$ref": "#/components/schemas/LogisticsMovementSubjectLocator"
    }
    assert schemas["ManifestLineInput"]["properties"]["subject"] == {
        "$ref": "#/components/schemas/LogisticsMovementSubjectLocator"
    }
    assert schemas["AssetAgreementCreate"]["properties"]["subject"] == {
        "$ref": "#/components/schemas/LogisticsCatalogSubjectLocator"
    }
    assert schemas["OfflineBatch"]["properties"]["operations"]["items"] == {
        "$ref": "#/components/schemas/LogisticsOfflineOperation"
    }
    assert {
        "LogisticsMovementSubjectLocator",
        "LogisticsCatalogSubjectLocator",
        "LogisticsOfflineOperation",
        "OfflineOperation",
    } <= set(schemas)
