"""One personal inbox for independently admitted Guides setup and access decisions."""

from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Never
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from maru.authorization.guidance_access_queries import (
    GuidanceAccessRequestView,
    list_my_guidance_access_requests_page,
)
from maru.authorization.guidance_readiness import GuidanceAuthorityUnavailable
from maru.authorization.page_access import fixed_page_access
from maru.events.guidance_activation_queries import (
    GuidanceActivationRequestView,
    list_my_guidance_activation_requests,
)
from maru.events.guidance_setup_readiness import GuidanceSetupUnavailable
from maru.identity.request_actor import RequestActor, authenticated_request_actor

from .access_views import _secure

_MAX_CURSOR_LENGTH = 4096


@dataclass(frozen=True, slots=True)
class _Pending:
    setup: tuple[GuidanceActivationRequestView, ...]
    access: tuple[GuidanceAccessRequestView, ...]
    next_cursor: str | None
    setup_unavailable: bool


def _bad_input() -> Never:
    raise ValueError


def _pending(actor: RequestActor, cursor: str | None) -> _Pending:
    setup_unavailable = False
    try:
        setup = list_my_guidance_activation_requests(
            actor=actor, correlation_id=uuid4()
        )
    except ValidationError as error:
        if getattr(error, "code", None) != "guidance_setup_capacity":
            raise
        setup = ()
        setup_unavailable = True
    access = list_my_guidance_access_requests_page(
        actor=actor, correlation_id=uuid4(), cursor=cursor, pending_only=True
    )
    return _Pending(
        tuple(item for item in setup if item.can_answer or item.can_apply),
        access.items,
        access.next_cursor,
        setup_unavailable,
    )


@login_required(login_url="staff-login")
@never_cache
@require_GET
def guidance_tasks(request: HttpRequest) -> HttpResponse:
    """Show only this actual person's currently actionable owner-admitted tasks.

    Parameters
    ----------
    request : HttpRequest
        Authenticated person's read-only personal inbox request.

    Returns
    -------
    HttpResponse
        Complete rechecked pending tasks or a safe non-disclosing response.
    """
    try:
        actor = authenticated_request_actor(request)
        if (
            set(request.GET) - {"cursor"}
            or request.FILES
            or any(
                len(values) != 1
                or any(len(value) > _MAX_CURSOR_LENGTH for value in values)
                for _, values in request.GET.lists()
            )
        ):
            _bad_input()
        cursor = request.GET.get("cursor") or None
        page = _pending(actor, cursor)
        nonce = token_urlsafe(32)
        context = dict(admin.site.each_context(request))
        context.update(
            title="Your Guides decisions",
            has_permission=True,
            maru_csp_nonce=nonce,
            setup_unavailable=page.setup_unavailable,
            setup_rows=tuple(
                (
                    item,
                    reverse(
                        "guidance-activation-detail",
                        kwargs={"request_id": item.request_id},
                    ),
                )
                for item in page.setup
            ),
            access_rows=tuple(
                (
                    item,
                    reverse(
                        "guidance-access-detail", kwargs={"request_id": item.request_id}
                    ),
                )
                for item in page.access
            ),
            next_url=request.path + "?" + urlencode({"cursor": page.next_cursor})
            if page.next_cursor
            else "",
            first_url=request.path if cursor else "",
            setup_history_url=reverse("guidance-activation-tasks"),
            access_history_url=reverse("guidance-access-tasks"),
            maru_page_access_spec=fixed_page_access(
                policy="self",
                scope_label="Your Guides decisions",
                explanation=(
                    "Only decisions currently addressed to you are shown. Every "
                    "setup request and access request checks your current "
                    "responsibilities again when you open it."
                ),
            ),
            baseline_hide_admin_scoped_navigation=True,
        )
        content = render_to_string("knowledge/tasks.html", context, request=request)
        if _pending(actor, cursor) != page:
            return _secure(
                HttpResponse(
                    "Your pending decisions changed. Reload to see the current list.",
                    status=409,
                ),
                nonce,
            )
        return _secure(HttpResponse(content), nonce)
    except (
        ValidationError,
        DatabaseError,
        GuidanceAuthorityUnavailable,
        GuidanceSetupUnavailable,
    ):
        return _secure(
            HttpResponse(
                (
                    "Guides decisions are temporarily unavailable. No partial list "
                    "is shown."
                ),
                status=503,
            )
        )
    except PermissionDenied:
        return _secure(HttpResponse("Guides decisions are unavailable.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported Guides decisions input.", status=400))
