"""Dormant own-person starter review in the existing private management shell."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.identity.models import Account
from maru.identity.services import require_recent_step_up
from maru.workforce.programme_starter_commands import decide_programme_starter
from maru.workforce.programme_starter_forms import ProgrammeStarterDecisionForm
from maru.workforce.programme_starter_inputs import (
    ProgrammeStarterAction,
    ProgrammeStarterScope,
)
from maru.workforce.programme_starter_queries import (
    ProgrammeStarterWorkspace,
    load_programme_starter_workspace,
)

_MAX_INPUT_LENGTH = 4096
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_UNAVAILABLE = (
    "Volunteer starter review is unavailable. No private content or partial list "
    "is shown. Keep original input and retry identities."
)


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _input(request: HttpRequest, fields: set[str], *, selected: bool = True) -> None:
    if request.GET or request.FILES:
        raise ValueError
    if request.method == "POST" and (
        not selected
        or set(request.POST) - (fields | {"csrfmiddlewaretoken"})
        or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        )
    ):
        raise ValueError


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied
    return request.user


def _url(
    request: HttpRequest, scope: ProgrammeStarterScope, suffix: str = "", **extra: UUID
) -> str:
    return reverse(
        "programme-volunteer-starter" + suffix,
        kwargs={
            "organization_id": scope.organization_id,
            "series_id": scope.series_id,
            "edition_id": scope.edition_id,
            **extra,
        },
        urlconf=getattr(request, "urlconf", None),
    )


def _render(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeStarterScope,
    workspace: ProgrammeStarterWorkspace,
    request_id: UUID | None,
    form: ProgrammeStarterDecisionForm | None,
    status: int,
) -> HttpResponse:
    nonce = token_urlsafe(32)
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Volunteer starter review",
        has_permission=True,
        maru_csp_nonce=nonce,
        workspace=workspace,
        selected=workspace.requests[0] if request_id else None,
        root_url=_url(request, scope),
        new_url=_url(request, scope, "-new") if workspace.can_request else "",
        rows=tuple(
            (row, _url(request, scope, "-request", request_id=row.request_id))
            for row in workspace.requests
        ),
        form=form,
        step_up_url=f"{reverse('account-step-up')}?{urlencode({'next': request.path})}",
    )
    content = render_to_string(
        "workforce/programme_starter_workspace.html", context, request=request
    )
    current = load_programme_starter_workspace(
        actor=actor,
        scope=scope,
        request_id=request_id,
        correlation_id=uuid4(),
        source_channel="html",
    )
    if current != workspace:
        return _secure(
            HttpResponse(
                "The original request, labels or your access changed while this page "
                "was prepared. No private content is shown. Reload the original "
                "request before deciding.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode()) > _MAX_RESPONSE_BYTES:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content, status=status), nonce)


def _decide(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeStarterScope,
    request_id: UUID,
    form: ProgrammeStarterDecisionForm,
) -> HttpResponse | int:
    if not form.is_valid():
        return 400
    try:
        require_recent_step_up(account=actor, request=request)
    except ValidationError:
        form.add_error(
            None,
            "Complete the extra sign-in check in a new tab, then return here and "
            "retry this exact original input. Your decision and key remain below.",
        )
        return 403
    try:
        decide_programme_starter(
            actor=actor,
            scope=scope,
            request_id=request_id,
            action=ProgrammeStarterAction(form.cleaned_data["action"]),
            reason=form.cleaned_data["reason"],
            idempotency_key=form.cleaned_data["idempotency_key"],
            correlation_id=uuid4(),
            source_channel="html",
        )
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        return 409
    except DatabaseError:
        form.add_error(
            None,
            "The decision could not be confirmed. Retry the exact original input "
            "and key; do not create another attempt.",
        )
        return 503
    return _secure(HttpResponseRedirect(request.path))


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_starter_workspace(
    request: HttpRequest,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    request_id: UUID | None = None,
) -> HttpResponse:
    """Review own exact starter intent and submit only this authenticated decision.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected browser request; no actor override is accepted.
    organization_id : UUID
        Exact shared-definition owner from the route.
    series_id : UUID
        Original independently resolved series within that organization.
    edition_id : UUID
        Exact admitted Programme context, not another edition's authority.
    request_id : UUID | None, default=None
        Known original request, or the complete bounded own open inventory.

    Returns
    -------
    HttpResponse
        Revalidated no-store shared-shell review, original receipt redirect or
        non-disclosing invalid/denied/stale/unavailable response.
    """
    try:
        _input(
            request,
            set(ProgrammeStarterDecisionForm.base_fields),
            selected=request_id is not None,
        )
        scope = ProgrammeStarterScope(organization_id, series_id, edition_id)
        actor = _actor(request)
        workspace = load_programme_starter_workspace(
            actor=actor,
            scope=scope,
            request_id=request_id,
            correlation_id=uuid4(),
            source_channel="html",
        )
        form = None
        status = 200
        if request_id is not None:
            selected = workspace.requests[0]
            if (
                request.method == "POST"
                or selected.can_approve
                or selected.can_decline
                or selected.can_cancel
            ):
                form = ProgrammeStarterDecisionForm(
                    request.POST if request.method == "POST" else None,
                    is_author=selected.author_id == actor.id,
                    allow_approve=selected.can_approve or request.method == "POST",
                    initial={"idempotency_key": uuid4()},
                )
            if request.method == "POST" and form is not None:
                outcome = _decide(request, actor, scope, request_id, form)
                if isinstance(outcome, HttpResponse):
                    return outcome
                status = outcome
        return _render(request, actor, scope, workspace, request_id, form, status)
    except PermissionDenied:
        return _secure(
            HttpResponse("Volunteer starter review is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Volunteer starter input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
