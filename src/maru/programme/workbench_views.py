"""Dormant shared-shell Programme tasks backed by existing owner commands."""

from __future__ import annotations

from dataclasses import asdict
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from . import commands, queries
from .authorization import (
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from .workbench_forms import (
    ProgrammeCoreForm,
    ProgrammeDeliveryForm,
    ProgrammePublicCopyForm,
    ProgrammeReadinessForm,
    ProgrammeWorkbenchForm,
    ProgrammeWorkingForm,
)
from .workbench_queries import (
    ProgrammeWorkbenchItem,
    ProgrammeWorkbenchRequest,
    load_programme_workbench_inventory,
    load_programme_workbench_item,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_READS = {
    "working": (
        "programme.view_private",
        frozenset({"item_summaries", "working_information"}),
    ),
    "delivery": ("programme.view_delivery", frozenset({"delivery_information"})),
    "readiness": ("programme.view_readiness", frozenset({"readiness_summary"})),
    "public-copy": (
        "programme.view_public_copy",
        frozenset({"latest_public_rendition"}),
    ),
    "working-history": ("programme.view_private", frozenset({"working_history"})),
    "delivery-history": ("programme.view_delivery", frozenset({"delivery_history"})),
    "readiness-history": ("programme.view_readiness", frozenset({"readiness_history"})),
    "public-copy-history": (
        "programme.view_private",
        frozenset({"public_copy_review_history"}),
    ),
}
_WRITES = {
    "create": "programme.manage_items",
    "working": "programme.manage_items",
    "delivery": "programme.manage_delivery",
    "readiness": "programme.manage_readiness",
    "public-copy": "programme.approve_public_copy",
}
_FORMS = {
    "create": ProgrammeCoreForm,
    "working": ProgrammeWorkingForm,
    "delivery": ProgrammeDeliveryForm,
    "readiness": ProgrammeReadinessForm,
    "public-copy": ProgrammePublicCopyForm,
}
_LABELS = {
    "working": "Working copy",
    "delivery": "Delivery instructions",
    "readiness": "Readiness",
    "public-copy": "Reviewed public copy",
    "working-history": "Working history",
    "delivery-history": "Delivery history",
    "readiness-history": "Readiness history",
    "public-copy-history": "Public-copy review history",
}
_BUTTONS = {
    "create": "Create private item",
    "working": "Save working revision",
    "delivery": "Save delivery revision",
    "readiness": "Save applicability decision",
    "public-copy": "Approve this public copy",
}
_CONFLICTS = (
    commands.ProgrammeVersionConflictError,
    commands.ProgrammeIdempotencyConflictError,
    commands.ProgrammeLifecycleConflictError,
    commands.ProgrammeLimitConflictError,
)
_MAX_INPUT_LENGTH = 6000
_UNAVAILABLE_MESSAGE = (
    "Programme is temporarily unavailable. No partial content is shown. "
    "Retry the same request before starting a new command."
)


def _selection(request: HttpRequest, task: str | None = None) -> None:
    if request.GET or request.FILES or (task is not None and task not in _READS):
        raise ValueError
    if request.method == "POST" and task is not None and task not in _FORMS:
        raise ValueError


def _authorize(
    scope: ProgrammeWorkbenchRequest, task: str, *, write: bool = False
) -> None:
    capability, fields = (_WRITES[task], None) if write else _READS[task]
    admitted = authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
        requested_fields=fields,
    )
    if write:
        if task == "public-copy":
            edition = resolve_scheduling_edition_reference(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            )
            if edition is None or not edition.accepts_scheduling_writes:
                raise ProgrammeAuthorizationDeniedError
        elif not admitted.accepts_private_planning_writes:
            raise ProgrammeAuthorizationDeniedError


def _allowed(
    scope: ProgrammeWorkbenchRequest, task: str, *, write: bool = False
) -> bool:
    if write and task not in _WRITES:
        return False
    try:
        _authorize(scope, task, write=write)
    except ProgrammeAuthorizationDeniedError:
        return False
    return True


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _html(
    request: HttpRequest, context: dict[str, Any], status: int = 200
) -> HttpResponse:
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(has_permission=True, maru_csp_nonce=nonce, title="Programme items")
    shell.update(context)
    content = render_to_string("programme/workbench.html", shell, request=request)
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        return _secure(
            HttpResponse("Programme output is unavailable.", status=503), nonce
        )
    return _secure(HttpResponse(content, status=status), nonce)


def _scope(
    request: HttpRequest, organization_id: UUID, edition_id: UUID
) -> ProgrammeWorkbenchRequest:
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        raise ProgrammeAuthorizationDeniedError
    return ProgrammeWorkbenchRequest(actor_id, organization_id, edition_id, uuid4())


def _root(scope: ProgrammeWorkbenchRequest) -> str:
    return f"/admin/programme/items/{scope.organization_id}/{scope.edition_id}/"


def _context(scope: ProgrammeWorkbenchRequest) -> dict[str, Any]:
    return {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "root_url": _root(scope),
    }


def _input(request: HttpRequest, form_type: type[ProgrammeWorkbenchForm]) -> None:
    if (
        request.GET
        or request.FILES
        or set(request.POST) - {*form_type.base_fields, "csrfmiddlewaretoken"}
    ):
        raise ValueError
    if any(
        len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
        for _, values in request.POST.lists()
    ):
        raise ValueError


def _submit(
    scope: ProgrammeWorkbenchRequest,
    task: str,
    form: ProgrammeWorkbenchForm,
    item_id: UUID | None,
) -> commands.ProgrammeCommandResult:
    functions: dict[str, Callable[..., commands.ProgrammeCommandResult]] = {
        "create": commands.create_organizer_core_item,
        "working": commands.revise_programme_working,
        "delivery": commands.revise_programme_delivery,
        "readiness": commands.configure_programme_readiness,
        "public-copy": commands.approve_programme_public_rendition,
    }
    kwargs = {
        **asdict(scope),
        **form.cleaned_data,
        "source_channel": "programme-workbench",
    }
    if item_id is not None:
        kwargs["item_id"] = item_id
    return functions[task](**kwargs)


def _post(
    scope: ProgrammeWorkbenchRequest,
    task: str,
    form: ProgrammeWorkbenchForm,
    item_id: UUID | None,
) -> tuple[HttpResponse | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        result = _submit(scope, task, form, item_id)
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            for key, messages in error.message_dict.items():
                for message in messages:
                    form.add_error(key if key in form.fields else None, message)
        else:
            form.add_error(
                None, "The command could not accept these values. Review the fields."
            )
        return None, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "The item, lifecycle or retry state has changed. Your original version "
            "and input are retained. Review the latest item before making "
            "a new attempt.",
        )
        return None, 409
    return _secure(
        HttpResponseRedirect(
            f"{_root(scope)}{result.item_id}/{'working' if task == 'create' else task}/"
        )
    ), 302


def _layer(
    scope: ProgrammeWorkbenchRequest, item_id: UUID, task: str
) -> dict[str, Any]:
    kwargs = {
        **asdict(scope),
        "item_id": item_id,
        "source_channel": "programme-workbench",
    }
    if task == "public-copy":
        return {"public_copy": queries.load_programme_public_copy(**kwargs)}
    kwargs["reason"] = f"Review selected Programme {_LABELS[task].lower()}"
    if task == "readiness":
        return {
            "readiness_cards": tuple(
                (row, row.concern.replace("_", " ").capitalize())
                for row in queries.load_programme_readiness(**kwargs)
            )
        }
    loaders: dict[str, Callable[..., object]] = {
        "delivery": queries.load_programme_delivery,
        "working-history": queries.list_programme_working_history,
        "delivery-history": queries.list_programme_delivery_history,
        "readiness-history": queries.list_programme_readiness_history,
        "public-copy-history": queries.list_programme_public_copy_review_history,
    }
    if task not in loaders:
        return {}
    if task.endswith("-history"):
        kwargs["limit"] = 200
        return {"history": loaders[task](**kwargs), "history_selected": True}
    return {task: loaders[task](**kwargs)}


def _item_context(
    scope: ProgrammeWorkbenchRequest, item_id: UUID, task: str
) -> dict[str, Any]:
    _authorize(scope, "working")
    _authorize(scope, task)
    item = load_programme_workbench_item(scope, item_id=item_id)
    return {
        **_context(scope),
        **_layer(scope, item_id, task),
        "selected": item,
        "task": task,
        "task_label": _LABELS[task],
        "button_label": _BUTTONS.get(task),
        "links": tuple(
            (name, label) for name, label in _LABELS.items() if _allowed(scope, name)
        ),
    }


def _initial(context: dict[str, Any], task: str) -> dict[str, Any]:
    item: ProgrammeWorkbenchItem = context["selected"]
    initial: dict[str, Any] = {
        "expected_version": item.private.item.aggregate_version,
        "idempotency_key": uuid4(),
    }
    if task == "working" and item.private.working:
        initial.update(
            internal_title=item.private.working.internal_title,
            working_summary=item.private.working.working_summary,
        )
    if task == "delivery" and context.get("delivery"):
        delivery = context["delivery"]
        initial.update(
            technical_requirements=delivery.technical_requirements,
            accessibility_delivery=delivery.accessibility_delivery,
            media_consent_notes=delivery.media_consent_notes,
        )
    if task == "public-copy":
        initial["source_working_revision_id"] = item.working_revision_id
    return initial


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_items(
    request: HttpRequest, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Select labelled items or create organizer-owned private work.

    Parameters
    ----------
    request : HttpRequest
        Authenticated browser request with closed, CSRF-protected POST input.
    organization_id : UUID
        Expected exact owner from the reserved dormant route.
    edition_id : UUID
        Exact edition, independently authorized before any private lookup.

    Returns
    -------
    HttpResponse
        Shared-shell inventory, safe failure or post-command redirect.
    """
    try:
        scope = _scope(request, organization_id, edition_id)
        _authorize(scope, "working")
        _selection(request)
        context = _context(scope)
        inventory = load_programme_workbench_inventory(scope)
        context.update(inventory=inventory, button_label=_BUTTONS["create"])
        if request.method == "POST":
            _authorize(scope, "create", write=True)
            _input(request, ProgrammeCoreForm)
            form = ProgrammeCoreForm(request.POST)
            response, status = _post(scope, "create", form, None)
            if response is not None:
                messages.success(
                    request, "Private Programme item created.", fail_silently=True
                )
                return response
            _authorize(scope, "working")
            _authorize(scope, "create", write=True)
            context.update(
                form=form, message="Item not created. Review the form below."
            )
            return _html(request, context, status)
        if _allowed(scope, "create", write=True):
            context["form"] = ProgrammeCoreForm(
                initial={
                    "expected_version": inventory.control_version,
                    "idempotency_key": uuid4(),
                }
            )
        return _html(request, context)
    except ProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Programme page not found.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme request.", status=400))
    except (DatabaseError, queries.ProgrammeQueryError, commands.ProgrammeCommandError):
        return _secure(HttpResponse(_UNAVAILABLE_MESSAGE, status=503))


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_item(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    task: str,
) -> HttpResponse:
    """Read or edit one independently authorized item layer.

    Parameters
    ----------
    request : HttpRequest
        Authenticated browser request; never carries trusted actor or tenant IDs.
    organization_id : UUID
        Expected exact owner from the reserved dormant route.
    edition_id : UUID
        Exact edition, reauthorized by each owning read and command.
    item_id : UUID
        Exact selected item; no account-directory discovery is performed.
    task : str
        Closed working, delivery, readiness, public-copy or history task.

    Returns
    -------
    HttpResponse
        Shared-shell selected layer, safe failure or fresh-read redirect.
    """
    try:
        scope = _scope(request, organization_id, edition_id)
        _authorize(scope, "working")
        _selection(request, task)
        context = _item_context(scope, item_id, task)
        if request.method == "POST":
            _authorize(scope, task, write=True)
            _input(request, _FORMS[task])
            form = _FORMS[task](request.POST)
            response, status = _post(scope, task, form, item_id)
            if response is not None:
                messages.success(
                    request,
                    "Programme decision saved; publication is separate.",
                    fail_silently=True,
                )
                return response
            # Recheck displayed layers after refusal before returning private input.
            context = _item_context(scope, item_id, task)
            _authorize(scope, task, write=True)
            context.update(
                form=form, message="Changes not saved. Review the form below."
            )
            return _html(request, context, status)
        if (
            _allowed(scope, task, write=True)
            and context["selected"].private.item.lifecycle == "active"
        ):
            context["form"] = _FORMS[task](initial=_initial(context, task))
        return _html(request, context)
    except ProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Programme page not found.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme request.", status=400))
    except (DatabaseError, queries.ProgrammeQueryError, commands.ProgrammeCommandError):
        return _secure(HttpResponse(_UNAVAILABLE_MESSAGE, status=503))
