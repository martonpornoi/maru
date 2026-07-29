"""Consistent RFC 9457-style API problem responses."""

from http import HTTPStatus
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import exception_handler


def problem_exception_handler(
    exception: Exception,
    context: dict[str, Any],
) -> Response | None:
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
        detail = original_data.get("detail", title)
        code_value = original_data.get("code")
        if isinstance(code_value, str):
            code = code_value
        else:
            detail_code = getattr(detail, "code", None)
            if isinstance(detail_code, str):
                code = detail_code
        remaining = {
            key: value
            for key, value in original_data.items()
            if key not in {"detail", "code"}
        }
        if remaining:
            errors = remaining
    elif original_data:
        errors = original_data

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
    response["Content-Type"] = "application/problem+json"
    return response
