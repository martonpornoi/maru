"""Dormant shared-shell on-site views and exact freshly admitted signed downloads."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .continuity_presentation import MAX_CONTINUITY_HTML_BYTES, render_continuity_body
from .continuity_protocol import ContinuityInvalidError, ContinuityScope
from .continuity_queries import load_continuity_projection
from .continuity_signing import (
    DEFAULT_CONTINUITY_LIFETIME_SECONDS,
    ContinuitySigningUnavailableError,
    load_continuity_signing_policy,
    sign_continuity_projection,
)
from .operator_output_queries import OPERATOR_OPTIONAL_LAYERS
from .output_rendering import TimetableOutputInvalidError

if TYPE_CHECKING:
    from .continuity_payload import ContinuityProjection

_TITLES = {
    "public": "Programme now and next",
    "exact_person": "My Programme now and next",
    "private_operator": "Programme operator now and next",
}
_TEMPLATES = {
    "public": "scheduling/continuity_public.html",
    "exact_person": "scheduling/continuity_personal.html",
    "private_operator": "scheduling/continuity_operator.html",
}
_LAYERS = {
    "technical": "Technical instructions",
    "accessibility": "Accessibility delivery instructions",
    "media": "Media instructions",
    "staffing": "Linked staffing and retained work",
}


def _secure(response: HttpResponse, *, nonce: str | None = None) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    scripts = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src {scripts}; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response["Referrer-Policy"] = "same-origin"
    return response


def _options(request: HttpRequest, *, operator: bool) -> tuple[str, tuple[str, ...]]:
    allowed = {"format"} | (set(OPERATOR_OPTIONAL_LAYERS) if operator else set())
    if set(request.GET) - allowed or any(
        len(values) != 1 for _, values in request.GET.lists()
    ):
        raise ValueError
    output_format = request.GET.get("format", "html")
    layers = tuple(sorted(set(request.GET) - {"format"}))
    if output_format not in {"html", "print", "pack"} or any(
        request.GET[key] != "1" for key in layers
    ):
        raise ValueError
    return output_format, layers


def _html(
    request: HttpRequest,
    scope: ContinuityScope,
    context: dict[str, object],
    *,
    status: int = 200,
) -> HttpResponse:
    shell = admin.site.each_context(request) if scope.audience != "public" else {}
    nonce = token_urlsafe(32)
    shell.update(
        title=_TITLES[scope.audience],
        baseline_admin_parent_template="admin/base_site.html",
        baseline_use_admin_shell=True,
        baseline_page_id="programme-continuity",
        baseline_page_class="programme-continuity-page",
        maru_csp_nonce=nonce,
        maru_personal_surface=scope.audience == "exact_person",
    )
    if scope.audience == "exact_person":
        shell["has_permission"] = True
    shell.update(context)
    content = render_to_string(
        _TEMPLATES[scope.audience], shell, request=request
    ).encode("utf-8")
    if len(content) > MAX_CONTINUITY_HTML_BYTES:
        raise ContinuityInvalidError
    return _secure(HttpResponse(content, status=status), nonce=nonce)


def _page_context(
    projection: ContinuityProjection, output_format: str
) -> dict[str, object]:
    scope = projection.scope
    parameters = dict.fromkeys(scope.layers, "1")
    source = {"organization_id": scope.organization_id, "edition_id": scope.edition_id}
    notice_url = None
    if scope.audience != "public":
        notice_url = reverse(
            "my-programme-changes"
            if scope.audience == "exact_person"
            else "programme-change-notices",
            kwargs=source,
        )
    body = render_continuity_body(
        projection,
        at=projection.observed_at,
        expires_at=projection.observed_at
        + timedelta(seconds=DEFAULT_CONTINUITY_LIFETIME_SECONDS),
    )
    return {
        # Only the code-owned renderer may create this fragment; it escapes every
        # source string and validates the complete closed payload before rendering.
        "continuity_body": mark_safe(body),  # noqa: S308 - closed escaped renderer only
        "print_view": output_format == "print",
        "refresh_url": "?" + urlencode(parameters),
        "print_url": "?" + urlencode(parameters | {"format": "print"}),
        "pack_url": "?" + urlencode(parameters | {"format": "pack"}),
        "notice_url": notice_url,
        "access_audience": scope.audience.replace("_", " "),
        "access_purpose": scope.kind,
        "access_layers": ", ".join(_LAYERS[layer] for layer in scope.layers)
        or "No optional private layers requested",
        "operator_layers": tuple(
            {"code": code, "label": label, "selected": code in scope.layers}
            for code, label in _LAYERS.items()
        )
        if scope.audience == "private_operator"
        else (),
    }


def _serve(request: HttpRequest, scope: ContinuityScope) -> HttpResponse:
    try:
        invalid_options = False
        try:
            output_format, layers = _options(
                request, operator=scope.audience == "private_operator"
            )
        except ValueError:
            # Do not disclose scope existence with a format error before admission.
            output_format, layers, invalid_options = "html", (), True
        projection = load_continuity_projection(
            replace(scope, layers=layers), correlation_id=uuid4()
        )
        if invalid_options:
            return _html(
                request,
                scope,
                {
                    "state_message": (
                        "Use the format and layer controls without extra "
                        "or repeated options."
                    )
                },
                status=400,
            )
        if output_format == "pack":
            package = sign_continuity_projection(
                projection,
                policy=load_continuity_signing_policy(),
                issued_at=timezone.now(),
            )
            response = HttpResponse(
                package, content_type="application/json; charset=utf-8"
            )
            response["Content-Disposition"] = (
                'attachment; filename="programme-continuity.maru.json"'
            )
            return _secure(response)
        return _html(request, scope, _page_context(projection, output_format))
    except (SchedulingAuthorizationDeniedError, ValidationError):
        status, message = (
            404,
            "Programme continuity is not available at this address "
            "or for the requested fields.",
        )
    except ContinuitySigningUnavailableError:
        status, message = (
            503,
            (
                "Signed export is not configured for this scope, or its key/source "
                "validity could not be verified. No file was produced. Return to "
                "the live view for a fresh authorized check; ask the accountable "
                "operator to configure signing."
            ),
        )
    except (
        SchedulingUnavailableError,
        ContinuityInvalidError,
        TimetableOutputInvalidError,
        DatabaseError,
        RuntimeError,
    ):
        status, message = (
            503,
            (
                "The complete current source could not be verified. No old or partial "
                "timetable is shown. Reload or ask the organizer for instructions."
            ),
        )
    except ValueError:
        status, message = (
            400,
            "Use the format and layer controls without extra or repeated options.",
        )
    return _html(request, scope, {"state_message": message}, status=status)


@never_cache
@require_safe
def public_programme_now(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Serve freshly admitted public now/next, print or signed continuity output.

    Parameters
    ----------
    request : HttpRequest
        Public GET/HEAD; never an actor or private-layer selector.
    organization_id : UUID
        Exact expected tenant scope, not a disclosure grant.
    edition_id : UUID
        Exact edition whose continuity and public adapters must both be admitted.

    Returns
    -------
    HttpResponse
        No-store shared public page/download or a content-free error state.
    """
    return _serve(request, ContinuityScope(organization_id, edition_id, "public"))


