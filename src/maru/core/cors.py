"""Exact-origin credentialed CORS for approved headless registration clients."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers

ALLOWED_METHODS = "GET, POST, PUT, OPTIONS"
ALLOWED_HEADERS = "Accept, Content-Type, Idempotency-Key, X-CSRFToken, X-Request-ID"
PRIVATE_API_DOCUMENTATION_PATHS = frozenset(
    {
        "/api/v1/schema",
        "/api/v1/docs",
        "/api/v1/redoc",
    }
)


class RegistrationClientCorsMiddleware:
    """Expose versioned APIs only to deployment-approved browser origins."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        origin = request.headers.get("Origin", "")
        allowed = origin in set(settings.MARU_REGISTRATION_CLIENT_ORIGINS)
        is_api = (
            request.path.startswith("/api/v1/")
            and request.path.rstrip("/") not in PRIVATE_API_DOCUMENTATION_PATHS
        )
        if request.method == "OPTIONS" and is_api and allowed:
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if is_api and allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = ALLOWED_METHODS
            response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
            response["Access-Control-Max-Age"] = "600"
            patch_vary_headers(response, ("Origin",))
        return response
