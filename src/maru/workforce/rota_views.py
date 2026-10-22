"""Authenticated portable and printable rota adapters with final read admission."""

from __future__ import annotations

import logging
from uuid import UUID
from zoneinfo import ZoneInfoNotFoundError

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from maru.events.admin_context import authorized_admin_edition_identity_for_route
from maru.identity.models import Account
from maru.workforce.rota import (
    MAX_ROTA_BYTES,
    RotaUnavailableError,
    _prepare_rota,
    _release_rota,
    rota_package,
)

logger = logging.getLogger(__name__)


def _response(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    *,
    representation: str,
) -> HttpResponse:
    actor = request.user
    if not isinstance(actor, Account):
        return HttpResponse(
            "Access unavailable.", status=403, content_type="text/plain"
        )
    if request.GET:
        return HttpResponse(
            "This page does not accept URL parameters.",
            status=400,
            content_type="text/plain",
        )
    try:
        organization_id, _series_id, edition_id = (
            authorized_admin_edition_identity_for_route(
                request=request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                capability_code="workforce.view_shifts",
            )
        )
        snapshot = _prepare_rota(
            actor=actor, organization_id=organization_id, edition_id=edition_id
        )
        route = {
            "organization_slug": organization_slug,
            "series_slug": series_slug,
            "edition_slug": edition_slug,
        }
        html = render_to_string("workforce/rota.html", {"rota": snapshot.payload})
        if representation == "download":
            content = rota_package(snapshot=snapshot, printable_html=html)
            response = HttpResponse(content, content_type="application/zip")
            response["Content-Disposition"] = (
                f'attachment; filename="workforce-rota-{edition_id}.zip"'
            )
        else:
            html = render_to_string(
                "workforce/rota.html",
                {
                    "rota": snapshot.payload,
                    "back_url": reverse("organization-workforce-shifts", kwargs=route),
                },
            )
            if len(html.encode("utf-8")) > MAX_ROTA_BYTES:
                raise RotaUnavailableError
            response = HttpResponse(html, content_type="text/html; charset=utf-8")
        _release_rota(
            actor=actor,
            snapshot=snapshot,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            representation=representation,
        )
    except (PermissionDenied, Account.DoesNotExist):
        return HttpResponse(
            "Access unavailable.", status=403, content_type="text/plain"
        )
    except Http404:
        return HttpResponse(
            "Resource unavailable.", status=404, content_type="text/plain"
        )
    except (
        DatabaseError,
        RuntimeError,
        ValidationError,
        ValueError,
        ZoneInfoNotFoundError,
    ):
        logger.exception("Unable to produce complete Workforce rota")
        return HttpResponse(
            (
                "The complete rota is unavailable. "
                "Return to Shift planning and try again later."
            ),
            status=503,
            content_type="text/plain",
        )
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )
    patch_vary_headers(response, ("Cookie",))
    return response


@never_cache
@login_required(login_url="staff-login")
@require_GET
def download_workforce_rota(
    request: HttpRequest, organization_slug: str, series_slug: str, edition_slug: str
) -> HttpResponse:
    """Download the exact-edition rota package after current field checks and audit.

    Parameters
    ----------
    request : HttpRequest
        Authenticated session and server-owned correlation.
    organization_slug : str
        Exact organization route locator.
    series_slug : str
        Exact parent series route locator.
    edition_slug : str
        Complete exact-edition route chain, never a selected-context shortcut.

    Returns
    -------
    HttpResponse
        Private ZIP or a name-free denied, invalid or unavailable response.
    """
    return _response(
        request, organization_slug, series_slug, edition_slug, representation="download"
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def print_workforce_rota(
    request: HttpRequest, organization_slug: str, series_slug: str, edition_slug: str
) -> HttpResponse:
    """Render the same minimized snapshot as accessible, self-contained print HTML.

    Parameters
    ----------
    request : HttpRequest
        Authenticated session and server-owned correlation.
    organization_slug : str
        Exact organization route locator.
    series_slug : str
        Exact parent series route locator.
    edition_slug : str
        Complete independently admitted route chain.

    Returns
    -------
    HttpResponse
        Private rendered HTML or a bounded failure without partial names.
    """
    return _response(
        request, organization_slug, series_slug, edition_slug, representation="print"
    )
