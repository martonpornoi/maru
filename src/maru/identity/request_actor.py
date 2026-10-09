"""Public request-principal boundary for native application adapters."""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .models import Account

type RequestActor = Account
"""The existing Identity account accepted from an authenticated request."""


def authenticated_request_actor(request: HttpRequest) -> RequestActor:
    """Return only the actual active authenticated account attached to a request.

    Parameters
    ----------
    request : HttpRequest
        Request whose authentication middleware supplies the current principal.

    Returns
    -------
    RequestActor
        The unchanged account supplied by the request, without an identity lookup
        or substitution. Owning services must still check current scoped authority.

    Raises
    ------
    PermissionDenied
        The request has no active authenticated Identity account.
    """
    actor = getattr(request, "user", None)
    if (
        not isinstance(actor, Account)
        or not actor.is_authenticated
        or not actor.is_active
    ):
        raise PermissionDenied
    return actor
