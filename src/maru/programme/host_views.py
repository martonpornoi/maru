"""Dormant organizer hosting tasks with independent roster and writer authority."""

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

from . import commands, host_commands, host_queries, queries
from .authorization import (
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from .host_catalogs import HOST_TERMINAL_STATES, MAX_HOSTS_PER_ITEM
from .host_forms import (
    ProgrammeHostReinvitationForm,
    ProgrammeHostRemovalForm,
)
from .host_inputs import ProgrammeHostInvitationInput
from .workbench_queries import ProgrammeWorkbenchRequest, load_programme_workbench_item
from .workbench_views import _CONFLICTS, _secure

if TYPE_CHECKING:
    from django import forms

    from .workbench_forms import ProgrammeWorkbenchForm

_FORMS: dict[str, type[ProgrammeWorkbenchForm]] = {
    "reinvite": ProgrammeHostReinvitationForm,
    "remove": ProgrammeHostRemovalForm,
}
_LABELS = {
    "roster": "Hosts",
    "invite": "Invite a host",
    "reinvite": "Invite again",
    "remove": "Remove hosting",
    "history": "Host history",
    "availability": "Shared availability",
}
_READ_FIELDS = {"history": "host_history", "availability": "shared_host_availability"}
_MAX_INPUT_LENGTH = 6000


def _scope(
    request: HttpRequest, organization_id: UUID, edition_id: UUID
) -> ProgrammeWorkbenchRequest:
    if not isinstance(request.user.pk, UUID):
        raise ProgrammeAuthorizationDeniedError
    return ProgrammeWorkbenchRequest(
        request.user.pk, organization_id, edition_id, uuid4()
    )


def _authorize(
    scope: ProgrammeWorkbenchRequest,
    capability: str,
    fields: frozenset[str] | None = None,
) -> AuthorizedProgrammeScope:
    return authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
        requested_fields=fields,
    )


def _allowed(
    scope: ProgrammeWorkbenchRequest,
    capability: str,
    fields: frozenset[str] | None = None,
    *,
    planning: bool = False,
) -> bool:
    try:
        admitted = _authorize(scope, capability, fields)
    except ProgrammeAuthorizationDeniedError:
        return False
    return not planning or admitted.accepts_private_planning_writes


def _html(
    request: HttpRequest, context: dict[str, Any], status: int = 200
) -> HttpResponse:
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        maru_personal_surface=context.get("personal", False),
        title=context["page_title"],
    )
    shell.update(context)
    html = render_to_string("programme/hosts.html", shell, request=request)
    if len(html.encode("utf-8")) > 8 * 1024 * 1024:
        return _secure(
            HttpResponse("Hosting output is unavailable.", status=503), nonce
        )
    return _secure(HttpResponse(html, status=status), nonce)


def _input(request: HttpRequest, permitted: set[str]) -> None:
    if (
        request.GET
        or request.FILES
        or set(request.POST) - {*permitted, "csrfmiddlewaretoken"}
    ):
        raise ValueError
    if any(
        len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
        for _, values in request.POST.lists()
    ):
        raise ValueError


def _errors(form: forms.Form, error: ValidationError) -> None:
    if hasattr(error, "message_dict"):
        for field, entries in error.message_dict.items():
            for message in entries:
                form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(
            None, "The owner could not accept these values. Review your input."
        )


def _conflict(form: forms.Form) -> None:
    form.add_error(
        None,
        "The relationship, source or retry state changed. Original versions and input "
        "are retained. Review the latest state before starting a new attempt.",
    )


def _host_request(
    scope: ProgrammeWorkbenchRequest, item_id: UUID
) -> host_queries.ProgrammeHostReadRequest:
    return host_queries.ProgrammeHostReadRequest(**asdict(scope), item_id=item_id)


def _root(scope: ProgrammeWorkbenchRequest, item_id: UUID) -> str:
    return (
        f"/admin/programme/hosts/{scope.organization_id}/{scope.edition_id}/{item_id}/"
    )


def _context(
    scope: ProgrammeWorkbenchRequest, item_id: UUID, task: str, host_id: UUID | None
) -> dict[str, Any]:
    _authorize(
        scope,
        "programme.view_private",
        frozenset({"item_summaries", "working_information"}),
    )
    _authorize(scope, "programme.view_hosts", frozenset({"host_roster"}))
    if task in _READ_FIELDS:
        _authorize(scope, "programme.view_hosts", frozenset({_READ_FIELDS[task]}))
    selected = load_programme_workbench_item(scope, item_id=item_id)
    if selected.private.working is None:
        raise queries.ProgrammeQueryUnavailableError
    request = _host_request(scope, item_id)
    roster = host_queries.load_programme_host_roster(request)
    if roster.item_version != selected.private.item.aggregate_version:
        raise queries.ProgrammeQueryUnavailableError
    entry = next(
        (row for row in roster.entries if row.relationship.host_id == host_id), None
    )
    if host_id is not None and entry is None:
        raise ProgrammeAuthorizationDeniedError
    context: dict[str, Any] = {
        "page_title": f"{_LABELS[task]} — {selected.private.working.internal_title}",
        "item_title": selected.private.working.internal_title,
        "item_state": selected.private.item.lifecycle,
        "item_id": item_id,
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "root_url": _root(scope, item_id),
        "item_url": (
            f"/admin/programme/items/{scope.organization_id}/"
            f"{scope.edition_id}/{item_id}/working/"
        ),
        "roster": roster,
        "entry": entry,
        "task": task,
        "task_label": _LABELS[task],
        "can_manage": selected.private.item.lifecycle == "active"
        and _allowed(scope, "programme.manage_hosts", planning=True),
        "can_history": _allowed(
            scope, "programme.view_hosts", frozenset({"host_history"})
        ),
        "can_availability": _allowed(
            scope, "programme.view_hosts", frozenset({"shared_host_availability"})
        ),
    }
    if task == "history":
        if host_id is None or entry is None:
            raise ValueError
        context["history"] = host_queries.load_programme_host_history(
            request, host_id=host_id
        )
        if (
            not context["history"]
            or context["history"][-1].relationship.version != entry.relationship.version
        ):
            raise queries.ProgrammeQueryUnavailableError
    elif task == "availability":
        snapshot = host_queries.load_programme_host_dependencies(request)
        labels = {row.relationship.host_id: row.display_label for row in roster.entries}
        versions = {
            row.relationship.host_id: row.relationship.version for row in roster.entries
        }
        if (
            snapshot.item_version != roster.item_version
            or set(labels) != {row.host_id for row in snapshot.hosts}
            or any(
                versions.get(row.host_id) != row.host_version for row in snapshot.hosts
            )
        ):
            raise queries.ProgrammeQueryUnavailableError
        context["shared_availability"] = tuple(
            (labels[row.host_id], row) for row in snapshot.hosts
        )
    context["can_invite"] = _can_edit(context, "invite")
    return context


