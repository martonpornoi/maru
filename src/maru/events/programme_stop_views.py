"""Dormant shared-shell accountable stop, never a generic lifecycle shortcut."""

from typing import Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.authorization.programme_stop_authorization import (
    require_programme_stop_preflight,
)
from maru.authorization.services import AuthorizationDenied

from .programme_stop_commands import stop_programme
from .programme_stop_composition import load_programme_stop_preview
from .programme_stop_forms import ProgrammeStopForm
from .programme_stop_receipt_queries import load_programme_stop_receipt

_MAX_INPUT_LENGTH = 1024


def _actor(request: HttpRequest) -> UUID:
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID) or not actor_id.int:
        raise AuthorizationDenied(
            "Programme stop unavailable.", reason_code="programme_stop_unavailable"
        )
    return actor_id


def _secure(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _html(
    request: HttpRequest, context: dict[str, Any], status: int = 200
) -> HttpResponse:
    shell = dict(admin.site.each_context(request))
    shell.update(has_permission=True, title="Stop Programme", **context)
    return _secure(
        HttpResponse(
            render_to_string("events/programme_stop.html", shell, request=request),
            status=status,
        )
    )


def _submit(request: HttpRequest, scope: dict[str, UUID], root: str) -> HttpResponse:
    form = ProgrammeStopForm(request.POST)
    if (
        set(request.POST) - {*form.fields, "csrfmiddlewaretoken"}
        or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        )
        or request.POST.get("confirm", "") not in {"", "on"}
    ):
        raise ValueError
    context: dict[str, Any] = {
        "scope": scope,
        "root_url": root,
        "form": form,
        "submitted": True,
    }
    status = 400
    if form.is_valid():
        try:
            result = stop_programme(
                **scope,
                details=form.cleaned_data["details"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                correlation_id=uuid4(),
                source_channel="programme-stop",
            )
            return _secure(HttpResponseRedirect(f"{root}{result.receipt_id}/"))
        except ValidationError as failure:
            unavailable = getattr(failure, "code", None) == "programme_stop_source"
            status = 503 if unavailable else 409
            form.add_error(
                None,
                "The original confirmation could not be accepted. "
                "If affected work changed, reload and review a new preview; "
                "your original input has not been replaced.",
            )
        except DatabaseError:
            status = 503
            form.add_error(
                None,
                "The result could not be confirmed. Retry this same "
                "form and key; do not assume the stop succeeded or failed.",
            )
    return _html(request, context, status)


def _page(
    request: HttpRequest, scope: dict[str, UUID], receipt_id: UUID | None
) -> HttpResponse:
    require_programme_stop_preflight(**scope)
    root = f"/admin/programme/stop/{scope['organization_id']}/{scope['edition_id']}/"
    if request.GET or request.FILES:
        raise ValueError
    if receipt_id is not None:
        if request.method != "GET":
            return _secure(HttpResponse("Method not allowed.", status=405))
        receipt = load_programme_stop_receipt(
            **scope, receipt_id=receipt_id, correlation_id=uuid4()
        )
        return _html(request, {"scope": scope, "root_url": root, "receipt": receipt})
    if request.method == "POST":
        return _submit(request, scope, root)
    try:
        preview = load_programme_stop_preview(**scope, correlation_id=uuid4())
    except ValidationError as failure:
        if getattr(failure, "code", None) != "programme_stop_lifecycle_conflict":
            raise
        return _html(request, {"scope": scope, "root_url": root, "stopped": True})
    form = None
    if (
        preview.scheduling.active_release_id is None
        or preview.scheduling.withdrawal_authorized
    ):
        form = ProgrammeStopForm(
            initial={
                "expected_aggregate_version": preview.aggregate_version,
                "expected_lifecycle_version": preview.lifecycle_version,
                "preview_fingerprint": preview.fingerprint,
                "idempotency_key": uuid4(),
            }
        )
    return _html(
        request, {"scope": scope, "root_url": root, "preview": preview, "form": form}
    )


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_stop(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    receipt_id: UUID | None = None,
) -> HttpResponse:
    """Preview and explicitly confirm a stop, or read one's original retained result.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected request; submitted fields never choose actor.
    organization_id : UUID
        Exact explicitly selected tenant, never discovered through private records.
    edition_id : UUID
        Exact independently selected scope from the route.
    receipt_id : UUID | None, default=None
        Exact original-actor receipt, or the deliberate preview/confirmation home.

    Returns
    -------
    HttpResponse
        Private shared-shell HTML, original result redirect or non-disclosing failure.
    """
    try:
        return _page(
            request,
            {
                "actor_id": _actor(request),
                "organization_id": organization_id,
                "edition_id": edition_id,
            },
            receipt_id,
        )
    except AuthorizationDenied:
        return _secure(
            HttpResponse("Programme stop unavailable for this request.", status=404)
        )
    except ValueError:
        return _secure(
            HttpResponse("Invalid stop request. Reload the preview.", status=400)
        )
    except (ValidationError, DatabaseError, RuntimeError):
        return _secure(
            HttpResponse(
                "Stop checks are unavailable. No partial preview "
                "or success is shown; retry the same request.",
                status=503,
            )
        )