@never_cache
@require_safe
@login_required(login_url="staff-login")
def personal_programme_now(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Serve only the genuine person's hosting and retained-work continuation.

    Parameters
    ----------
    request : HttpRequest
        Authenticated GET/HEAD; the actor comes only from the authenticated account.
    organization_id : UUID
        Exact tenant independently checked by the owning queries.
    edition_id : UUID
        Exact edition, never a cross-edition or other-person discovery request.

    Returns
    -------
    HttpResponse
        Private no-store My Maru page/download or a non-disclosing failure.
    """
    return _serve(
        request,
        ContinuityScope(
            organization_id, edition_id, "exact_person", request.user.pk, "personal"
        ),
    )


@never_cache
@require_safe
@login_required(login_url="staff-login")
def operator_programme_now(
    request: HttpRequest,
    *,
    organization_id: UUID,
    edition_id: UUID,
    scope_kind: str,
    target_id: UUID,
) -> HttpResponse:
    """Serve exact-purpose operator now/next without planner or public fallbacks.

    Parameters
    ----------
    request : HttpRequest
        Authenticated safe request with explicitly chosen optional owner layers.
    organization_id : UUID
        Exact tenant, not authority over another organizer.
    edition_id : UUID
        Exact edition rechecked with the current adoption profile.
    scope_kind : str
        Closed room, Department or edition purpose.
    target_id : UUID
        Persisted target independently checked by each requested owner.

    Returns
    -------
    HttpResponse
        Private no-store Administration page/download or a content-free error.
    """
    if scope_kind not in {"room", "department", "edition"}:
        return _secure(HttpResponse("Programme continuity not available.", status=404))
    return _serve(
        request,
        ContinuityScope(
            organization_id,
            edition_id,
            "private_operator",
            request.user.pk,
            scope_kind,
            target_id,
        ),
    )
