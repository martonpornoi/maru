from collections.abc import Iterator
from typing import Any, cast

import pytest
from drf_spectacular.generators import SchemaGenerator

from maru.applications.urls import urlpatterns as application_urlpatterns
from maru.charities.urls import urlpatterns as charity_urlpatterns

APPLICATION_OPERATIONS = {
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/starters",
        "get",
    ): "applications_list_starters",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions",
        "get",
    ): "applications_list_definitions",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions",
        "post",
    ): "applications_create_definition",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions/{definition_id}/commands",
        "post",
    ): "applications_command_definition",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/applications/me",
        "get",
    ): "applications_retrieve_my_workspace",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions/{definition_id}/submissions",
        "post",
    ): "applications_start_submission",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/submissions/{submission_id}/answers",
        "post",
    ): "applications_append_answer",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/submissions/{submission_id}/submit",
        "post",
    ): "applications_submit_submission",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/review-queue",
        "get",
    ): "applications_list_review_queue",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/submissions/{submission_id}/review-decisions",
        "post",
    ): "applications_record_review_decision",
}

CHARITY_OPERATIONS = {
    (
        "/api/v1/public/organizations/{organization_id}/editions/{edition_id}/"
        "charities",
        "get",
    ): "charities_list_public",
    (
        "/api/v1/organizations/{organization_id}/charity-partners",
        "get",
    ): "charities_list_partners",
    (
        "/api/v1/organizations/{organization_id}/charity-partners",
        "post",
    ): "charities_create_partner",
    (
        "/api/v1/organizations/{organization_id}/charity-partners/{partner_id}",
        "patch",
    ): "charities_update_partner",
    (
        "/api/v1/organizations/{organization_id}/charity-partners/{partner_id}/media",
        "post",
    ): "charities_add_media",
    (
        "/api/v1/organizations/{organization_id}/charity-partners/{partner_id}/"
        "media/{media_id}/commands/{action}",
        "post",
    ): "charities_command_media",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "charity-selections",
        "get",
    ): "charities_list_selections",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "charity-selections",
        "post",
    ): "charities_propose_selection",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "charity-selections/{selection_id}",
        "get",
    ): "charities_retrieve_selection",
    (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "charity-selections/{selection_id}/commands/{action}",
        "post",
    ): "charities_command_selection",
}


@pytest.fixture(scope="module")
def api_schema() -> dict[str, Any]:
    patterns = [
        pattern
        for pattern in [*application_urlpatterns, *charity_urlpatterns]
        if "api/" in str(pattern.pattern)
    ]
    generator = SchemaGenerator(patterns=patterns)  # type: ignore[no-untyped-call]
    generated = generator.get_schema(  # type: ignore[no-untyped-call]
        request=None,
        public=True,
    )
    return cast(
        dict[str, Any],
        generated,
    )


def _operation(
    schema: dict[str, Any],
    path: str,
    method: str,
) -> dict[str, Any]:
    return cast(dict[str, Any], schema["paths"][path][method])


