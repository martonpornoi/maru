"""Low-write session inventory tracking."""

from collections.abc import Callable
from datetime import timedelta

from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from maru.identity.models import Account, AccountSession
from maru.identity.services import inventory_session, session_key_digest


class AccountSessionInventoryMiddleware:
    """Refresh a signed-in session inventory record at most every five minutes."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize the AccountSessionInventoryMiddleware instance.

        Parameters
        ----------
        get_response : Callable[[HttpRequest], HttpResponse]
            The callback invoked to get response.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Invoke the configured operation.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        HttpResponse
            The HTTP response for the requested operation.
        """
        if isinstance(request.user, Account):
            key = request.session.session_key
            stale_before = timezone.now() - timedelta(minutes=5)
            should_refresh = (
                not key
                or not AccountSession.objects.filter(
                    account=request.user,
                    session_key_digest=session_key_digest(key),
                    revoked_at__isnull=True,
                    last_seen_at__gte=stale_before,
                ).exists()
            )
            if should_refresh:
                inventory_session(account=request.user, request=request)
        return self.get_response(request)
