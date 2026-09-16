"""Original-intent upload and deliberate clear tasks in the personal shell."""

from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_commands as answers
from . import programme_file_commands as commands
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_views import _secure
from .programme_file_commands import _DEFAULT, _arguments, _question
from .programme_file_forms import (
    MAX_FILE_INTENT_BYTES,
    ProgrammeFileClearForm,
    _decode,
    _encode,
)
from .programme_file_preparation import ProgrammeFileUnavailableError
from .programme_file_transport import _source_request
from .programme_proposal_views import _CONFLICTS, _UNAVAILABLE, _html, _root, _Scope
from .programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
    _fresh,
    _source,
)


def _transport(request: HttpRequest, task: str) -> str:
    if task not in {"upload", "clear"} or request.FILES:
        raise ValueError
    if task == "upload":
        if request.method != "GET" or set(request.GET) - {"intent"}:
            raise ValueError
        values = request.GET.getlist("intent")
        if len(values) > 1 or (values and not values[0]):
            raise ValueError
        return values[0] if values else ""
    if request.GET or set(request.POST) - {"token", "confirm", "csrfmiddlewaretoken"}:
        raise ValueError
    if any(
        len(values) != 1 or len(values[0]) > MAX_FILE_INTENT_BYTES
        for _, values in request.POST.lists()
    ):
        raise ValueError
    return ""


def _task(
    request: HttpRequest, source: ProgrammeAnswerReferenceRequest, task: str, token: str
) -> HttpResponse:
    scope = _Scope(
        source.actor_id,
        source.organization_id,
        source.edition_id,
        source.correlation_id,
    )
    proposal_url = f"{_root(scope)}{source.proposal_id}/work/"
    root = proposal_url + f"answer/{source.question_id}/file/"
    values: dict[str, Any] = {
        "task": "file",
        "file_task": task,
        "proposal_url": proposal_url,
        "file_upload_url": root,
        "file_intake_url": root + "intake/",
    }
    # Retained recovery requires only original retry authority, not new edit permission.
    if token:
        intent = _decode(source, token, purpose="upload")

        def verify_recovery() -> None:
            commands.get_programme_file_upload_result(request=source, intent=intent)

        values.update(
            token=token, recovery=True, question_label="Original supporting-file upload"
        )
        return _html(request, scope, values, verify_recovery)

    form = ProgrammeFileClearForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid():
        intent = _decode(source, form.cleaned_data["token"], purpose="clear")
        try:
            answers.append_programme_proposal_answer(
                **asdict(source),
                **asdict(intent),
                value=None,
                reason="Clear this supporting-file answer.",
            )
            return _secure(HttpResponseRedirect(proposal_url))
        except _CONFLICTS:
            form.add_error(
                None,
                "The original clear request conflicts with current state. Your "
                "intent is retained. Check proposal history before starting "
                "another request.",
            )
            status = 409
        except (*_UNAVAILABLE, ValidationError):
            form.add_error(
                None,
                "Clearing is not confirmed. Your original intent is retained; "
                "check proposal history before retrying.",
            )
            status = 503
    elif request.method == "POST":
        status = 400

    admitted = _source(source, _DEFAULT)
    context, detail = admitted
    rows = tuple(
        row
        for row in detail.answers or ()
        if row.question.question_id == source.question_id
    )
    if len(rows) != 1 or rows[0].question.field_type != "safe_file":
        raise Denied
    question = rows[0].question
    if request.method == "GET":
        intent = ProgrammeAnswerReferenceIntent(
            context.summary.aggregate_version,
            context.call_version,
            context.definition_version,
            uuid4(),
        )
        _fresh(context, intent)
        _question(_arguments(source, intent), context.summary.call_id, lock=False)
        token = _encode(source, intent, purpose=task)
        if task == "clear":
            form = ProgrammeFileClearForm(initial={"token": token})

    def verify() -> None:
        if _source(source, _DEFAULT) != admitted:
            raise Denied

    values.update(
        question_label=question.label, question=question, token=token, form=form
    )
    return _html(request, scope, values, verify, status=status)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_file_task(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    *,
    task: str = "upload",
) -> HttpResponse:
    """Serve a signed original upload task or deliberate current-answer clear.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected task with closed inputs.
    organization_id : UUID
        Exact expected organization.
    edition_id : UUID
        Exact event edition.
    proposal_id : UUID
        Genuine contributor's proposal.
    question_id : UUID
        Exact private supporting-file question.
    task : str, default="upload"
        Code-owned upload or clear route purpose.

    Returns
    -------
    HttpResponse
        Protected task, canonical clear redirect or minimized error.
    """
    try:
        token = _transport(request, task)
        source = _source_request(
            request, organization_id, edition_id, proposal_id, question_id
        )
        response = _task(request, source, task, token)
    except Denied:
        return _secure(
            HttpResponse(
                "This file task is unavailable. Check authorized history "
                "after an uncertain attempt.",
                status=404,
            )
        )
    except _CONFLICTS:
        return _secure(
            HttpResponse(
                "This file task is no longer current. Check the original result "
                "or proposal history before starting another attempt.",
                status=409,
            )
        )
    except (*_UNAVAILABLE, ProgrammeFileUnavailableError):
        return _secure(
            HttpResponse(
                "File handling is unavailable. An earlier attempt may have "
                "committed; check its original result.",
                status=503,
            )
        )
    except (ValueError, TypeError, ValidationError):
        return _secure(
            HttpResponse("Use the complete original supporting-file task.", status=400)
        )
    else:
        if task == "upload" and response.status_code == HTTPStatus.OK:
            # Only this task needs same-origin fetch for raw intake and recovery.
            # All script, framing and default-deny restrictions remain unchanged.
            response["Content-Security-Policy"] += "; connect-src 'self'"
        return response
