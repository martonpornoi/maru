"""Reserved labelled scope selection; links never stand in for current authority."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from maru.authorization.programme_role_creation_views import programme_role_creation
from maru.authorization.programme_role_scope_choices import (
    ProgrammeRoleScopeCatalog,
    load_programme_role_scope_choices,
)
from maru.authorization.programme_role_views import (
    _actor,
    _secure,
    programme_role_workspace,
)

if TYPE_CHECKING:
    from maru.identity.models import Account

_UNAVAILABLE = (
    "Programme access scopes are temporarily unavailable. No partial list or "
    "private content is shown. Retry this page; no access has been changed."
)


def _links(
    request: HttpRequest, catalog: ProgrammeRoleScopeCatalog
) -> list[dict[str, Any]]:
    rows = []
    urlconf = getattr(request, "urlconf", None)
    for choice in catalog.choices:
        scope = choice.scope
        values = {
            "organization_id": scope.organization_id,
            "edition_id": scope.programme_edition_id,
        }
        if scope.department_id is not None:
            values["department_id"] = scope.department_id
        if scope.resource_binding_id is not None:
            values["resource_binding_id"] = scope.resource_binding_id
        row: dict[str, Any] = {"choice": choice}
        for suffix, key, handler in (
            ("", "review_url", programme_role_workspace),
            ("-new", "create_url", programme_role_creation),
        ):
            name = f"programme-access-{scope.level.value}{suffix}"
            url = reverse(name, kwargs=values, urlconf=urlconf)
            match = resolve(url, urlconf=urlconf)
            if (
                match.url_name != name
                or match.func is not handler
                or match.kwargs != {**values, "level": scope.level.value}
            ):
                raise NoReverseMatch
            row[key] = url
        rows.append(row)
    return rows


def _render(
    request: HttpRequest,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    catalog: ProgrammeRoleScopeCatalog,
) -> HttpResponse:
    rows = _links(request, catalog)
    nonce = token_urlsafe(32)
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Choose Programme access scope",
        has_permission=True,
        maru_csp_nonce=nonce,
        catalog=catalog,
        rows=rows,
    )
    content = render_to_string(
        "authorization/programme_role_scopes.html", context, request=request
    )
    current = load_programme_role_scope_choices(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=uuid4(),
        source_channel="html",
    )
    if current != catalog or _links(request, current) != rows:
        return _secure(
            HttpResponse(
                "Your access scopes changed while this page was prepared. "
                "No private content is shown. Reload to choose a current scope.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content), nonce)


@login_required(login_url="staff-login")
@never_cache
@require_http_methods(["GET"])
def programme_role_scopes(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    """Choose only independently admitted scopes through ordinary labelled links.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated browser GET with no scope override or search input.
    organization_id : UUID
        Exact expected organization, independently resolved by the owner query.
    edition_id : UUID
        Exact Programme context, not permission over every scope within it.

    Returns
    -------
    HttpResponse
        Revalidated no-store shared-shell choices or a non-disclosing failure.
        This read-only adapter never invokes an access request or grant command.
    """
    if request.GET or request.FILES or request.body:
        return _secure(HttpResponse("Unsupported Programme access input.", status=400))
    try:
        actor = _actor(request)
        catalog = load_programme_role_scope_choices(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=uuid4(),
            source_channel="html",
        )
        return _render(request, actor, organization_id, edition_id, catalog)
    except PermissionDenied:
        return _secure(HttpResponse("Programme access is unavailable.", status=404))
    except (ValidationError, DatabaseError, NoReverseMatch, Resolver404):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
