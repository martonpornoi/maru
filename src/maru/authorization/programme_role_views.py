"""Dormant genuine-person approval controls over exact owning commands/queries."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_commands import decide_programme_role
from maru.authorization.programme_role_forms import ProgrammeRoleDecisionForm
from maru.authorization.programme_role_inputs import (
    ProgrammeRoleDecision,
    ProgrammeRoleScope,
)
from maru.authorization.programme_role_queries import (
    ProgrammeRoleWorkspace,
    load_programme_role_workspace,
)
from maru.identity.models import Account

_UNAVAILABLE = (
    "Programme access review is temporarily unavailable. No private content is shown. "
    "Keep the original request and retry identity; do not start a replacement decision."
)
_MAX_INPUT_LENGTH = 4096


def _unavailable(error: ValidationError | DatabaseError) -> HttpResponse:
    message = _UNAVAILABLE
    if getattr(error, "code", None) == "programme_role_inventory_overflow":
        message = (
            "The open-request list is too large to show completely. No partial "
            "list is shown. Review known original request links before retrying."
        )
    return _secure(HttpResponse(message, status=503))


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


def _input(request: HttpRequest, *, selected: bool) -> None:
    if request.GET or request.FILES:
        raise ValueError
    if request.method == "POST" and (
        not selected
        or set(request.POST)
        - {*ProgrammeRoleDecisionForm.base_fields, "csrfmiddlewaretoken"}
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


def _root(request: HttpRequest, scope: ProgrammeRoleScope) -> str:
    values: dict[str, UUID] = {
        "organization_id": scope.organization_id,
        "edition_id": scope.programme_edition_id,
    }
    if scope.department_id is not None:
        values["department_id"] = scope.department_id
    if scope.resource_binding_id is not None:
        values["resource_binding_id"] = scope.resource_binding_id
    return reverse(
        f"programme-access-{scope.level.value}",
        kwargs=values,
        urlconf=getattr(request, "urlconf", None),
    )


def _scope_choices_url(request: HttpRequest, scope: ProgrammeRoleScope) -> str:
    # The chooser uses this module's existing shared-shell response boundary.
    from maru.authorization.programme_role_scope_views import (  # noqa: PLC0415
        programme_role_scopes,
    )

    values = {
        "organization_id": scope.organization_id,
        "edition_id": scope.programme_edition_id,
    }
    urlconf = getattr(request, "urlconf", None)
    try:
        url = reverse("programme-access-scopes", kwargs=values, urlconf=urlconf)
        match = resolve(url, urlconf=urlconf)
    except (NoReverseMatch, Resolver404):
        return ""
    if (
        match.url_name != "programme-access-scopes"
        or match.func is not programme_role_scopes
        or match.kwargs != values
    ):
        return ""
    return url


def _render(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeRoleScope,
    workspace: ProgrammeRoleWorkspace,
    request_id: UUID | None,
    form: ProgrammeRoleDecisionForm | None,
    message: str,
    status: int,
) -> HttpResponse:
    nonce = token_urlsafe(32)
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Programme access review",
        has_permission=True,
        maru_csp_nonce=nonce,
        workspace=workspace,
        selected=workspace.requests[0] if request_id else None,
        scope_level=scope.level.value,
        root_url=_root(request, scope),
        scope_choices_url=_scope_choices_url(request, scope),
        form=form,
        message=message,
    )
    content = render_to_string(
        "authorization/programme_role_workspace.html", context, request=request
    )
    current = load_programme_role_workspace(
        actor=actor,
        scope=scope,
        request_id=request_id,
        correlation_id=uuid4(),
        source_channel="html",
    )
    if current != workspace:
        return _secure(
            HttpResponse(
                "The request or your access changed while this page was prepared. "
                "No private content is shown. "
                "Reload the original request before deciding.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content, status=status), nonce)


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_role_workspace(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    *,
    level: str,
    department_id: UUID | None = None,
    resource_binding_id: UUID | None = None,
    request_id: UUID | None = None,
) -> HttpResponse:
    """Review exact own intent and submit only the authenticated person's decision.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected browser request; no alternate actor is accepted.
    organization_id : UUID
        Exact organization route locator, independently resolved and authorized.
    edition_id : UUID
        Exact Programme context even for an organization-wide Venue request.
    level : str
        Code-owned route target level, not a form field or scope inheritance claim.
    department_id : UUID | None, default=None
        Required exact narrower Department for Department or room targets.
    resource_binding_id : UUID | None, default=None
        Exact selected-room binding for the resource route only.
    request_id : UUID | None, default=None
        Original retained request, or the complete bounded own open inventory.

    Returns
    -------
    HttpResponse
        Revalidated no-store shared-shell review, canonical receipt redirect or safe
        non-disclosing malformed, denied, conflict or unavailable response.
    """
    try:
        _input(request, selected=request_id is not None)
        scope = ProgrammeRoleScope(
            organization_id,
            edition_id,
            ScopeLevel(level),
            department_id,
            resource_binding_id,
            "venue.edition_space" if resource_binding_id else "",
        )
        actor = _actor(request)
        workspace = load_programme_role_workspace(
            actor=actor,
            scope=scope,
            request_id=request_id,
            correlation_id=uuid4(),
            source_channel="html",
        )
        form = None
        message = ""
        status = 200
        if request_id is not None:
            selected = workspace.requests[0]
            if (
                request.method == "POST"
                or selected.can_approve
                or selected.can_decline
                or selected.can_cancel
            ):
                form = ProgrammeRoleDecisionForm(
                    request.POST if request.method == "POST" else None,
                    is_author=selected.author_id == actor.id,
                    allow_approve=selected.can_approve or request.method == "POST",
                    initial={"idempotency_key": uuid4()},
                )
            if request.method == "POST" and form is not None:
                if form.is_valid():
                    try:
                        decide_programme_role(
                            actor=actor,
                            scope=scope,
                            request_id=request_id,
                            action=ProgrammeRoleDecision(form.cleaned_data["action"]),
                            reason=form.cleaned_data["reason"],
                            idempotency_key=form.cleaned_data["idempotency_key"],
                            correlation_id=uuid4(),
                            source_channel="html",
                        )
                    except ValidationError as error:
                        form.add_error(None, " ".join(error.messages))
                        status = 409
                    except DatabaseError:
                        form.add_error(
                            None,
                            "The decision could not be confirmed. Retry this exact "
                            "original input and key; do not create another attempt.",
                        )
                        status = 503
                    else:
                        return _secure(HttpResponseRedirect(request.path))
                else:
                    status = 400
                message = (
                    "Your original input and retry identity are retained. Review "
                    "the errors before retrying; no decision is sent automatically."
                )
        return _render(
            request, actor, scope, workspace, request_id, form, message, status
        )
    except PermissionDenied:
        return _secure(
            HttpResponse("Programme access review is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme access input.", status=400))
    except (ValidationError, DatabaseError) as error:
        return _unavailable(error)
