import pytest
from django.http import JsonResponse

from tests.support.isolation import (
    EndpointIsolationCase,
    assert_endpoint_isolation,
)


def test_isolation_harness_detects_a_protected_value_leak() -> None:
    case = EndpointIsolationCase(
        name="deliberately unsafe fixture",
        request=lambda: JsonResponse({"results": [{"name": "Protected Event"}]}),
        expected_status=200,
        forbidden_values=("Protected Event",),
    )

    with pytest.raises(
        AssertionError,
        match="deliberately unsafe fixture",
    ):
        assert_endpoint_isolation([case])


def test_isolation_harness_detects_count_metadata_on_denial() -> None:
    case = EndpointIsolationCase(
        name="unsafe denied count",
        request=lambda: JsonResponse(
            {"code": "permission_absent", "count": 1},
            status=403,
        ),
        expected_status=403,
        expected_code="permission_absent",
    )

    with pytest.raises(AssertionError, match="unsafe denied count"):
        assert_endpoint_isolation([case])
