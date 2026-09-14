"""Dormant Department review policy composition using the canonical owner writer."""

from __future__ import annotations

import json
from dataclasses import asdict
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_review_setup_queries as queries
from .models import ApplicationDefinitionStatus, ProgrammeReviewAction
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_decision_views import _CONFLICTS, _UNAVAILABLE
from .programme_review_authorization import (
    MANAGE_REVIEW,
    authorize_programme_review_scope,
)
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import MAX_REVIEW_STAGES, ProgrammeReviewCommandInput
from .programme_review_management_views import can_manage_programme_review_cases
from .programme_review_queries import ProgrammeReviewReadRequest
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_review_setup_forms import (
    MAX_REVIEW_STATE,
    OUTCOME_LABELS,
    ReviewPolicySaveForm,
    ReviewProposedForm,
    ReviewStageForm,
    ReviewTemplatesForm,
    decode_proposed_review,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-review-setup"
_EMPTY = '{"stages":[],"templates":[]}'
_MAX_QUESTIONS = 500
_UUID_LENGTH = 36


def _root(scope: ProgrammeReviewReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/"
    )


def _authorize(scope: ProgrammeReviewReadRequest) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        capability_code=MANAGE_REVIEW,
        requested_fields=scope.requested_fields,
    )


def _transport(
    request: HttpRequest, call_id: UUID | None, version: int | None
) -> UUID | None:
    if request.FILES or set(request.GET) - {"after"}:
        raise ValueError
    if call_id is not None and request.GET:
        raise ValueError
    if request.method == "POST":
        if call_id is None or version is not None or request.GET:
            raise ValueError
        if (
            any(
                (len(values) != 1 and name != "question_keys")
                or any(
                    len(value.encode("utf-8"))
                    > (MAX_REVIEW_STATE if name == "proposed" else 12_000)
                    for value in values
                )
                for name, values in request.POST.lists()
            )
            or len(request.POST.getlist("question_keys")) > _MAX_QUESTIONS
        ):
            raise ValueError
    if "after" not in request.GET:
        return None
    if len(request.GET.getlist("after")) != 1:
        raise ValueError
    text = request.GET["after"]
    if len(text) != _UUID_LENGTH:
        raise ValueError
    identifier = UUID(text)
    if str(identifier) != text or not identifier.int:
        raise ValueError
    return identifier


