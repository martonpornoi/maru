"""HTTP middleware shared by all API modules."""

from typing import ClassVar
from uuid import UUID, uuid4

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

from maru.core.correlation import correlation_id


def _safe_request_id(candidate: str | None) -> str:
    if candidate is not None:
        try:
            return str(UUID(candidate))
        except ValueError:
            pass
    return str(uuid4())


class CorrelationIdMiddleware(MiddlewareMixin):
    """Assign one safe request identifier and return it to the client."""

    header_name: ClassVar[str] = "HTTP_X_REQUEST_ID"
    response_header: ClassVar[str] = "X-Request-ID"

    def process_request(self, request: HttpRequest) -> None:
        """Attach a correlation identifier to the incoming request.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        """
        request_id = _safe_request_id(request.META.get(self.header_name))
        request.correlation_id = request_id  # type: ignore[attr-defined]
        request.maru_correlation_token = correlation_id.set(request_id)  # type: ignore[attr-defined]

    def process_response(
        self,
        request: HttpRequest,
        response: HttpResponse,
    ) -> HttpResponse:
        """Expose the request correlation identifier on the response.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        response : HttpResponse
            The HTTP response before policy headers or content are finalized.

        Returns
        -------
        HttpResponse
            The HTTP response for the requested operation.
        """
        request_id = getattr(request, "correlation_id", str(uuid4()))
        response[self.response_header] = request_id
        token = getattr(request, "maru_correlation_token", None)
        if token is not None:
            correlation_id.reset(token)
        return response
