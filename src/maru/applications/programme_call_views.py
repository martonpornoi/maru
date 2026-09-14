"""Dedicated dormant call workspace using Applications' existing owner seams."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.core.forms import StrictBase10IntegerField
from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from . import programme_call_editor as editor
from . import programme_call_forms as forms
from . import programme_commands as commands
from . import programme_queries as queries
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_call_scope,
)
from .programme_write_scope import (
    ApplicationsProgrammeWriteScopeUnavailableError,
    lock_programme_edition_write_scope,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-call-workspace"
_MAX_INPUT_LENGTH = 6000
_FORMS: dict[str, type[forms.ProgrammeCallTaskForm]] = {
    "details": forms.ProgrammeCallDetailsForm,
    "window": forms.ProgrammeCallWindowForm,
    "track": forms.ProgrammeCallTrackForm,
    "format": forms.ProgrammeCallFormatForm,
    "contributor-field": forms.ProgrammeCallContributorFieldForm,
    **dict.fromkeys(
        (
            "activate",
            "retire",
            "successor",
            "remove-track",
            "remove-format",
            "remove-contributor-field",
        ),
        forms.ProgrammeCallConfirmationForm,
    ),
}
_CATALOGS = {
    "track": "tracks",
    "format": "formats",
    "contributor-field": "contributor_fields",
}
_LABELS = {
    "overview": "Complete call configuration",
    "details": "Call details and policy",
    "window": "Replace deadlines",
    "track": "Edit track",
    "format": "Edit format",
    "contributor-field": "Contributor collection policy",
    "activate": "Activate domain call",
    "retire": "Retire call",
    "successor": "Create successor draft",
    "remove-track": "Remove track",
    "remove-format": "Remove format",
    "remove-contributor-field": "Remove contributor field",
}
_BUTTONS = {
    "details": "Save details and policy",
    "window": "Replace these deadlines",
    "track": "Save track",
    "format": "Save format",
    "contributor-field": "Save collection policy",
}
_CONSEQUENCES = {
    "activate": (
        "Make this complete call configuration immutable. This does not publish "
        "or discover the call, enable a profile, or mount a production route."
    ),
    "retire": (
        "Retire this domain call. Retained proposals and historical evidence are "
        "not erased. A new successor draft is a separate action."
    ),
    "successor": (
        "Copy this retired call's complete configuration into an independent "
        "successor draft. The original stays retired and historical proposals "
        "stay with it."
    ),
    "window": (
        "Replace all three deadlines with the displayed whole-minute local "
        "times. Original sub-minute precision is deliberately replaced only "
        "by this task."
    ),
    "remove-track": (
        "Remove the selected track from this draft. The call must retain "
        "at least one track."
    ),
    "remove-format": (
        "Remove the selected format from this draft. The call must retain "
        "at least one format."
    ),
    "remove-contributor-field": (
        "Remove this proposed-public collection field from the draft policy. "
        "The lead's required public display name cannot be removed. "
        "No person's profile is changed."
    ),
}
_CONFLICTS = (
    commands.ApplicationsProgrammeVersionConflictError,
    commands.ApplicationsProgrammeStateConflictError,
    commands.ApplicationsProgrammeIdempotencyConflictError,
    editor.ProgrammeCallEditorConflictError,
)
_UNAVAILABLE = (
    DatabaseError,
    commands.ApplicationsProgrammeUnavailableError,
    ApplicationsProgrammeWriteScopeUnavailableError,
    queries.ApplicationsProgrammeProjectionOverflowError,
)


@dataclass(frozen=True, slots=True)
class _Scope:
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    correlation_id: UUID


def _scope_values(scope: _Scope) -> dict[str, Any]:
    return {**asdict(scope), "source_channel": _SOURCE}


def _authorize(scope: _Scope) -> bool:
    result = authorize_programme_call_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    return result.accepts_private_planning_writes


def _root(scope: _Scope) -> str:
    return (
        f"/admin/applications/programme-calls/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/"
    )


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    nonce = nonce or token_urlsafe(32)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _render(
    request: HttpRequest,
    scope: _Scope,
    context: dict[str, Any],
    status: int = 200,
    *,
    template: str = "applications/programme_calls.html",
) -> HttpResponse:
    _authorize(scope)
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(has_permission=True, title="Programme calls", maru_csp_nonce=nonce)
    shell.update(root_url=_root(scope), **context)
    content = render_to_string(template, shell, request=request)
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        return _secure(HttpResponse("Call workspace unavailable.", status=503), nonce)
    _authorize(scope)
    return _secure(HttpResponse(content, status=status), nonce)


def _editable(task: str, status: str, *, planning: bool) -> bool:
    required = {"retire": "active", "successor": "retired"}.get(task, "draft")
    return planning and status == required and task in _FORMS


def _form(
    request: HttpRequest,
    task: str,
    source: queries.ProgrammeCallConfigurationProjection,
    *,
    row: int | None,
    zone: str,
    edition_version: int,
) -> forms.ProgrammeCallTaskForm:
    initial: dict[str, Any] = {
        "expected_version": source.summary.aggregate_version,
        "retry_key": uuid4(),
    }
    kwargs: dict[str, Any] = {}
    catalog = _CATALOGS.get(task.removeprefix("remove-"))
    if catalog is not None and row is None:
        initial["position"] = len(getattr(source, catalog)) + 1
    if catalog is not None and row is not None:
        values = getattr(source, catalog)
        if 0 <= row < len(values):
            initial.update(
                {
                    name: getattr(values[row], name)
                    for name in _FORMS[task].base_fields
                    if hasattr(values[row], name)
                }
            )
        elif request.method != "POST":
            raise ValueError
    if task in {"details", "window"}:
        kwargs["inputs"] = editor.programme_call_editor_inputs(
            source, expected_version=source.summary.aggregate_version
        )
    if task == "window":
        initial["expected_edition_version"] = edition_version
        kwargs["edition_time_zone"] = zone
    return _FORMS[task](
        request.POST if request.method == "POST" else None, initial=initial, **kwargs
    )


def _compose(
    source: queries.ProgrammeCallConfigurationProjection,
    task: str,
    form: forms.ProgrammeCallTaskForm,
    row: int | None,
) -> editor.ProgrammeCallEditorInputs:
    graph = editor.programme_call_editor_inputs(
        source, expected_version=form.cleaned_data["expected_version"]
    )
    if isinstance(
        form, (forms.ProgrammeCallDetailsForm, forms.ProgrammeCallWindowForm)
    ):
        if form.result is None:
            raise ValidationError("Review the complete call input.")
        return form.result
    if task.endswith("track"):
        return editor.edit_programme_call_track(
            graph,
            index=row,
            value=None
            if task.startswith("remove-")
            else forms.ProgrammeCallTrackForm.track_input(form.cleaned_data),
        )
    if task.endswith("format"):
        return editor.edit_programme_call_format(
            graph,
            index=row,
            value=None
            if task.startswith("remove-")
            else forms.ProgrammeCallFormatForm.format_input(form.cleaned_data),
        )
    if task.endswith("contributor-field"):
        return editor.edit_programme_call_contributor_field(
            graph,
            index=row,
            value=None
            if task.startswith("remove-")
            else forms.ProgrammeCallContributorFieldForm.contributor_field_input(
                form.cleaned_data
            ),
        )
    raise ValueError


def _command(
    scope: _Scope,
    source: queries.ProgrammeCallConfigurationProjection,
    task: str,
    form: forms.ProgrammeCallTaskForm,
    row: int | None,
) -> commands.ProgrammeCommandResult:
    common = {
        "actor_id": scope.actor_id,
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "owner_department_id": scope.department_id,
        "call_id": source.summary.call_id,
        "correlation_id": scope.correlation_id,
        "source_channel": _SOURCE,
        **{
            name: form.cleaned_data[name]
            for name in ("expected_version", "reason", "retry_key")
        },
    }
    lifecycle: dict[str, Callable[..., commands.ProgrammeCommandResult]] = {
        "activate": commands.activate_programme_call,
        "retire": commands.retire_programme_call,
        "successor": commands.create_programme_call_successor,
    }
    if task in lifecycle:
        return lifecycle[task](**common)
    graph = _compose(source, task, form, row)
    if task != "window":
        return commands.configure_programme_call(
            **common,
            definition_input=graph.definition,
            configuration=graph.configuration,
        )
    # Keep the displayed zone/version stable through the owner's nested command.
    with transaction.atomic():
        lock_programme_edition_write_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_ids=(scope.department_id,),
        )
        _authorize(scope)
        edition = resolve_scheduling_edition_reference(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        if (
            edition is None
            or edition.version != form.cleaned_data["expected_edition_version"]
        ):
            raise editor.ProgrammeCallEditorConflictError
        return commands.configure_programme_call(
            **common,
            definition_input=graph.definition,
            configuration=graph.configuration,
        )


def _post(
    scope: _Scope,
    source: queries.ProgrammeCallConfigurationProjection,
    task: str,
    form: forms.ProgrammeCallTaskForm,
    row: int | None,
    edition_version: int,
) -> tuple[HttpResponse | None, int]:
    try:
        original = StrictBase10IntegerField().clean(form.data.get("expected_version"))
        if original != source.summary.aggregate_version:
            raise editor.ProgrammeCallEditorConflictError
        if (
            task == "window"
            and StrictBase10IntegerField(min_value=1).clean(
                form.data.get("expected_edition_version")
            )
            != edition_version
        ):
            raise editor.ProgrammeCallEditorConflictError
        if not form.is_valid():
            return None, 400
        result = _command(scope, source, task, form, row)
    except _CONFLICTS:
        form.add_error(
            None,
            "The call, edition or retry state changed. Your original input and "
            "version are retained. An earlier attempt may already have succeeded; "
            "review the current call before starting a fresh attempt. Deadlines "
            "are not reinterpreted in a changed edition zone.",
        )
        return None, 409
    except commands.ApplicationsProgrammeCompletenessError:
        form.add_error(
            None,
            "The call is incomplete. Review its complete configuration "
            "before attempting this action again.",
        )
        return None, 400
    except ValidationError as error:
        if hasattr(error, "error_dict"):
            for name, errors in error.error_dict.items():
                form.add_error(name if name in form.fields else None, errors)
        else:
            form.add_error(None, error)
        return None, 400
    return _secure(
        HttpResponseRedirect(f"{_root(scope)}{result.target_id}/overview/")
    ), 302


def _request_scope(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None,
    task: str,
    row: int | None,
) -> _Scope:
    if not isinstance(request.user.pk, UUID):
        raise ApplicationsProgrammeAuthorizationDeniedError
    scope = _Scope(request.user.pk, organization_id, edition_id, department_id, uuid4())
    if request.GET or request.FILES or task not in _LABELS:
        raise ValueError
    if row is not None and task.removeprefix("remove-") not in _CATALOGS:
        raise ValueError
    if task.startswith("remove-") and row is None:
        raise ValueError
    if request.method == "POST":
        if call_id is None or task not in _FORMS:
            raise ValueError
        allowed = {*_FORMS[task].base_fields, "csrfmiddlewaretoken"}
        if set(request.POST) - allowed or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        ):
            raise ValueError
    return scope


def _serve(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None,
    task: str,
    row: int | None,
) -> HttpResponse:
    scope = _request_scope(
        request, organization_id, edition_id, department_id, call_id, task, row
    )
    planning = _authorize(scope)
    department = queries.get_managed_programme_call_department(**_scope_values(scope))
    context: dict[str, Any] = {
        "department": department,
        "task": task,
        "task_label": _LABELS[task],
        "button_label": _BUTTONS.get(task, _LABELS[task]),
        "consequence": _CONSEQUENCES.get(task, ""),
        "pending": request.method == "POST",
    }
    if row is None and task in _CATALOGS:
        context["task_label"] = {
            "track": "Add track",
            "format": "Add format",
            "contributor-field": "Add contributor collection field",
        }[task]
        context["button_label"] = context["task_label"]
    if call_id is None:
        context["can_create"] = planning
        context["calls"] = queries.list_managed_programme_calls(**_scope_values(scope))
        return _render(request, scope, context)
    source = queries.get_managed_programme_call_configuration(
        **_scope_values(scope), call_id=call_id
    )
    edition = resolve_scheduling_edition_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    context.update(
        source=source,
        call_url=f"{_root(scope)}{call_id}/",
        zone_name=edition.zone_name,
        can_edit=planning and source.summary.status == "draft",
        can_retire=planning and source.summary.status == "active",
        can_successor=planning and source.summary.status == "retired",
    )
    if not _editable(task, source.summary.status, planning=planning):
        if request.method == "POST":
            raise ApplicationsProgrammeAuthorizationDeniedError
        return _render(request, scope, context)
    form = _form(
        request,
        task,
        source,
        row=row,
        zone=edition.zone_name,
        edition_version=edition.version,
    )
    context["form"] = form
    if row is not None:
        catalog = getattr(source, _CATALOGS[task.removeprefix("remove-")])
        context["selected_row"] = catalog[row] if 0 <= row < len(catalog) else None
        context["selected_row_label"] = getattr(
            context["selected_row"],
            "label",
            getattr(context["selected_row"], "field_code", ""),
        )
    status = 200
    if request.method == "POST":
        response, status = _post(scope, source, task, form, row, edition.version)
        if response is not None:
            return response
    return _render(request, scope, context, status)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_calls(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None = None,
    task: str = "overview",
    row: int | None = None,
) -> HttpResponse:
    """Serve a complete exact-Department inventory or one dedicated call task.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request; submitted scope and unknown fields are refused.
    organization_id : UUID
        Selected organization, independently authorized on every request.
    edition_id : UUID
        Exact edition expected to own the Department and call.
    department_id : UUID
        Exact current call-owning Department, without hierarchy inheritance.
    call_id : UUID | None, default=None
        Selected call or ``None`` for the bounded complete inventory.
    task : str, default='overview'
        Closed task discriminator; no generic writer or recovery route.
    row : int | None, default=None
        Exact original catalog offset or ``None`` for a new catalog entry.

    Returns
    -------
    HttpResponse
        Protected HTML, owner-success redirect or a non-disclosing refusal.
    """
    try:
        return _serve(
            request, organization_id, edition_id, department_id, call_id, task, row
        )
    except ApplicationsProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Call workspace unavailable.", status=404))
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "Call workspace temporarily unavailable. No partial content is shown. "
                "Review the current call before a new attempt.",
                status=503,
            )
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("The call workspace cannot accept this request.", status=400)
        )
