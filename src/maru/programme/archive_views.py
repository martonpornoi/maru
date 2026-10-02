"""Dormant purpose-specific archive screens; no production URL inclusion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
    StreamingHttpResponse,
)
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .archive_authorization import authorize_programme_archive_scope
from .archive_forms import ProgrammeArchiveCancelForm, ProgrammeArchiveRequestForm
from .archive_queries import inspect_programme_archive
from .archive_tasks import (
    ProgrammeArchiveCapacityError,
    ProgrammeArchiveConflictError,
    ProgrammeArchiveScope,
    ProgrammeArchiveUnavailableError,
    cancel_programme_archive,
    request_programme_archive,
)
from .authorization import ProgrammeAuthorizationDeniedError

if TYPE_CHECKING:
    from django.forms import Form

_MAX_INPUT_LENGTH = 80


def _secure[ResponseT: HttpResponseBase](response: ResponseT) -> ResponseT:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _scope(
    request: HttpRequest, organization_id: UUID, edition_id: UUID
) -> ProgrammeArchiveScope:
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        raise ProgrammeArchiveUnavailableError
    scope = ProgrammeArchiveScope(actor_id, organization_id, edition_id)
    authorize_programme_archive_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        requested_fields=frozenset({"archive_requests"}),
    )
    return scope


def _root(scope: ProgrammeArchiveScope) -> str:
    return f"/admin/programme/archive/{scope.organization_id}/{scope.edition_id}/"


def _html(
    request: HttpRequest, context: dict[str, Any], status: int = 200
) -> HttpResponse:
    shell = dict(admin.site.each_context(request))
    shell.update(has_permission=True, title="Programme exit archive", **context)
    response = _secure(
        HttpResponse(
            render_to_string("programme/archive.html", shell, request=request),
            status=status,
        )
    )
    # Preserve native form CSRF evidence; attachments retain no-referrer below.
    response["Referrer-Policy"] = "same-origin"
    return response


def _input(request: HttpRequest, form: Form) -> None:
    if (
        request.GET
        or request.FILES
        or set(request.POST)
        - {
            *form.fields,
            "action",
            "csrfmiddlewaretoken",
        }
        or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        )
    ):
        raise ValueError


def _submit(
    request: HttpRequest,
    scope: ProgrammeArchiveScope,
    task_id: UUID | None,
    context: dict[str, Any],
) -> HttpResponse:
    root = _root(scope)
    action = request.POST.get("action")
    if (action == "request" and task_id is None) or (action == "retry" and task_id):
        form: Form = ProgrammeArchiveRequestForm(request.POST)
    elif action == "cancel" and task_id:
        form = ProgrammeArchiveCancelForm(request.POST)
    else:
        raise ValueError
    _input(request, form)
    status = 400
    if form.is_valid():
        status = 409
        try:
            if action == "cancel" and task_id:
                cancel_programme_archive(
                    scope=scope,
                    task_id=task_id,
                    expected_version=form.cleaned_data["expected_version"],
                )
                return _secure(HttpResponseRedirect(f"{root}{task_id}/"))
            queued = request_programme_archive(
                scope=scope,
                request_key=form.cleaned_data["request_key"],
                previous_task_id=task_id,
            )
            return _secure(HttpResponseRedirect(f"{root}{queued}/"))
        except ProgrammeArchiveCapacityError:
            form.add_error(
                None,
                "Archive capacity is unavailable. Refresh your "
                "previous request or try later with this same request key.",
            )
        except ProgrammeArchiveConflictError:
            form.add_error(
                None,
                "This request changed or cannot be retried yet. "
                "Refresh its status before trying again.",
            )
        except DatabaseError:
            status = 503
            form.add_error(
                None,
                "The request could not be confirmed. Retry this "
                "same form; its request key has been preserved.",
            )
    context.update(form=form, action=action, invalid=True)
    return _html(request, context, status)


def _selection(request: HttpRequest) -> None:
    if request.GET or request.FILES:
        raise ValueError


def _page(
    request: HttpRequest,
    scope: ProgrammeArchiveScope,
    task_id: UUID | None,
) -> HttpResponse:
    root = _root(scope)
    context: dict[str, Any] = {
        "scope": scope,
        "root_url": root,
        "task_url": f"{root}{task_id}/" if task_id else root,
    }
    _selection(request)
    if request.method == "POST":
        return _submit(request, scope, task_id, context)
    if task_id is None:
        context.update(
            form=ProgrammeArchiveRequestForm(initial={"request_key": uuid4()}),
            action="request",
        )
    else:
        result = inspect_programme_archive(scope=scope, task_id=task_id)
        context["task"] = result
        if result.state in {"queued", "running", "ready"}:
            context.update(
                form=ProgrammeArchiveCancelForm(
                    initial={"expected_version": result.version}
                ),
                action="cancel",
            )
        else:
            context.update(
                form=ProgrammeArchiveRequestForm(initial={"request_key": uuid4()}),
                action="retry",
            )
    return _html(request, context)


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_archive(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    task_id: UUID | None = None,
) -> HttpResponse:
    """Preview, request, inspect, cancel or deliberately replace one's own archive.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with closed CSRF-protected mutation inputs.
    organization_id : UUID
        Independently selected route tenant, not submitted authority.
    edition_id : UUID
        Exact edition inside the selected tenant.
    task_id : UUID | None, default=None
        Previously acknowledged private request or the static preview home.

    Returns
    -------
    HttpResponse
        Private shared-shell HTML, exact redirect or non-content failure.
    """
    try:
        return _page(request, _scope(request, organization_id, edition_id), task_id)
    except (
        ProgrammeAuthorizationDeniedError,
        PermissionDenied,
        ProgrammeArchiveUnavailableError,
    ):
        return _secure(
            HttpResponse("Programme archive unavailable for this request.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Invalid archive request. Reload the form.", status=400)
        )
    except (DatabaseError, RuntimeError):
        return _secure(
            HttpResponse(
                "Archive checks are temporarily unavailable. No partial result is "
                "shown; retry the same request.",
                status=503,
            )
        )


@never_cache
@login_required
@require_http_methods(["GET"])
def programme_archive_download(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    task_id: UUID,
) -> HttpResponseBase:
    """Return only fully verified private bytes to the current original requester.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated browser download request, with no selection overrides.
    organization_id : UUID
        Independently selected tenant scope.
    edition_id : UUID
        Exact edition inside that tenant.
    task_id : UUID
        Exact retained private task; never a shared bearer capability.

    Returns
    -------
    HttpResponseBase
        Private attachment response or the same non-content unavailable shape.
    """
    try:
        _selection(request)
        result = inspect_programme_archive(
            scope=_scope(request, organization_id, edition_id),
            task_id=task_id,
            download=True,
        )
        response = StreamingHttpResponse(
            iter(result.chunks), content_type="application/zip"
        )
        response["Content-Disposition"] = (
            'attachment; filename="programme-exit-archive.zip"'
        )
        response["Content-Length"] = str(result.size_bytes)
        return _secure(response)
    except (PermissionDenied, ValidationError, ValueError, RuntimeError, DatabaseError):
        return _secure(
            HttpResponse("Programme archive unavailable for this request.", status=404)
        )
