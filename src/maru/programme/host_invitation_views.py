"""Preview-first exact-person hosting with original receipt recovery before reads."""

from __future__ import annotations

from dataclasses import asdict
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import commands, host_commands, queries
from .authorization import PROGRAMME_MANAGE_HOSTS, ProgrammeAuthorizationDeniedError
from .host_authorization import authorize_host_retry_scope
from .host_forms import ProgrammeHostInvitationConfirmForm, ProgrammeHostInvitationForm
from .host_invitation_preview import (
    HostInvitationPreview,
    prepare_host_invitation_preview,
    verify_host_invitation_preview,
)
from .host_views import _conflict, _errors, _input, _scope, _write
from .host_views import _context as _host_context
from .host_views import _root as _host_root
from .workbench_views import _CONFLICTS, _secure

if TYPE_CHECKING:
    from collections.abc import Callable

    from .workbench_queries import ProgrammeWorkbenchRequest

_UNAVAILABLE = (
    DatabaseError,
    queries.ProgrammeQueryError,
    commands.ProgrammeCommandError,
)


def _entry(scope: ProgrammeWorkbenchRequest) -> None:
    authorize_host_retry_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_MANAGE_HOSTS,
    )


def _context(scope: ProgrammeWorkbenchRequest, item_id: UUID) -> dict[str, Any]:
    return _host_context(scope, item_id, "invite", None)


def _html(
    request: HttpRequest,
    scope: ProgrammeWorkbenchRequest,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
) -> HttpResponse:
    verify()
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        page_title="Exact Programme host invitation",
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    shell.update(context)
    html = render_to_string("programme/host_invitation.html", shell, request)
    if len(html.encode("utf-8")) > 8 * 1024 * 1024:
        raise queries.ProgrammeQueryUnavailableError
    verify()
    return _secure(HttpResponse(html, status=status), nonce)


def _continuation(scope: ProgrammeWorkbenchRequest, item_id: UUID) -> str | None:
    try:
        _context(scope, item_id)
    except (ProgrammeAuthorizationDeniedError, *_UNAVAILABLE):
        return None
    return _host_root(scope, item_id)


def _receipt(
    request: HttpRequest,
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    result: host_commands.ProgrammeHostCommandResult,
) -> HttpResponse:
    if result.item_id != item_id:
        raise queries.ProgrammeQueryUnavailableError
    link = _continuation(scope, item_id)

    def verify() -> None:
        _entry(scope)
        if link and _continuation(scope, item_id) != link:
            raise ProgrammeAuthorizationDeniedError

    try:
        return _html(request, scope, {"receipt": result, "roster_link": link}, verify)
    except ProgrammeAuthorizationDeniedError:
        return _html(request, scope, {"receipt": result}, lambda: _entry(scope))


def _confirm(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    form: ProgrammeHostInvitationConfirmForm,
) -> tuple[host_commands.ProgrammeHostCommandResult | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        preview = verify_host_invitation_preview(
            scope,
            item_id=item_id,
            intent=form.to_intent(),
            proof=form.cleaned_data["selection_proof"],
        )
        result = host_commands.invite_programme_host(
            **asdict(scope),
            item_id=item_id,
            invitation=preview.intent.invitation(preview.person_id),
            idempotency_key=preview.intent.idempotency_key,
            reason=preview.intent.reason,
            source_channel="programme-hosts",
        )
    except ValidationError as error:
        _errors(form, error)
        return None, 400
    except _CONFLICTS:
        _conflict(form)
        return None, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            (
                "The invitation result is unavailable. Keep the original selection "
                "proof, person, version, retry and entered values for exact recovery."
            ),
        )
        return None, 503
    return result, 200


def _prepare(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    form: ProgrammeHostInvitationForm,
    context: dict[str, Any],
) -> tuple[HostInvitationPreview | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        _write(scope)
        if (
            not context["can_invite"]
            or form.cleaned_data["expected_version"] != context["roster"].item_version
        ):
            raise commands.ProgrammeVersionConflictError
        preview = prepare_host_invitation_preview(
            scope, item_id=item_id, intent=form.to_intent()
        )
    except ValidationError as error:
        _errors(form, error)
        return None, 400
    except _CONFLICTS:
        _conflict(form)
        return None, 409
    except _UNAVAILABLE:
        form.add_error(
            None, "Person selection is unavailable. No invitation was confirmed."
        )
        return None, 503
    return preview, 200


def _run(
    request: HttpRequest,
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
) -> HttpResponse:
    form: ProgrammeHostInvitationForm | None = None
    preview = None
    status = 200
    action = request.POST.get("action")
    if request.method == "POST" and action == "confirm":
        form = ProgrammeHostInvitationConfirmForm(request.POST)
        result, status = _confirm(scope, item_id, form)
        if result is not None:
            return _receipt(request, scope, item_id, result)
    context = _context(scope, item_id)
    if request.method == "POST":
        _write(scope)
        if action == "preview":
            form = ProgrammeHostInvitationForm(request.POST)
            preview, status = _prepare(scope, item_id, form, context)
            if preview is not None:
                form = ProgrammeHostInvitationConfirmForm(
                    initial={**asdict(preview.intent), "selection_proof": preview.proof}
                )
    elif context["can_invite"]:
        form = ProgrammeHostInvitationForm(
            initial={
                "expected_version": context["roster"].item_version,
                "idempotency_key": uuid4(),
            }
        )

    def verify() -> None:
        if _context(scope, item_id) != context:
            raise ProgrammeAuthorizationDeniedError
        if request.method == "POST":
            _write(scope)

    return _html(
        request,
        scope,
        {
            **context,
            "form": form,
            "preview": preview,
            "confirmation": isinstance(form, ProgrammeHostInvitationConfirmForm),
            "pending": request.method == "POST",
        },
        verify,
        status,
    )


def _transport(request: HttpRequest) -> None:
    _input(request, set(ProgrammeHostInvitationConfirmForm.base_fields) | {"action"})
    if request.method == "POST" and request.POST.get("action") not in {
        "preview",
        "confirm",
    }:
        raise ValueError


@login_required
@never_cache
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_host_invitation(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
) -> HttpResponse:
    """Select one exact host before confirming or recovering the original receipt.

    Parameters
    ----------
    request : HttpRequest
        Authenticated closed request with real CSRF enforcement.
    organization_id : UUID
        Exact organizer scope from trusted routing.
    edition_id : UUID
        Exact Programme edition, independently revalidated by owner commands.
    item_id : UUID
        Exact selected item, never an editable form authority claim.

    Returns
    -------
    HttpResponse
        Fresh selection/confirmation, minimal original receipt or bounded failure.
    """
    try:
        scope = _scope(request, organization_id, edition_id)
        _entry(scope)
        _transport(request)
        return _run(request, scope, item_id)
    except ProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Hosting page not found.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported hosting request.", status=400))
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "Hosting is unavailable. No partial content is shown.", status=503
            )
        )