def _html(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
) -> HttpResponse:
    verify()
    can_manage = can_manage_programme_review_cases(scope)
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        title="Programme review setup",
        root_url=_root(scope),
        can_manage=can_manage,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string(
        "applications/programme_review_setup.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    if can_manage_programme_review_cases(scope) != can_manage:
        raise Denied
    return _secure(HttpResponse(content, status=status), nonce)


def _initial(form: ReviewProposedForm, proposed: dict[str, Any]) -> dict[str, Any]:
    return {
        "retry_key": form.cleaned_data["retry_key"],
        "expected_version": form.cleaned_data["expected_version"],
        "proposed": json.dumps(proposed, ensure_ascii=False, separators=(",", ":")),
    }


def _stage_initial(stage: dict[str, Any]) -> dict[str, Any]:
    values = {key: stage[key] for key in ("code", "required_reviews", "question_keys")}
    values.update(
        {key: "yes" if stage[key] else "no" for key in ("anonymous", "discussion")}
    )
    for index, criterion in enumerate(stage["criteria"]):
        values.update(
            {f"criterion_{index}_{key}": value for key, value in criterion.items()}
        )
    return values


def _transition(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    source: queries.ReviewSetupContext,
) -> tuple[ReviewProposedForm, str, int] | HttpResponse:
    action = request.POST.get("action", "")
    form_type = {
        "keep-stage": ReviewStageForm,
        "keep-templates": ReviewTemplatesForm,
        "save": ReviewPolicySaveForm,
        "back": ReviewPolicySaveForm,
        "refresh": ReviewPolicySaveForm,
    }.get(action, ReviewProposedForm)
    kwargs = {"questions": source.questions} if form_type is ReviewStageForm else {}
    form = form_type(request.POST, **kwargs)
    if action in {"back", "refresh"}:
        form.fields["reason"].required = False
        form.fields["confirm"].required = False
    mode = {
        "keep-stage": "stage",
        "keep-templates": "templates",
        "save": "confirm",
    }.get(action, "overview")
    if not form.is_valid():
        return form, mode, 400
    proposed = form.cleaned_data["proposed"]
    initial = _initial(form, proposed)
    if action == "save" and isinstance(form, ReviewPolicySaveForm):
        return _save(form, scope, source)
    if not source.writable:
        raise Denied
    if action in {"keep-stage", "keep-templates"}:
        try:
            proposed = _keep(action, form, proposed)
        except ValidationError as error:
            _apply_errors(form, error)
            return form, mode, 400
        return ReviewProposedForm(initial=_initial(form, proposed)), "overview", 200
    return _navigate(action, form, initial, proposed, source)


def _save(
    form: ReviewPolicySaveForm,
    scope: ProgrammeReviewReadRequest,
    source: queries.ReviewSetupContext,
) -> tuple[ReviewProposedForm, str, int] | HttpResponse:
    try:
        result = apply_programme_review_command(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            command=ProgrammeReviewCommandInput(
                ProgrammeReviewAction.POLICY_CREATED,
                source.call.call_id,
                policy=form.policy(),
            ),
            expected_version=form.cleaned_data["expected_version"],
            retry_key=form.cleaned_data["retry_key"],
            reason=form.cleaned_data["reason"],
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except ValidationError as error:
        _apply_errors(form, error)
        return form, "confirm", 400
    except _CONFLICTS:
        form.add_error(
            None,
            "This policy was not confirmed as saved. Your proposed policy and "
            "original retry proof remain here. Inspect current policy history "
            "before explicitly refreshing the intent.",
        )
        return form, "confirm", 409
    return _secure(
        HttpResponseRedirect(
            f"{_root(scope)}{source.call.call_id}/policies/{result.version}/"
        )
    )


def _keep(
    action: str,
    form: ReviewProposedForm,
    proposed: dict[str, Any],
) -> dict[str, Any]:
    if action == "keep-stage":
        index = form.cleaned_data["stage_index"]
        if index > len(proposed["stages"]):
            raise ValueError
        stages = proposed["stages"][:]
        if index == len(stages):
            stages.append(asdict(form.cleaned_data["stage"]))
        else:
            stages[index] = asdict(form.cleaned_data["stage"])
        proposed["stages"] = stages
    else:
        proposed["templates"] = [
            {
                "outcome": outcome,
                "text": form.cleaned_data[f"{outcome}_text"],
                "acknowledgement_required": form.cleaned_data[f"{outcome}_receipt"]
                == "yes",
            }
            for outcome in OUTCOME_LABELS
        ]
    return decode_proposed_review(json.dumps(proposed))


def _navigate(
    action: str,
    form: ReviewProposedForm,
    initial: dict[str, Any],
    proposed: dict[str, Any],
    source: queries.ReviewSetupContext,
) -> tuple[ReviewProposedForm, str, int]:
    if action == "add-stage" or action.startswith("edit:"):
        index = (
            len(proposed["stages"])
            if action == "add-stage"
            else _index(action, proposed)
        )
        if index >= MAX_REVIEW_STAGES:
            raise ValueError
        initial["stage_index"] = index
        if index < len(proposed["stages"]):
            initial.update(_stage_initial(proposed["stages"][index]))
        return (
            ReviewStageForm(initial=initial, questions=source.questions),
            "stage",
            200,
        )
    if action == "templates":
        for row in proposed["templates"]:
            initial[f"{row['outcome']}_text"] = row["text"]
            initial[f"{row['outcome']}_receipt"] = (
                "yes" if row["acknowledgement_required"] else "no"
            )
        return ReviewTemplatesForm(initial=initial), "templates", 200
    if action.startswith(("remove:", "up:", "down:")):
        index = _index(action, proposed)
        if action.startswith("remove:"):
            proposed["stages"].pop(index)
        else:
            destination = index + (-1 if action.startswith("up:") else 1)
            if not 0 <= destination < len(proposed["stages"]):
                raise ValueError
            proposed["stages"][index], proposed["stages"][destination] = (
                proposed["stages"][destination],
                proposed["stages"][index],
            )
    elif action == "confirm":
        return ReviewPolicySaveForm(initial=initial), "confirm", 200
    elif action == "refresh":
        initial.update(retry_key=uuid4(), expected_version=source.policy_version)
        return ReviewProposedForm(initial=initial), "overview", 200
    elif action != "back":
        raise ValueError
    return ReviewProposedForm(initial=_initial(form, proposed)), "overview", 200


def _index(action: str, proposed: dict[str, Any]) -> int:
    value = action.partition(":")[2]
    if (
        len(value) != 1
        or value not in "01234567"
        or int(value) >= len(proposed["stages"])
    ):
        raise ValueError
    return int(value)


def _workspace(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    call_id: UUID,
    version: int | None,
) -> HttpResponse:
    source = queries.get_programme_review_setup(request=scope, call_id=call_id)
    policy = (
        None
        if version is None
        else queries.get_programme_review_setup_policy(
            request=scope, call_id=call_id, version=version
        )
    )
    context: dict[str, Any] = {"source": source, "policy": policy}
    if policy is not None:
        context["summary"] = _summary(asdict(policy.policy), source)
    status = 200
    if policy is None and source.call.status in {
        ApplicationDefinitionStatus.ACTIVE,
        ApplicationDefinitionStatus.RETIRED,
    }:
        form: ReviewProposedForm = ReviewProposedForm(
            initial={
                "retry_key": uuid4(),
                "expected_version": source.policy_version,
                "proposed": _EMPTY,
            }
        )
        mode = "overview"
        if request.method == "POST":
            transition = _transition(request, scope, source)
            if isinstance(transition, HttpResponse):
                return transition
            form, mode, status = transition
            # Conflict rendering must show the newly read sequence, not stale context.
            source = queries.get_programme_review_setup(request=scope, call_id=call_id)
            context["source"] = source
        raw = (
            form.data.get("proposed", _EMPTY)
            if form.is_bound
            else form.initial["proposed"]
        )
        try:
            proposed = decode_proposed_review(raw)
        except ValidationError:
            proposed = None
        context.update(
            form=form if source.writable or form.is_bound else None,
            mode=mode,
            proposed=proposed,
        )
        if proposed is not None:
            context["summary"] = _summary(proposed, source)
        if isinstance(form, ReviewStageForm):
            rows = tuple(
                tuple(
                    form[f"criterion_{index}_{key}"]
                    for key in ("code", "label", "minimum", "maximum")
                )
                for index in range(16)
            )
            context["criterion_rows"] = tuple(
                (fields, any(field.value() not in (None, "") for field in fields))
                for fields in rows
            )
    elif request.method == "POST":
        raise Denied

    def verify() -> None:
        if queries.get_programme_review_setup(request=scope, call_id=call_id) != source:
            raise Denied
        if (
            version is not None
            and queries.get_programme_review_setup_policy(
                request=scope, call_id=call_id, version=version
            )
            != policy
        ):
            raise Denied

    return _html(request, scope, context, verify, status)


def _summary(
    proposed: dict[str, Any],
    source: queries.ReviewSetupContext,
) -> dict[str, Any]:
    labels = {question.key: question.label for question in source.questions}
    return {
        "stages": tuple(
            stage
            | {
                "question_labels": tuple(
                    f"{labels.get(key, 'Question unavailable')} · {key}"
                    for key in stage["question_keys"]
                )
            }
            for stage in proposed["stages"]
        ),
        "templates": tuple(
            item | {"outcome_label": OUTCOME_LABELS[item["outcome"]]}
            for item in proposed["templates"]
        ),
    }


def _history(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    cursor: UUID | None,
) -> HttpResponse:
    page = queries.list_programme_review_setup_calls(request=scope, after_id=cursor)

    def verify() -> None:
        if (
            queries.list_programme_review_setup_calls(request=scope, after_id=cursor)
            != page
        ):
            raise Denied

    return _html(request, scope, {"page": page}, verify)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_review_setup(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None = None,
    version: int | None = None,
) -> HttpResponse:
    """Compose explicit review policy without exposing or mutating proposal content.

    Parameters
    ----------
    request : HttpRequest
        Authenticated exact manager request with ordinary CSRF protection.
    organization_id : UUID
        Exact owning organization from the reserved route.
    edition_id : UUID
        Exact edition from the reserved route.
    department_id : UUID
        Current owner Department, independently authorized.
    call_id : UUID | None, default=None
        Selected call, absent for bounded configuration discovery.
    version : int | None, default=None
        Exact immutable policy version, absent for the unsaved composer.

    Returns
    -------
    HttpResponse
        Protected setup, original-input recovery or a non-disclosing error.
    """
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        return _secure(
            HttpResponse("This review workspace is unavailable.", status=404)
        )
    scope = ProgrammeReviewReadRequest(
        actor_id,
        organization_id,
        edition_id,
        department_id,
        MANAGE_REVIEW,
        frozenset({"review_setup"}),
        uuid4(),
        _SOURCE,
    )
    try:
        _authorize(scope)
        cursor = _transport(request, call_id, version)
        if call_id is not None:
            return _workspace(request, scope, call_id, version)
        return _history(request, scope, cursor)
    except Denied:
        return _secure(
            HttpResponse("This review workspace is unavailable.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use the complete bounded review request.", status=400)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "The review setup service is temporarily unavailable.", status=503
            )
        )
