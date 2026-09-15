"""Dormant shared-shell discovery of independently admitted on-site purposes."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError as Denied
from .command_support import SchedulingUnavailableError as Unavailable
from .continuity_protocol import ContinuityScope
from .operator_entry_queries import (
    OperatorEntryCatalog,
    OperatorEntryChoice,
    load_operator_entry,
)
from .operator_output_views import _secure
from .output_navigation import ProgrammeOutputLink, programme_output_links
from .output_rendering import MAX_TIMETABLE_OUTPUT_BYTES
from .planning_queries import SchedulingReadRequest
from .workspace_navigation import ProgrammeWorkspaceLink, programme_workspace_links

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class _Row:
    choice: OperatorEntryChoice
    links: tuple[ProgrammeOutputLink, ...]


def _links(
    request: HttpRequest, scope: SchedulingReadRequest, catalog: OperatorEntryCatalog
) -> tuple[tuple[_Row, ...], tuple[ProgrammeWorkspaceLink, ...]]:
    urlconf = getattr(request, "urlconf", None)
    return (
        tuple(
            _Row(
                choice,
                tuple(
                    link
                    for link in programme_output_links(
                        ContinuityScope(
                            scope.organization_id,
                            scope.edition_id,
                            "private_operator",
                            scope.actor_id,
                            choice.kind.value,
                            choice.target_id,
                        ),
                        current="entry",
                        urlconf=urlconf,
                    )
                    if link.code in {"timetable", "now"}
                ),
            )
            for choice in catalog.choices
        ),
        programme_workspace_links(scope, current="operators", urlconf=urlconf),
    )


def _render(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    read: Callable[[], OperatorEntryCatalog],
) -> HttpResponse:
    catalog = read()
    rows, workspace_links = _links(request, scope, catalog)
    nonce = token_urlsafe(32)
    context = dict(admin.site.each_context(request))
    context.update(
        has_permission=True,
        title="On-site Programme run sheets",
        maru_csp_nonce=nonce,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        rows=rows,
        workspace_links=workspace_links,
    )
    content = render_to_string("scheduling/operator_entry.html", context, request)
    if (rows, workspace_links) != _links(request, scope, catalog):
        context.update(
            rows=tuple(_Row(choice, ()) for choice in catalog.choices),
            workspace_links=(),
        )
        content = render_to_string("scheduling/operator_entry.html", context, request)
    if len(content.encode("utf-8")) > MAX_TIMETABLE_OUTPUT_BYTES or read() != catalog:
        raise Unavailable
    return _secure(HttpResponse(content), script_nonce=nonce)


@never_cache
@require_safe
@login_required(login_url="staff-login")
def operator_entry(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Offer exact operator-purpose choices without creating work or granting access.

    Parameters
    ----------
    request : HttpRequest
        Safe authenticated request; the actual principal is never a form selection.
    organization_id : UUID
        Exact route-bound expected tenant owner.
    edition_id : UUID
        Exact selected edition, not an inferred or portable permission.

    Returns
    -------
    HttpResponse
        Complete revalidated shared-shell catalog or non-disclosing failure.
    """
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID) or not actor_id.int:
        return _secure(
            HttpResponse("These Programme tasks are unavailable.", status=404)
        )
    if request.GET or request.FILES:
        return _secure(
            HttpResponse("Open the operator entry without extra controls.", status=400)
        )
    scope = SchedulingReadRequest(actor_id, organization_id, edition_id, uuid4())
    try:
        return _render(request, scope, lambda: load_operator_entry(scope))
    except Denied:
        return _secure(
            HttpResponse("These Programme tasks are unavailable.", status=404)
        )
    except (Unavailable, DatabaseError, ValidationError, ValueError, RuntimeError):
        return _secure(
            HttpResponse(
                "The operator task service is temporarily unavailable.", status=503
            )
        )
