"""Local-only trial launcher; the normal application still owns every sign-in."""

import json
import os
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from maru.demo.convention_plan import (
    ACCOUNT_KEYS,
    CONTENT_ROLES,
    SCENARIOS,
    account_identity,
)


@never_cache
@require_safe
def convention_demo(request: HttpRequest) -> HttpResponse:
    """Show generated practice credentials only inside an explicit loopback preview.

    Parameters
    ----------
    request : HttpRequest
        Browser request; non-loopback peers and hosts are refused.

    Returns
    -------
    HttpResponse
        A non-cacheable trial page, without authentication or authorization bypass.

    Raises
    ------
    Http404
        If the local preview has not completed preparation or its context differs.
    """
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "maru.settings.local"
        or os.environ.get("MARU_SYNTHETIC_CONVENTION_DEMO") != "true"
        or not settings.DEBUG
        or request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}
        or request.get_host().split(":")[0] not in {"127.0.0.1", "localhost"}
    ):
        raise Http404
    try:
        manifest = json.loads(os.environ["MARU_DEMO_MANIFEST"])
        passwords = json.loads(os.environ["MARU_DEMO_PASSWORDS"])
        if (
            manifest["schema_version"] != 1
            or manifest["synthetic_only"] is not True
            or tuple(edition["key"] for edition in manifest["editions"]) != SCENARIOS
            or set(passwords) != set(ACCOUNT_KEYS)
        ):
            raise Http404
        editions = []
        for edition in manifest["editions"]:
            scope = {
                "organization_id": UUID(edition["organization_id"]),
                "edition_id": UUID(edition["edition_id"]),
            }
            roles = []
            for role in CONTENT_ROLES:
                key = f"{edition['key']}-{role}"
                destination = reverse(
                    "guidance-library" if role == "reader" else ("guidance-work"),
                    kwargs=scope,
                )
                roles.append(
                    {
                        "key": key,
                        "name": role.title(),
                        "email": account_identity(key)[1],
                        "password": passwords[key],
                        "sign_in": reverse("staff-login")
                        + "?"
                        + urlencode({"next": destination}),
                    }
                )
            editions.append(
                {
                    **edition,
                    "roles": roles,
                    "guides": reverse("guidance-library", kwargs=scope),
                    "announcements": reverse("announcements-inventory", kwargs=scope),
                }
            )
    except (KeyError, TypeError, ValueError) as error:
        raise Http404 from error
    response = render(
        request, "demo/convention.html", {"manifest": manifest, "editions": editions}
    )
    # Keep same-origin logout POSTs compatible with CSRF origin checking while
    # withholding referrers on cross-origin navigation.
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    return response
