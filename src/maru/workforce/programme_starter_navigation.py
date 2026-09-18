"""Independently admitted contextual entry to the dormant starter workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.workforce.programme_starter_creation import load_programme_starter_creation
from maru.workforce.programme_starter_views import programme_starter_workspace

if TYPE_CHECKING:
    from django.http import HttpRequest

    from maru.identity.models import Account
    from maru.workforce.programme_starter_inputs import ProgrammeStarterScope


def programme_starter_entry_url(
    *, request: HttpRequest, actor: Account, scope: ProgrammeStarterScope
) -> str:
    """Offer a contextual link only to the real mounted and admitted owner view.

    Parameters
    ----------
    request : HttpRequest
        Current request and its actual URL configuration.
    actor : Account
        Actual signed-in controller, never a substituted platform identity.
    scope : ProgrammeStarterScope
        Independently selected exact organization, series and edition.

    Returns
    -------
    str
        Own-request inventory URL after audited owner admission, or an empty
        string for absent routes, denied authority or unavailable dependencies.

    Notes
    -----
    A link does not grant access. The destination reauthorizes every request.
    No private request inventory or other person's selection is loaded here.
    """
    urlconf = getattr(request, "urlconf", None)
    try:
        url = reverse(
            "programme-volunteer-starter",
            kwargs={
                "organization_id": scope.organization_id,
                "series_id": scope.series_id,
                "edition_id": scope.edition_id,
            },
            urlconf=urlconf,
        )
        if resolve(url, urlconf=urlconf).func is not programme_starter_workspace:
            return ""
        load_programme_starter_creation(
            actor=actor, scope=scope, correlation_id=uuid4(), source_channel="html"
        )
    except (
        NoReverseMatch,
        Resolver404,
        PermissionDenied,
        ValidationError,
        DatabaseError,
    ):
        return ""
    return url
