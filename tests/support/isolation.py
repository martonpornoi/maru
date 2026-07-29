"""Reusable endpoint assertions for non-disclosure and stable denial shapes."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from django.http import HttpResponse


@dataclass(frozen=True, slots=True)
class EndpointIsolationCase:
    name: str
    request: Callable[[], HttpResponse]
    expected_status: int
    expected_code: str | None = None
    forbidden_values: tuple[str, ...] = ()
    forbid_collection_metadata_on_error: bool = True


def assert_endpoint_isolation(cases: Sequence[EndpointIsolationCase]) -> None:
    """Run a consistent non-disclosure assertion matrix for API endpoints."""

    for case in cases:
        response = case.request()
        rendered = response.content.decode()
        payload = json.loads(rendered) if rendered else {}
        try:
            assert response.status_code == case.expected_status
            if case.expected_code is not None:
                assert payload["code"] == case.expected_code
            for forbidden_value in case.forbidden_values:
                assert forbidden_value not in rendered
            if (
                case.forbid_collection_metadata_on_error
                and response.status_code >= 400
                and isinstance(payload, dict)
            ):
                assert "count" not in payload
                assert "results" not in payload
                assert "next" not in payload
                assert "previous" not in payload
        except AssertionError as error:
            raise AssertionError(
                f"Endpoint isolation case failed: {case.name}"
            ) from error
