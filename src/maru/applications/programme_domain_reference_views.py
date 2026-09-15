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
from . import programme_domain_references as references
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_domain_reference_forms import (
    ProgrammeDomainLookupForm,
    ProgrammeDomainReferenceForm,
)
from .programme_domain_references import _DEFAULT, _answer, _target_values
from .programme_domain_targets import _domain_options
from .programme_proposal_views import _CONFLICTS, _UNAVAILABLE, _html, _root, _Scope
from .programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
    _fresh,
    _source,
)

_SOURCE = "programme-domain-reference"
_MAX_INPUT_BYTES = 6000


def _transport(request: HttpRequest, *, edit: bool) -> str:
    if request.GET or request.FILES or (request.method == "POST" and not edit):
        raise ValueError
    if request.method != "POST":
        return "prepare"
    phase = request.POST.get("phase", "")
    allowed = {
        *ProgrammeDomainReferenceForm.base_fields,
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


def _intent(values: dict[str, Any]) -> ProgrammeAnswerReferenceIntent:
    return ProgrammeAnswerReferenceIntent(
        **{
            key: values[key]
            for key in ProgrammeAnswerReferenceIntent.__dataclass_fields__
        }
    )


def _prepare(
    request: HttpRequest,
    source: ProgrammeAnswerReferenceRequest,
    form: ProgrammeDomainReferenceForm,
) -> tuple[
    ProgrammeDomainReferenceForm, references.ProgrammeDomainSelection | None, str, int
]:
    if form.cleaned_data["token"]:
        raise ValueError
    mode, target = form.cleaned_data["mode"], form.cleaned_data["target"]
    if (mode == "select" and target is None) or (
        mode == "clear" and target is not None
    ):
        form.add_error(
            "target", "Choose an entry to select, or leave it empty to clear."
        )
        return form, None, "prepare", 400
    selected = references.prepare_programme_domain_selection(
        request=source,
        intent=_intent(form.cleaned_data),
        target_id=target if mode == "select" else None,
    )
    data = request.POST.copy()
    data["target"] = ""
    data["token"] = selected.token
    # HiddenInput posts the string "False", which an unbound checkbox treats as true.
    # A newly prepared intent must always require a fresh deliberate confirmation.
    data["confirm"] = ""
    return (
        ProgrammeDomainReferenceForm(initial=data, auto_id="domain_%s"),
        selected,
        "confirm",
        200,
    )


def _choices(
    request: HttpRequest,
    source: ProgrammeAnswerReferenceRequest,
    form: ProgrammeDomainReferenceForm,
    initial: dict[str, Any],
) -> references.ProgrammeDomainChoices | None:
    values = initial
    if request.method == "POST":
        form.is_valid()
        values = form.cleaned_data
        if not set(ProgrammeAnswerReferenceIntent.__dataclass_fields__).issubset(
            values
        ):
            return None
    choices = references.get_programme_domain_choices(
        request=source, intent=_intent(values)
    )
    form.fields["target"].widget = forms.Select(
        choices=(
            ("", "Choose an entry"),
            *(
                (str(row.target_id), f"{row.label} ({row.code})")
                for row in choices.options
            ),
        )
    )
    return choices


def _retain_choice(form: ProgrammeDomainReferenceForm) -> None:
    retained = form.cleaned_data.get("target")
    if isinstance(retained, UUID):
        form.fields["target"].widget = forms.Select(
            choices=(
                ("", "Choose an entry"),
                (
                    str(retained),
                    "Original choice retained; current choices are unavailable",
                ),
            )
        )


def _edit(
    request: HttpRequest,
    scope: _Scope,
    source_request: ProgrammeAnswerReferenceRequest,
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
        ProgrammeDomainLookupForm
        if phase == "prepare"
        else ProgrammeDomainReferenceForm
    )
    form = form_type(
        request.POST if request.method == "POST" else None,
        initial=initial,
        auto_id="domain_%s",
    )
    selected = None
    choices = None
    status = 200
    try:
        if phase == "prepare":
            choices = _choices(request, source_request, form, initial)
        if request.method == "GET":
            _fresh(context, _intent(initial))
        elif not form.is_valid():
            status = 400
            if phase == "confirm" and {
                "token",
                *ProgrammeAnswerReferenceIntent.__dataclass_fields__,
            }.issubset(form.cleaned_data):
                selected = references.read_programme_domain_selection(
                    request=source_request,
                    intent=_intent(form.cleaned_data),
                    token=form.cleaned_data["token"],
                )
        elif phase == "prepare":
            form, selected, phase, status = _prepare(request, source_request, form)
        else:
            selected = references.read_programme_domain_selection(
                request=source_request,
                intent=_intent(form.cleaned_data),
                token=form.cleaned_data["token"],
            )
            if form.cleaned_data["target"] or (
                form.cleaned_data["mode"] == "clear"
            ) != (selected.target_id is None):
                raise ValueError
            commands.append_programme_proposal_answer(
                actor_id=scope.actor_id,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                proposal_id=source_request.proposal_id,
                question_id=source_request.question_id,
                value=str(selected.target_id)
                if selected.target_id is not None
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

    if phase == "prepare" and choices is None and form.is_bound:
        _retain_choice(form)

    def verify() -> None:
        if _source(source_request, _DEFAULT) != source:
            raise Denied
        if (
            choices is not None
            and _domain_options(
                **_target_values(
                    source_request,
                    context.summary.call_id,
                    choices.question.reference_kind,
                )
            )
            != choices.options
        ):
            raise Denied
        if (
            selected is not None
            and references.read_programme_domain_selection(
                request=source_request, intent=selected.intent, token=selected.token
            )
            != selected
        ):
            raise Denied

    if phase == "confirm":
        form.fields["mode"].widget = forms.HiddenInput()
        form.fields["target"].widget = forms.HiddenInput()
    return _html(
        request,
        scope,
        {
            "task": "domain-reference",
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
    source: ProgrammeAnswerReferenceRequest,
    revision_id: UUID | None,
) -> HttpResponse:
    view = references.get_self_programme_domain_reference(
        request=source, revision_id=revision_id
    )

    def verify() -> None:
        if (
            references.get_self_programme_domain_reference(
                request=source, revision_id=revision_id
            )
            != view
        ):
            raise Denied

    return _html(
        request,
        scope,
        {
            "task": "domain-reference",
            "domain_view": view,
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
def programme_domain_reference(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    *,
    edit: bool = False,
    revision_id: UUID | None = None,
) -> HttpResponse:
    """Serve a dedicated exact-domain task without mounting production routes.

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
        Exact question, never a caller-specified target to look up.
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
        source = ProgrammeAnswerReferenceRequest(
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
                "This domain-reference task is unavailable. Check authorized "
                "proposal history after an uncertain attempt.",
                status=404,
            )
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "The domain-reference service is unavailable. An earlier attempt "
                "may have committed; check proposal history.",
                status=503,
            )
        )
    except (ValueError, TypeError, ValidationError):
        return _secure(
            HttpResponse(
                "Use the complete bounded domain-reference request.", status=400
            )
        )