def _success_response_schemas(operation: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for status_code, response in operation["responses"].items():
        if str(status_code).startswith("2"):
            yield cast(
                dict[str, Any],
                response["content"]["application/json"]["schema"],
            )


def _resolve_component(
    schema: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    name = cast(str, reference["$ref"]).rsplit("/", maxsplit=1)[-1]
    return cast(dict[str, Any], schema["components"]["schemas"][name])


@pytest.mark.parametrize(
    ("path", "method", "operation_id"),
    [
        (*route, operation_id)
        for route, operation_id in {
            **APPLICATION_OPERATIONS,
            **CHARITY_OPERATIONS,
        }.items()
    ],
)
def test_applications_and_charities_operations_have_typed_success_contracts(
    api_schema: dict[str, Any],
    path: str,
    method: str,
    operation_id: str,
) -> None:
    operation = _operation(api_schema, path, method)

    assert operation["operationId"] == operation_id
    success_schemas = list(_success_response_schemas(operation))
    assert success_schemas
    assert all(
        "$ref" in success_schema or success_schema.get("type") == "array"
        for success_schema in success_schemas
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        route
        for route in [*APPLICATION_OPERATIONS, *CHARITY_OPERATIONS]
        if route[1] in {"post", "patch"}
    ],
)
def test_applications_and_charities_mutations_document_required_retry_header(
    api_schema: dict[str, Any],
    path: str,
    method: str,
) -> None:
    parameters = _operation(api_schema, path, method)["parameters"]
    header = next(
        parameter
        for parameter in parameters
        if parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
    )

    assert header["required"] is True
    assert header["schema"]["format"] == "uuid"
    assert header["schema"]["pattern"].startswith("^")


def test_application_submission_start_is_bodyless_in_openapi(
    api_schema: dict[str, Any],
) -> None:
    path = (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions/{definition_id}/submissions"
    )

    assert "requestBody" not in _operation(api_schema, path, "post")


def test_application_definition_command_documents_closed_one_of(
    api_schema: dict[str, Any],
) -> None:
    path = (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "applications/definitions/{definition_id}/commands"
    )
    request_schema = _operation(api_schema, path, "post")["requestBody"]["content"][
        "application/json"
    ]["schema"]
    command_schema = _resolve_component(api_schema, request_schema)

    assert len(command_schema["oneOf"]) == 5
    assert set(command_schema["discriminator"]["mapping"]) == {
        "definition.configure",
        "section.add",
        "question.add",
        "definition.activate",
        "definition.retire",
        "definition.successor",
    }


def test_charity_public_contract_is_anonymous_but_private_contract_is_not(
    api_schema: dict[str, Any],
) -> None:
    public_path = (
        "/api/v1/public/organizations/{organization_id}/editions/{edition_id}/charities"
    )
    private_path = "/api/v1/organizations/{organization_id}/charity-partners"

    assert "security" not in _operation(api_schema, public_path, "get")
    assert _operation(api_schema, private_path, "get")["security"]


def test_charity_media_command_documents_distinct_approve_and_withdraw_inputs(
    api_schema: dict[str, Any],
) -> None:
    path = (
        "/api/v1/organizations/{organization_id}/charity-partners/{partner_id}/"
        "media/{media_id}/commands/{action}"
    )
    operation = _operation(api_schema, path, "post")
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    command_schema = _resolve_component(api_schema, request_schema)
    variants = [
        _resolve_component(api_schema, variant) for variant in command_schema["oneOf"]
    ]
    approve = next(
        variant for variant in variants if "public_reference" in variant["properties"]
    )
    withdraw = next(
        variant
        for variant in variants
        if "public_reference" not in variant["properties"]
    )
    action_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "path" and parameter["name"] == "action"
    )

    assert "public_reference" in approve["required"]
    assert set(withdraw["properties"]) == {"expected_version", "reason"}
    assert set(action_parameter["schema"]["enum"]) == {"approve", "withdraw"}


def test_charity_selection_command_documents_closed_request_variants(
    api_schema: dict[str, Any],
) -> None:
    path = (
        "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        "charity-selections/{selection_id}/commands/{action}"
    )
    operation = _operation(api_schema, path, "post")
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    command_schema = _resolve_component(api_schema, request_schema)
    variant_names = {
        cast(str, item["$ref"]).rsplit("/", maxsplit=1)[-1]
        for item in command_schema["oneOf"]
    }
    action_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "path" and parameter["name"] == "action"
    )

    assert variant_names == {
        "CharitySelectionDecision",
        "CharitySelectionComment",
        "CharitySelectionPublish",
    }
    assert set(action_parameter["schema"]["enum"]) == {
        "submit",
        "confirm",
        "reject",
        "comment",
        "publish",
        "withdraw",
    }