def _manager_submit(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    task: str,
    form: ProgrammeWorkbenchForm,
    context: dict[str, Any],
) -> None:
    values = form.cleaned_data
    common = {
        **asdict(scope),
        "item_id": item_id,
        "idempotency_key": values["idempotency_key"],
        "reason": values["reason"],
        "source_channel": "programme-hosts",
    }
    if task == "remove":
        host_commands.remove_programme_host(
            **common,
            host_id=context["entry"].relationship.host_id,
            expected_item_version=values["expected_version"],
            expected_host_version=values["expected_host_version"],
        )
        return
    account_id = context["entry"].account_id
    host_version = values["expected_host_version"]
    host_commands.invite_programme_host(
        **common,
        invitation=ProgrammeHostInvitationInput(
            account_id,
            values["role"],
            values["title"],
            values["briefing"],
            values["expected_version"],
            host_version,
        ),
    )


def _write(scope: ProgrammeWorkbenchRequest) -> None:
    if not _authorize(scope, "programme.manage_hosts").accepts_private_planning_writes:
        raise ProgrammeAuthorizationDeniedError


def _selection(request: HttpRequest, task: str, host_id: UUID | None) -> None:
    if request.GET or request.FILES or task not in _LABELS or task == "invite":
        raise ValueError
    if (host_id is not None) != (task in {"reinvite", "remove", "history"}):
        raise ValueError
    if request.method == "POST" and task not in _FORMS:
        raise ValueError


def _can_edit(context: dict[str, Any], task: str) -> bool:
    if not context["can_manage"]:
        return False
    if task == "invite":
        return len(context["roster"].entries) < MAX_HOSTS_PER_ITEM
    entry = context["entry"]
    if entry is None:
        return False
    if task == "reinvite":
        return entry.person_current and entry.relationship.state in HOST_TERMINAL_STATES
    return task == "remove" and entry.relationship.state in {"invited", "confirmed"}


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_hosts(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    task: str = "roster",
    host_id: UUID | None = None,
) -> HttpResponse:
    """Read and manage exact labelled hosting without impersonating the person.

    Parameters
    ----------
    request : HttpRequest
        Authenticated shared-shell request with closed CSRF-protected input.
    organization_id : UUID
        Exact expected organizer scope, not a permission claim.
    edition_id : UUID
        Exact current edition, independently authorized by every owner seam.
    item_id : UUID
        Exact Programme item selected from a labelled private workspace.
    task : str, default='roster'
        Closed roster, invitation, removal, history or availability task.
    host_id : UUID | None, default=None
        Exact retained roster selection for reinvitation, removal or history.

    Returns
    -------
    HttpResponse
        Authorized task, fresh-read redirect or non-disclosing bounded failure.
    """
    try:
        scope = _scope(request, organization_id, edition_id)
        _selection(request, task, host_id)
        context = _context(scope, item_id, task, host_id)
        if request.method == "POST":
            _write(scope)
            _input(request, set(_FORMS[task].base_fields))
            form = _FORMS[task](request.POST)
            status = 400
            if form.is_valid():
                try:
                    _manager_submit(scope, item_id, task, form, context)
                except ValidationError as error:
                    _errors(form, error)
                except _CONFLICTS:
                    _conflict(form)
                    status = 409
                else:
                    messages.success(
                        request,
                        "Hosting decision recorded. Invitation recording is not "
                        "email delivery or the person's confirmation.",
                        fail_silently=True,
                    )
                    return _secure(HttpResponseRedirect(_root(scope, item_id)))
            context = _context(scope, item_id, task, host_id)
            _write(scope)
            context.update(
                form=form, message="Hosting decision not saved. Review the form."
            )
            return _html(request, context, status)
        if task in _FORMS and _can_edit(context, task):
            initial = {
                "expected_version": context["roster"].item_version,
                "idempotency_key": uuid4(),
            }
            if context["entry"] is not None:
                initial["expected_host_version"] = context["entry"].relationship.version
            context["form"] = _FORMS[task](initial=initial)
        return _html(request, context)
    except ProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Hosting page not found.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported hosting request.", status=400))
    except (DatabaseError, queries.ProgrammeQueryError, commands.ProgrammeCommandError):
        return _secure(
            HttpResponse(
                "Hosting is unavailable. No partial content is shown.", status=503
            )
        )
