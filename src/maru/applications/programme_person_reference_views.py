"""Dormant personal reference selection and exact-answer label viewers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_commands as commands
from . import programme_person_references as references
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_person_reference_forms import (
    ProgrammePersonLookupForm,
    ProgrammePersonReferenceForm,
)
from .programme_person_references import _DEFAULT, _answer, _fresh, _source
from .programme_proposal_views import _CONFLICTS, _UNAVAILABLE, _html, _root, _Scope

_SOURCE = "programme-person-reference"
_MAX_INPUT_BYTES = 6000


def _transport(request: HttpRequest, *, edit: bool) -> str:
    if request.GET or request.FILES or (request.method == "POST" and not edit):
        raise ValueError
    if request.method != "POST":
        return "prepare"
    phase = request.POST.get("phase", "")
    allowed = {
        *ProgrammePersonReferenceForm.base_fields,
        "csrfmiddlewaretoken",
        "phase",
    }
    if phase not in {"prepare", "confirm"} or set(request.POST) - allowed:
        raise ValueError
    if any(
        len(values) != 1 or len(values[0].encode("utf-8")) > _MAX_INPUT_BYTES
        for _, values in request.POST.lists()
    ):
        raise ValueError
    return phase


def _intent(values: dict[str, Any]) -> references.ProgrammePersonReferenceIntent:
    return references.ProgrammePersonReferenceIntent(
        **{
            key: values[key]
            for key in references.ProgrammePersonReferenceIntent.__dataclass_fields__
        }
    )


def _prepare(
    request: HttpRequest,
    source: references.ProgrammePersonReferenceRequest,
    form: ProgrammePersonReferenceForm,
) -> tuple[
    ProgrammePersonReferenceForm, references.ProgrammePersonSelection | None, str, int
]:
    if form.cleaned_data["token"]:
        raise ValueError
    mode, email = form.cleaned_data["mode"], form.cleaned_data["email"]
    if (mode == "select" and not email) or (mode == "clear" and email):
        form.add_error(
            "email", "Enter the known email to select, or leave it empty to clear."
        )
        return form, None, "prepare", 400
    selected = references.prepare_programme_person_selection(
        request=source,
        intent=_intent(form.cleaned_data),
        email=email if mode == "select" else None,
    )
    if selected is None:
        form.add_error(
            "email", "No available person was selected. Check the known address."
        )
        return form, None, "prepare", 400
    data = request.POST.copy()
    data["email"] = ""
    data["token"] = selected.token
    # HiddenInput posts the string "False", which an unbound checkbox treats as true.
    # A newly prepared intent must always require a fresh deliberate confirmation.
    data["confirm"] = ""
    return (
        ProgrammePersonReferenceForm(initial=data, auto_id="person_%s"),
        selected,
        "confirm",
        200,
    )


def _edit(
    request: HttpRequest,
    scope: _Scope,
    source_request: references.ProgrammePersonReferenceRequest,
    phase: str,
) -> HttpResponse:
    source = _source(source_request, _DEFAULT)
    context, detail = source
    # A retained confirmation may outlive applicability; the writer owns replay.
    answer = (
        next(
            (
                row
                for row in detail.answers or ()
                if row.question.question_id == source_request.question_id
            ),
            None,
        )
        if phase == "confirm"
        else _answer(detail.answers, source_request.question_id)
    )
    initial = {
        "expected_version": context.summary.aggregate_version,
        "expected_call_version": context.call_version,
        "expected_definition_version": context.definition_version,
        "retry_key": uuid4(),
        "mode": "select",
    }
    form_type = (
        ProgrammePersonLookupForm
        if phase == "prepare"
        else ProgrammePersonReferenceForm
    )
    form = form_type(
        request.POST if request.method == "POST" else None,
        initial=initial,
        auto_id="person_%s",
    )
    selected = None
    status = 200
    try:
        if request.method == "GET":
            _fresh(context, _intent(initial))
        elif not form.is_valid():
            status = 400
            if phase == "confirm" and {
                "token",
                *references.ProgrammePersonReferenceIntent.__dataclass_fields__,
            }.issubset(form.cleaned_data):
                selected = references.read_programme_person_selection(
                    request=source_request,
                    intent=_intent(form.cleaned_data),
                    token=form.cleaned_data["token"],
                )
        elif phase == "prepare":
            form, selected, phase, status = _prepare(request, source_request, form)
        else:
            selected = references.read_programme_person_selection(
                request=source_request,
                intent=_intent(form.cleaned_data),
                token=form.cleaned_data["token"],
            )
            if form.cleaned_data["email"] or (form.cleaned_data["mode"] == "clear") != (
                selected.account_id is None
            ):
                raise ValueError
            commands.append_programme_proposal_answer(
                actor_id=scope.actor_id,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                proposal_id=source_request.proposal_id,
                question_id=source_request.question_id,
                value=str(selected.account_id)
                if selected.account_id is not None
                else None,
                **asdict(selected.intent),
                reason=form.cleaned_data["reason"],
                correlation_id=scope.correlation_id,
                source_channel=_SOURCE,
            )
            return _secure(
                HttpResponseRedirect(
                    f"{_root(scope)}{source_request.proposal_id}/work/"
                )
            )
    except _CONFLICTS:
        if not form.is_bound:
            form.cleaned_data = {}
        form.add_error(
            None,
            "The original source is no longer current. Your intent is retained. "
            "Check proposal history: an earlier attempt may have committed. "
            "Do not replace the retry key to guess a new request.",
        )
        status = 409
    except ValidationError as error:
        _apply_errors(form, error)
        status = 400

    def verify() -> None:
        if _source(source_request, _DEFAULT) != source:
            raise Denied
        if (
            selected is not None
            and references.read_programme_person_selection(
                request=source_request, intent=selected.intent, token=selected.token
            )
            != selected
        ):
            raise Denied

    if phase == "confirm":
        form.fields["mode"].widget = forms.HiddenInput()
        form.fields["email"].widget = forms.HiddenInput()
    return _html(
        request,
        scope,
        {
            "task": "person-reference",
            "form": form,
            "phase": phase,
            "selection": selected,
            "question_label": answer.question.label
            if answer
            else "Original selected question",
            "question": answer.question if answer else None,
            "proposal_url": f"{_root(scope)}{source_request.proposal_id}/work/",
        },
        verify,
        status=status,
    )


def _viewer(
    request: HttpRequest,
    scope: _Scope,
    source: references.ProgrammePersonReferenceRequest,
    revision_id: UUID | None,
) -> HttpResponse:
    view = references.get_self_programme_person_reference(
        request=source, revision_id=revision_id
    )

    def verify() -> None:
        if (
            references.get_self_programme_person_reference(
                request=source, revision_id=revision_id
            )
            != view
        ):
            raise Denied

    return _html(
        request,
        scope,
        {
            "task": "person-reference",
            "person_view": view,
            "question_label": view.question_label,
            "proposal_url": f"{_root(scope)}{source.proposal_id}/work/",
        },
        verify,
    )


def _route(*, edit: bool, revision_id: UUID | None) -> None:
    if edit and revision_id is not None:
        raise ValueError


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_person_reference(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    *,
    edit: bool = False,
    revision_id: UUID | None = None,
) -> HttpResponse:
    """Serve a dedicated exact-person task without mounting production routes.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected closed transport.
    organization_id : UUID
        Exact expected organization, never authority.
    edition_id : UUID
        Exact expected event edition.
    proposal_id : UUID
        Current genuine contributor's proposal.
    question_id : UUID
        Exact question, never a caller-specified account to look up.
    edit : bool, default=False
        Code-owned selection task flag, absent for read-only viewers.
    revision_id : UUID | None, default=None
        Exact current seal for frozen viewing only.

    Returns
    -------
    HttpResponse
        Protected selection/viewer, canonical success redirect, or safe error.
    """
    try:
        phase = _transport(request, edit=edit)
        _route(edit=edit, revision_id=revision_id)
        scope = _Scope(UUID(str(request.user.pk)), organization_id, edition_id, uuid4())
        source = references.ProgrammePersonReferenceRequest(
            scope.actor_id,
            organization_id,
            edition_id,
            proposal_id,
            question_id,
            scope.correlation_id,
            _SOURCE,
        )
        if edit:
            return _edit(request, scope, source, phase)
        return _viewer(request, scope, source, revision_id)
    except Denied:
        return _secure(
            HttpResponse(
                "This person-reference task is unavailable. Check authorized "
                "proposal history after an uncertain attempt.",
                status=404,
            )
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "The person-reference service is unavailable. An earlier attempt "
                "may have committed; check proposal history.",
                status=503,
            )
        )
    except (ValueError, TypeError, ValidationError):
        return _secure(
            HttpResponse(
                "Use the complete bounded person-reference request.", status=400
            )
        )
