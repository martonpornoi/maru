from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from maru.core.correlation import correlation_id
from maru.core.middleware import CorrelationIdMiddleware


def _response(request: HttpRequest) -> HttpResponse:
    assert correlation_id.get() == request.correlation_id  # type: ignore[attr-defined]
    return HttpResponse()


def test_middleware_accepts_valid_uuid_and_clears_context() -> None:
    expected = "1d8f179f-22e4-4ca5-a181-f70ed0d3a412"
    request = RequestFactory().get("/", HTTP_X_REQUEST_ID=expected)
    middleware = CorrelationIdMiddleware(_response)

    response = middleware(request)

    assert response["X-Request-ID"] == expected
    assert correlation_id.get() is None


def test_middleware_replaces_untrusted_request_id() -> None:
    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="customer@example.com")
    middleware = CorrelationIdMiddleware(_response)

    response = middleware(request)

    assert str(UUID(response["X-Request-ID"])) == response["X-Request-ID"]
    assert response["X-Request-ID"] != "customer@example.com"
