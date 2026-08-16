"""Narrow postprocessing rules for Maru's generated OpenAPI contract."""

from __future__ import annotations

from typing import Any, Final

CANONICAL_UUID_PATTERN: Final = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
CANONICAL_UUID_SCHEMA: Final[dict[str, str]] = {
    "type": "string",
    "format": "uuid",
    "pattern": CANONICAL_UUID_PATTERN,
}

CLOSED_REQUEST_OPERATION_ID_PREFIXES: Final[tuple[str, ...]] = (
    "applications_",
    "catalog_",
    "charities_",
    "my_organizations_editions_equipment_offers_",
    "organizations_editions_equipment_offers_",
    "organizations_editions_logistics_",
    "organizations_logistics_",
    "venues_",
)

REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS: Final[frozenset[str]] = frozenset(
    {
        "applications_command_definition",
        "charities_command_media",
        "charities_command_selection",
        "charities_update_partner",
        "organizations_editions_equipment_offers_review_create",
        "venues_update_property",
    }
)

PATCH_REQUEST_COMPONENT_RULES: Final[dict[str, tuple[frozenset[str], int]]] = {
    "charities_update_partner": (frozenset({"expected_version", "reason"}), 3),
    "venues_update_property": (frozenset({"expected_version", "reason"}), 3),
}


def _component_for_reference(
    schema: dict[str, Any],
    components: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    reference = schema.get("$ref")
    prefix = "#/components/schemas/"
    if not isinstance(reference, str):
        return None
    if not reference.startswith(prefix):
        raise RuntimeError(f"Unsupported local OpenAPI reference {reference!r}.")
    name = reference.removeprefix(prefix)
    component = components.get(name)
    if not isinstance(component, dict):
        raise TypeError(f"OpenAPI component {name!r} is unavailable.")
    return name, component


def _schema_is_object(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    return (
        "properties" in schema
        or schema_type == "object"
        or (isinstance(schema_type, list) and "object" in schema_type)
    )


def _close_request_objects(
    schema: dict[str, Any],
    components: dict[str, Any],
    visited_components: set[str],
) -> None:
    resolved = _component_for_reference(schema, components)
    if resolved is not None:
        name, component = resolved
        if name in visited_components:
            return
        visited_components.add(name)
        _close_request_objects(component, components, visited_components)
        return

    if _schema_is_object(schema) and "additionalProperties" not in schema:
        schema["additionalProperties"] = False

    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            for alternative in alternatives:
                if isinstance(alternative, dict):
                    _close_request_objects(
                        alternative,
                        components,
                        visited_components,
                    )

    items = schema.get("items")
    if isinstance(items, dict):
        _close_request_objects(items, components, visited_components)

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for property_schema in properties.values():
            if isinstance(property_schema, dict):
                _close_request_objects(
                    property_schema,
                    components,
                    visited_components,
                )


def _require_patch_controls(
    *,
    operation_id: str,
    request_schema: dict[str, Any],
    components: dict[str, Any],
) -> None:
    rule = PATCH_REQUEST_COMPONENT_RULES.get(operation_id)
    if rule is None:
        return
    required_controls, minimum_properties = rule
    resolved = _component_for_reference(request_schema, components)
    if resolved is None:
        raise RuntimeError(
            f"OpenAPI operation {operation_id!r} no longer uses one component."
        )
    _name, component = resolved
    properties = component.get("properties")
    if not isinstance(properties, dict) or not required_controls <= set(properties):
        raise RuntimeError(
            f"OpenAPI operation {operation_id!r} lost required control fields."
        )
    required = set(component.get("required", [])) | required_controls
    component["required"] = [name for name in properties if name in required]
    component["minProperties"] = minimum_properties


def _json_request_schema(
    *,
    operation_id: str,
    request_body: dict[str, Any],
) -> dict[str, Any]:
    content = request_body.get("content")
    if not isinstance(content, dict):
        raise TypeError(f"OpenAPI operation {operation_id!r} lost its body content.")
    media = content.get("application/json")
    if not isinstance(media, dict):
        raise TypeError(f"OpenAPI operation {operation_id!r} lost its JSON body.")
    request_schema = media.get("schema")
    if not isinstance(request_schema, dict):
        raise TypeError(f"OpenAPI operation {operation_id!r} lost its body schema.")
    return request_schema


def _pattern_path_uuids(operation: dict[str, Any]) -> None:
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list):
        return
    for parameter in parameters:
        if not isinstance(parameter, dict) or parameter.get("in") != "path":
            continue
        parameter_schema = parameter.get("schema")
        if (
            isinstance(parameter_schema, dict)
            and parameter_schema.get("format") == "uuid"
        ):
            parameter_schema["pattern"] = CANONICAL_UUID_PATTERN


def _process_operation(
    *,
    path: object,
    method: object,
    operation: dict[str, Any],
    components: dict[str, Any],
    matched: dict[str, tuple[str, str]],
) -> None:
    _pattern_path_uuids(operation)
    operation_id = operation.get("operationId")
    if not isinstance(operation_id, str):
        return
    request_body = operation.get("requestBody")
    request_schema: dict[str, Any] | None = None
    needs_json_schema = (
        operation_id.startswith(CLOSED_REQUEST_OPERATION_ID_PREFIXES)
        or operation_id in REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS
        or operation_id in PATCH_REQUEST_COMPONENT_RULES
    )
    if needs_json_schema and isinstance(request_body, dict):
        request_schema = _json_request_schema(
            operation_id=operation_id,
            request_body=request_body,
        )
        if operation_id.startswith(CLOSED_REQUEST_OPERATION_ID_PREFIXES):
            _close_request_objects(request_schema, components, set())
        _require_patch_controls(
            operation_id=operation_id,
            request_schema=request_schema,
            components=components,
        )

    if operation_id not in REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS:
        return
    if operation_id in matched:
        raise RuntimeError(f"OpenAPI operation ID {operation_id!r} is duplicated.")
    if not isinstance(request_body, dict) or request_schema is None:
        raise TypeError(f"OpenAPI operation ID {operation_id!r} lost its request body.")
    request_body["required"] = True
    matched[operation_id] = (str(path), str(method))


def require_explicit_domain_request_bodies(
    *,
    result: dict[str, Any],
    generator: object,
    request: object,
    public: bool,
) -> dict[str, Any]:
    """Expose runtime-true strict request contracts and reject schema drift."""

    del request, public
    matched: dict[str, tuple[str, str]] = {}
    paths = result.get("paths")
    if not isinstance(paths, dict):
        raise TypeError("The OpenAPI result has no paths object.")

    component_container = result.get("components")
    if not isinstance(component_container, dict):
        raise TypeError("The OpenAPI result has no components object.")
    components = component_container.get("schemas")
    if not isinstance(components, dict):
        raise TypeError("The OpenAPI result has no component schemas object.")

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            _process_operation(
                path=path,
                method=method,
                operation=operation,
                components=components,
                matched=matched,
            )

    # App-local schema tests deliberately pass a pattern subset. A normal
    # generator resolves the mounted root URL configuration and must contain
    # the complete closed target set.
    if getattr(generator, "patterns", None) is None:
        missing = REQUIRED_JSON_REQUEST_BODY_OPERATION_IDS.difference(matched)
        if missing:
            rendered = ", ".join(sorted(missing))
            raise RuntimeError(
                f"The mounted OpenAPI schema lost required-body operations: {rendered}."
            )

    return result
