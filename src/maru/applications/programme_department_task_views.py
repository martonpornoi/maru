"""Read-only shared-shell entry to independently admitted Applications tasks."""

from __future__ import annotations

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
from django.views.decorators.http import require_http_methods

from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.workspace_navigation import programme_workspace_links

from . import programme_department_tasks as tasks
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_views import _secure

if TYPE_CHECKING:
    from collections.abc import Callable

    from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink


def _render(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    read: Callable[[], tasks.ProgrammeDepartmentTaskCatalog],
) -> HttpResponse:
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID) or not actor_id.int:
        raise Denied
    initial = read()
    nonce = token_urlsafe(32)
    context = dict(admin.site.each_context(request))
    context.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        title="Programme calls, review and conversion",
        organization_id=organization_id,
        edition_id=edition_id,
        department_tasks=initial.tasks,
        read_only=not initial.accepts_private_planning_writes,
    )
    scope = SchedulingReadRequest(actor_id, organization_id, edition_id, uuid4())

    def links() -> tuple[ProgrammeWorkspaceLink, ...]:
        return programme_workspace_links(
            scope, current="applications", urlconf=getattr(request, "urlconf", None)
        )

    context["workspace_links"] = links()
    content = render_to_string(
        "applications/programme_department_tasks.html", context, request
    )
    if context["workspace_links"] != links():
        context["workspace_links"] = ()
        content = render_to_string(
            "applications/programme_department_tasks.html", context, request
        )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        return _secure(
            HttpResponse(
                "The Programme task service is temporarily unavailable.", status=503
            )
        )
    if read() != initial:
        raise Denied
    return _secure(HttpResponse(content), nonce)


@login_required
@never_cache
@require_http_methods(["GET"])
def programme_department_tasks(
    request: HttpRequest, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Offer exact-edition task choices without accepting writes or guessed roles.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request whose principal is always the actual person.
    organization_id : UUID
        Exact route-bound organization, independently resolved by the owner.
    edition_id : UUID
        Exact route-bound edition, not a session-derived permission grant.

    Returns
    -------
    HttpResponse
        Complete revalidated task catalog or non-disclosing safe failure.
    """
    actor = request.user.pk
    if not isinstance(actor, UUID) or not actor.int:
        return _secure(
            HttpResponse("These Programme tasks are unavailable.", status=404)
        )
    if request.GET or request.FILES:
        return _secure(
            HttpResponse(
                "Open the Programme task entry without extra controls.", status=400
            )
        )
    correlation_id = uuid4()

    def read() -> tasks.ProgrammeDepartmentTaskCatalog:
        return tasks.list_programme_department_tasks(
            actor_id=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            source_channel="programme-department-tasks",
        )

    try:
        return _render(request, organization_id, edition_id, read)
    except Denied:
        return _secure(
            HttpResponse("These Programme tasks are unavailable.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use a complete Programme task request.", status=400)
        )
    except DatabaseError:
        return _secure(
            HttpResponse(
                "The Programme task service is temporarily unavailable.", status=503
            )
        )
