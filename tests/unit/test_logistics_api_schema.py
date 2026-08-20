"""Non-database OpenAPI contracts for the bounded Logistics API."""

from functools import cache
from typing import Any, cast

from drf_spectacular.generators import SchemaGenerator

from maru.logistics.urls import urlpatterns as logistics_urlpatterns

CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
RESTRICTED_CONTACT_PATH = (
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "restricted-addresses/{address_id}/read"
)
OFFER_REVIEW_PATH = (
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
    "equipment-offers/{offer_id}/review"
)
CREATE_PATHS = {
    "/api/v1/my/organizations/{organization_id}/editions/{edition_id}/equipment-offers",
    "/api/v1/organizations/{organization_id}/logistics/parties",
    "/api/v1/organizations/{organization_id}/logistics/restricted-addresses",
    "/api/v1/organizations/{organization_id}/logistics/nodes",
    "/api/v1/organizations/{organization_id}/logistics/assets",
    "/api/v1/organizations/{organization_id}/logistics/stock-lots",
    "/api/v1/organizations/{organization_id}/logistics/physical-keys",
    "/api/v1/organizations/{organization_id}/logistics/labels",
    "/api/v1/organizations/{organization_id}/logistics/agreements",
    "/api/v1/organizations/{organization_id}/logistics/kits",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "restricted-addresses",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/nodes",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/assets",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "stock-lots",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "physical-keys",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "agreements",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/events",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests",
    "/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/"
    "offline-batches",
}


@cache
def _schema() -> dict[str, Any]:
    patterns = [
        pattern for pattern in logistics_urlpatterns if "api/" in str(pattern.pattern)
    ]
    return cast(
        "dict[str, Any]",
        SchemaGenerator(patterns=patterns).get_schema(request=None, public=True),
    )


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_operations in _schema()["paths"].items():
        for method, operation in path_operations.items():
            operations.append((path, method, cast("dict[str, Any]", operation)))
    return operations


def _operation(path: str, method: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _schema()["paths"][path][method])


def _resolve_component(reference: dict[str, Any]) -> dict[str, Any]:
    name = cast("str", reference["$ref"]).rsplit("/", maxsplit=1)[-1]
    return cast("dict[str, Any]", _schema()["components"]["schemas"][name])


def _assert_typed_schema(schema: dict[str, Any]) -> None:
    assert "$ref" in schema or (
        schema.get("type") == "array"
        and isinstance(schema.get("items"), dict)
        and "$ref" in schema["items"]
    )


def test_logistics_openapi_types_all_thirty_two_authenticated_operations() -> None:
    operations = _operations()

    assert len(operations) == 32
    assert len({operation["operationId"] for _, _, operation in operations}) == 32
    assert sum(method == "get" for _, method, _ in operations) == 6
    assert sum(method == "post" for _, method, _ in operations) == 26

    for _path, _method, operation in operations:
        security = operation["security"]
        assert {"cookieAuth": []} in security
        assert {} not in security
        for status_code, response in operation["responses"].items():
            if str(status_code).startswith("2"):
                schema = response["content"]["application/json"]["schema"]
                _assert_typed_schema(cast("dict[str, Any]", schema))


def test_logistics_openapi_types_exact_request_and_retry_boundaries() -> None:
    operations = _operations()
    mutations = [item for item in operations if item[1] == "post"]

    assert len(mutations) == 26
    for path, method, operation in operations:
        if method == "post":
            request_schema = operation["requestBody"]["content"]["application/json"][
                "schema"
            ]
            assert "$ref" in request_schema
        else:
            assert "requestBody" not in operation

        retry_headers = [
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
        ]
        if path == RESTRICTED_CONTACT_PATH or method == "get":
            assert retry_headers == []
        else:
            assert len(retry_headers) == 1
            assert retry_headers[0]["required"] is True
            assert retry_headers[0]["schema"] == {
                "type": "string",
                "format": "uuid",
                "pattern": CANONICAL_UUID_PATTERN,
            }


def test_logistics_openapi_distinguishes_create_replay_from_commands() -> None:
    mutations = [item for item in _operations() if item[1] == "post"]

    assert len(CREATE_PATHS) == 19
    for path, _method, operation in mutations:
        assert set(operation["responses"]) == (
            {"200", "201"} if path in CREATE_PATHS else {"200"}
        )


def test_logistics_offer_review_is_action_discriminated() -> None:
    request_reference = _operation(OFFER_REVIEW_PATH, "post")["requestBody"]["content"][
        "application/json"
    ]["schema"]
    request_schema = _resolve_component(cast("dict[str, Any]", request_reference))

    assert len(request_schema["oneOf"]) == 2
    assert set(request_schema["discriminator"]["mapping"]) == {
        "accepted",
        "rejected",
    }

    variants = {
        name: _resolve_component(cast("dict[str, Any]", reference))
        for name, reference in zip(
            ("accepted", "rejected"),
            request_schema["oneOf"],
            strict=True,
        )
    }
    assert "responsible_department_id" in variants["accepted"]["required"]
    assert "responsible_department_id" not in variants["rejected"]["properties"]
