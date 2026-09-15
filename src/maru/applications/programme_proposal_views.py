"""Dormant personal Programme intake, separate from organizer management."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
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

from maru.scheduling.personal_navigation import (
    PersonalProgrammeTaskLink,
    personal_programme_task_links,
)

from . import programme_commands as commands
from . import programme_queries as queries
from .programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_proposal_scope,
    authorize_programme_self_entry_scope,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_proposal_forms import ProgrammeProposalStartForm
from .programme_write_scope import ApplicationsProgrammeWriteScopeUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-proposal-workspace"
_MAX_INPUT_LENGTH = 6000
_MINIMAL = frozenset({"proposal_summary", "selection", "own_invitation"})
_OWN_PROFILE = _MINIMAL | {"contributor_profiles"}
_CONFLICTS = (
    commands.ApplicationsProgrammeVersionConflictError,
    commands.ApplicationsProgrammeStateConflictError,
    commands.ApplicationsProgrammeIdempotencyConflictError,
)
_UNAVAILABLE = (
    DatabaseError,
    commands.ApplicationsProgrammeUnavailableError,
    ApplicationsProgrammeWriteScopeUnavailableError,
    queries.ApplicationsProgrammeProjectionError,
)


@dataclass(frozen=True, slots=True)
class _Scope:
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


def _values(scope: _Scope) -> dict[str, Any]:
    return {**asdict(scope), "source_channel": _SOURCE}


def _root(scope: _Scope) -> str:
    return f"/my/applications/programme/{scope.organization_id}/{scope.edition_id}/"


def _entry(scope: _Scope, fields: frozenset[str], *, write: bool = False) -> bool:
    admitted = authorize_programme_self_entry_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=(
            APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
            if write
            else APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF
        ),
        requested_fields=None if write else fields,
    )
    if write and not admitted.accepts_private_planning_writes:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return admitted.accepts_private_planning_writes


def _verify_summary(
    scope: _Scope,
    summary: queries.ProgrammeProposalSummaryProjection,
    fields: frozenset[str],
) -> None:
    admitted = authorize_programme_proposal_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        proposal_id=summary.proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=fields,
    )
    names = (
        "proposal_id",
        "submission_id",
        "call_id",
        "state",
        "aggregate_version",
        "relationship",
    )
    if any(getattr(summary, name) != getattr(admitted, name) for name in names):
        raise ApplicationsProgrammeAuthorizationDeniedError


def _html(
    request: HttpRequest,
    scope: _Scope,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
) -> HttpResponse:
    verify()
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_personal_surface=True,
        maru_csp_nonce=nonce,
        title="My Programme proposals",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    shell.update(context)

    def links() -> tuple[PersonalProgrammeTaskLink, ...]:
        return personal_programme_task_links(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            current="proposals",
            urlconf=getattr(request, "urlconf", None),
        )

    navigation = links()
    shell["personal_task_links"] = navigation
    content = render_to_string("applications/programme_proposals.html", shell, request)
    if navigation and navigation != links():
        shell["personal_task_links"] = ()
        content = render_to_string(
            "applications/programme_proposals.html", shell, request
        )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise queries.ApplicationsProgrammeProjectionOverflowError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _inventory(request: HttpRequest, scope: _Scope) -> HttpResponse:
    _entry(scope, _MINIMAL)
    rows = queries.list_self_programme_proposals(**_values(scope))

    def verify() -> None:
        _entry(scope, _MINIMAL)
        for row in rows:
            _verify_summary(scope, row.summary, _MINIMAL)

    return _html(request, scope, {"task": "inventory", "proposals": rows}, verify)


def _detail(request: HttpRequest, scope: _Scope, proposal_id: UUID) -> HttpResponse:
    admitted = authorize_programme_proposal_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=_MINIMAL,
    )
    fields = _MINIMAL if admitted.relationship == "invited" else _OWN_PROFILE
    detail = queries.get_self_programme_proposal_detail(
        **_values(scope), proposal_id=proposal_id, requested_fields=fields
    )
    summary = detail.summary
    if summary is None or summary.proposal_id != proposal_id:
        raise ApplicationsProgrammeAuthorizationDeniedError
    if (
        detail.requested_fields != fields
        or summary.relationship != admitted.relationship
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError

    def verify() -> None:
        _verify_summary(scope, summary, fields)

    return _html(request, scope, {"task": "detail", "detail": detail}, verify)


def _available(scope: _Scope) -> tuple[queries.AvailableProgrammeCallProjection, ...]:
    _entry(scope, frozenset({"available_calls"}))
    return queries.available_programme_calls(**_values(scope))


def _calls(request: HttpRequest, scope: _Scope) -> HttpResponse:
    planning = _entry(scope, frozenset({"available_calls"}))
    rows = _available(scope) if planning else ()

    def verify() -> None:
        if _entry(scope, frozenset({"available_calls"})) != planning:
            raise ApplicationsProgrammeAuthorizationDeniedError
        if planning and _available(scope) != rows:
            raise ApplicationsProgrammeAuthorizationDeniedError

    return _html(
        request, scope, {"task": "calls", "calls": rows, "planning": planning}, verify
    )


def _call(scope: _Scope, call_id: UUID) -> queries.AvailableProgrammeCallProjection:
    source = next(
        (row for row in _available(scope) if row.summary.call_id == call_id), None
    )
    if source is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return source


def _start(request: HttpRequest, scope: _Scope, call_id: UUID) -> HttpResponse:
    _entry(scope, frozenset(), write=True)
    source = _call(scope, call_id)
    form = ProgrammeProposalStartForm(
        request.POST if request.method == "POST" else None,
        source=source,
        initial={
            "retry_key": uuid4(),
            "expected_version": 0,
            "expected_call_version": source.summary.aggregate_version,
            "expected_definition_version": source.summary.version,
        },
    )
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            try:
                if (
                    values["expected_call_version"] != source.summary.aggregate_version
                    or values["expected_definition_version"] != source.summary.version
                ):
                    raise commands.ApplicationsProgrammeVersionConflictError
                result = _create(scope, call_id, form)
                return _secure(
                    HttpResponseRedirect(f"{_root(scope)}{result.target_id}/")
                )
            except _CONFLICTS:
                status = 409
                form.add_error(
                    None,
                    "The call, source version or retry state changed. Original input "
                    "is retained. An earlier attempt may already have committed; "
                    "check My proposals before starting a new attempt.",
                )
            except ValidationError as error:
                _apply_errors(form, error)

    def verify() -> None:
        _entry(scope, frozenset(), write=True)
        if _call(scope, call_id) != source:
            raise ApplicationsProgrammeAuthorizationDeniedError

    return _html(
        request, scope, {"task": "start", "call": source, "form": form}, verify, status
    )


def _create(
    scope: _Scope, call_id: UUID, form: ProgrammeProposalStartForm
) -> commands.ProgrammeCommandResult:
    if form.selection is None or form.profile is None:
        raise ValidationError("Review the complete draft input.")
    _entry(scope, frozenset(), write=True)
    return commands.start_programme_proposal(
        **_values(scope),
        call_id=call_id,
        selection=form.selection,
        lead_profile=form.profile,
        expected_version=form.cleaned_data["expected_version"],
        reason=form.cleaned_data["reason"],
        retry_key=form.cleaned_data["retry_key"],
    )


def _transport(request: HttpRequest, task: str) -> None:
    if request.GET or request.FILES:
        raise ValueError
    if request.method != "POST":
        return
    permitted = {
        *ProgrammeProposalStartForm.base_fields,
        "public_name",
        "biography",
        "pronouns",
        "website",
        "csrfmiddlewaretoken",
    }
    if task != "start" or set(request.POST) - permitted:
        raise ValueError
    if any(
        len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
        for _, values in request.POST.lists()
    ):
        raise ValueError


def _dispatch(
    request: HttpRequest,
    scope: _Scope,
    task: str,
    call_id: UUID | None,
    proposal_id: UUID | None,
) -> HttpResponse:
    if (
        task not in {"inventory", "calls", "start", "detail"}
        or (call_id is not None) != (task == "start")
        or (proposal_id is not None) != (task == "detail")
    ):
        raise ValueError
    if task == "inventory":
        return _inventory(request, scope)
    if task == "calls":
        return _calls(request, scope)
    if call_id is not None:
        return _start(request, scope, call_id)
    if proposal_id is not None:
        return _detail(request, scope, proposal_id)
    raise ValueError


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_proposals(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    *,
    task: str = "inventory",
    call_id: UUID | None = None,
    proposal_id: UUID | None = None,
) -> HttpResponse:
    """Serve exact-person intake only through dedicated dormant routes.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with closed transport and CSRF protection.
    organization_id : UUID
        Expected owner organization; context never grants authority.
    edition_id : UUID
        Exact event edition for this personal workspace.
    task : str, default="inventory"
        Closed inventory, calls, start or detail task.
    call_id : UUID | None, default=None
        Exact selected call for draft creation only.
    proposal_id : UUID | None, default=None
        Exact relationship-owned proposal for detail only.

    Returns
    -------
    HttpResponse
        Protected personal output, redirect or non-disclosing refusal.
    """
    try:
        _transport(request, task)
        scope = _Scope(UUID(str(request.user.pk)), organization_id, edition_id, uuid4())
        return _dispatch(request, scope, task, call_id, proposal_id)
    except ApplicationsProgrammeAuthorizationDeniedError:
        return _secure(
            HttpResponse(
                "This personal task is unavailable. Return to My proposals to check "
                "any earlier attempt; no new draft is confirmed by this response.",
                status=404,
            )
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("Personal proposal workspace unavailable.", status=503)
        )
    except (ValueError, TypeError):
        return _secure(HttpResponse("Invalid personal task request.", status=400))


__all__ = ["programme_proposals"]
