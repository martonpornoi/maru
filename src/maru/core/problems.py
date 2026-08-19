"""Consistent RFC 9457-style API problem responses."""

from http import HTTPStatus
from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DependencyUnavailable(APIException):
    """Safe public boundary for a temporary canonical dependency failure."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "A required Maru service is temporarily unavailable."
    default_code = "service_unavailable"


def _first_error_code(value: object) -> str | None:
    direct_code = getattr(value, "code", None)
    if isinstance(direct_code, str):
        return direct_code
    if isinstance(value, dict):
        for nested in value.values():
            if code := _first_error_code(nested):
                return code
    if isinstance(value, (list, tuple)):
        for nested in value:
            if code := _first_error_code(nested):
                return code
    return None


def _mapping_problem_parts(
    original_data: dict[object, object],
    *,
    title: str,
) -> tuple[object, object | None, str]:
    detail = original_data.get("detail", title)
    code = "request_failed"
    code_value = original_data.get("code")
    if isinstance(code_value, str):
        code = code_value
    else:
        detail_code = getattr(detail, "code", None)
        if isinstance(detail_code, str):
            code = detail_code
        elif nested_code := _first_error_code(original_data):
            code = nested_code

    explicit_errors = original_data.get("errors")
    remaining = {
        key: value
        for key, value in original_data.items()
        if key not in {"detail", "code", "errors"}
    }
    errors: object | None = None
    if explicit_errors is not None and remaining:
        errors = {"fields": remaining, "general": explicit_errors}
    elif explicit_errors is not None:
        errors = explicit_errors
    elif remaining:
        errors = remaining
    return detail, errors, code


def problem_exception_handler(
    exception: Exception,
    context: dict[str, Any],
) -> Response | None:
    """Translate a DRF exception into Maru's RFC 9457 problem response.

    Parameters
    ----------
    exception : Exception
        The exception translated into the canonical problem response.
    context : dict[str, Any]
        The resolved context for the operation.

    Returns
    -------
    Response | None
        The HTTP response for this request.
    """
    response = exception_handler(exception, context)
    if response is None:
        return None

    request = context.get("request")
    request_id = (
        getattr(request, "correlation_id", None)
        if isinstance(request, Request)
        else None
    )
    status_code = response.status_code
    title = HTTPStatus(status_code).phrase
    original_data = response.data

    detail: object = title
    errors: object | None = None
    code = "request_failed"

    if isinstance(original_data, dict):
        detail, errors, code = _mapping_problem_parts(
            original_data,
            title=title,
        )
    elif original_data:
        errors = original_data
        if nested_code := _first_error_code(original_data):
            code = nested_code

    problem: dict[str, object] = {
        "type": f"https://docs.maru.invalid/problems/{code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if request_id:
        problem["request_id"] = request_id
    if errors is not None:
        problem["errors"] = errors

    response.data = problem
    response.content_type = "application/problem+json"
    return response
