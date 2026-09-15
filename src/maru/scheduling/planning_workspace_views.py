"""Dormant canonical timetable route around the existing native editor component."""

from __future__ import annotations

from secrets import token_urlsafe
from uuid import UUID, uuid4

from django.contrib import admin
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.events.queries import resolve_edition_series_identity
from maru.workforce.programme_navigation import programme_shift_links

from .authorization import SchedulingAuthorizationDeniedError
from .planning_disclosure import verify_planning_workspace
from .planning_queries import SchedulingReadRequest
from .planning_views import _DENIALS, scheduling_planning_view
from .workspace_navigation import (
    authorize_timetable_workspace,
    programme_workspace_links,
)

_MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    nonce = nonce or token_urlsafe(32)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _failure(status: int) -> HttpResponse:
    return _secure(
        HttpResponse(
            "This complete timetable workspace is unavailable. No private source "
            "content is shown. If a command was submitted, do not assume it failed; "
            "verify its retained result before starting a different intent.",
            status=status,
            content_type="text/plain; charset=utf-8",
        )
    )


def _series(scope: SchedulingReadRequest, expected: UUID) -> None:
    if (
        resolve_edition_series_identity(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        != expected
    ):
        raise SchedulingAuthorizationDeniedError


def _render(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    series_id: UUID,
    response: TemplateResponse,
) -> HttpResponse:
    context = response.context_data
    if context is None or "snapshot" not in context:
        return _failure(response.status_code)
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        title="Timetable planning",
        has_permission=True,
        maru_csp_nonce=nonce,
        baseline_admin_parent_template="admin/base_site.html",
        baseline_use_admin_shell=True,
        maru_shell_access_rendered_by_page=True,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        series_id=series_id,
    )
    context.update(shell)
    urlconf = getattr(request, "urlconf", None)
    context["workspace_links"] = programme_workspace_links(
        scope, current="timetable", series_id=series_id, urlconf=urlconf
    )
    demand_ids = tuple(
        row["binding"].demand_id
        for row in context.get("staffing_rows", ())
        if row.get("binding") is not None
    )

    def current_shift_links() -> dict[UUID, str]:
        return programme_shift_links(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            series_id=series_id,
            edition_id=scope.edition_id,
            demand_ids=demand_ids,
            urlconf=urlconf,
        )

    shift_links = current_shift_links()
    context["workforce_staffing_cards"] = tuple(
        row | {"shift_url": shift_links.get(row["binding"].demand_id)}
        if row.get("binding") is not None
        else row
        for row in context.get("staffing_rows", ())
    )
    response.render()
    fresh_workspace_links = programme_workspace_links(
        scope, current="timetable", series_id=series_id, urlconf=urlconf
    )
    fresh_shift_links = current_shift_links()
    if (
        context["workspace_links"] != fresh_workspace_links
        or shift_links != fresh_shift_links
    ):
        # Optional navigation movement must not become a command failure.
        context["workspace_links"] = ()
        context["workforce_staffing_cards"] = ()
        response = TemplateResponse(
            request, response.template_name, context, status=response.status_code
        )
        response.render()
    if len(response.content) > _MAX_OUTPUT_BYTES:
        raise RuntimeError("Timetable output exceeds its complete bound.")
    verify_planning_workspace(scope, context)
    authorize_timetable_workspace(scope)
    _series(scope, series_id)
    return _secure(response, nonce)


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_timetable_workspace(
    request: HttpRequest,
    *,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    """Resolve a canonical dormant route and finish guarded native editor rendering.

    Parameters
    ----------
    request : HttpRequest
        Authenticated native request; original selection and command POST is unchanged.
    organization_id : UUID
        Expected exact tenant from the reserved route, not a grant.
    series_id : UUID
        Expected parent verified through Events' public identity seam.
    edition_id : UUID
        Exact edition independently admitted by every participating owner.

    Returns
    -------
    HttpResponse
        Shared-shell, no-store native planner or a non-disclosing failure. No current
        profile or production URL configuration mounts this declaration.

    Notes
    -----
    The existing editor is dispatched once. Final rendering performs only protected
    owner reads and policy checks, never a second submission. Scope names are not
    inferred from identifiers or an unrelated shell selection. The native planner's
    retained source-read recovery contract is unchanged; this wrapper is not a new
    source-free command receipt API.
    """
    actor_id = getattr(request.user, "pk", None)
    if not request.user.is_authenticated or not isinstance(actor_id, UUID):
        return _failure(403)
    scope = SchedulingReadRequest(actor_id, organization_id, edition_id, uuid4())
    try:
        authorize_timetable_workspace(scope)
        _series(scope, series_id)
        response = scheduling_planning_view(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            edition_label="Selected edition",
        )
        if not isinstance(response, TemplateResponse):
            return _secure(response)
        return _render(request, scope, series_id, response)
    except _DENIALS:
        return _failure(403)
    except (DatabaseError, RuntimeError):
        return _failure(503)
