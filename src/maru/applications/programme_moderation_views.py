"""Dormant independent moderation, protected evidence and exact-intent receipts."""

from __future__ import annotations

import json
from dataclasses import replace
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_moderation_queries as queries
from .models import ProgrammeReviewAction
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_decision_views import _CONFLICTS, _UNAVAILABLE
from .programme_moderation_forms import ModerationActionForm
from .programme_review_authorization import MODERATE, authorize_programme_review_scope
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import ProgrammeReviewCommandInput
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    get_programme_review_detail,
)
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_reviewer_views import _answer_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from .programme_review_inputs import ProgrammeReviewStageInput

_SOURCE = "programme-moderation"
_ACTIONS = {
    "moderate": ProgrammeReviewAction.MODERATED,
    "advance": ProgrammeReviewAction.STAGE_ADVANCED,
    "reopen": ProgrammeReviewAction.STAGE_REOPENED,
}
_SECTIONS = {
    "context": "review_context",
    "answers": "review_answers",
    "evidence": "review_evidence",
}
_MAX_INPUT_BYTES = 12_000
_MAX_VERSION_DIGITS = 19


def _root(scope: ProgrammeReviewReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/moderation/"
    )


def _authorize(scope: ProgrammeReviewReadRequest) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        capability_code=MODERATE,
        requested_fields=scope.requested_fields,
    )


def _integer(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > _MAX_VERSION_DIGITS:
        raise ValueError
    result = int(value)
    if str(result) != value or not 1 <= result <= 2**63 - 1:
        raise ValueError
    return result


def _transport(request: HttpRequest, task: str, *, queue: bool) -> dict[str, Any]:
    if request.FILES or task not in {"overview", *_ACTIONS, *_SECTIONS}:
        raise ValueError
    if queue and (task != "overview" or request.method != "GET"):
        raise ValueError
    if request.method == "POST" and (
        task not in _ACTIONS or request.GET or request.POST.get("action") != task
    ):
        raise ValueError
    if any(
        len(values) != 1 or len(values[0].encode("utf-8")) > _MAX_INPUT_BYTES
        for data in (request.GET, request.POST)
        for _key, values in data.lists()
    ):
        raise ValueError
    allowed = (
        {"after"}
        if queue
        else ({"after", "version"} if task in {"evidence", "moderate"} else set())
    )
    if set(request.GET) - allowed:
        raise ValueError
    if queue:
        value = request.GET.get("after")
        if value is None:
            return {}
        identifier = UUID(value)
        if value != str(identifier) or not identifier.int:
            raise ValueError
        return {"after_id": identifier}
    result = {key: _integer(request.GET.getlist(key)[0]) for key in request.GET}
    if "after" in result and (
        "version" not in result or result["after"] > result["version"]
    ):
        raise ValueError
    return result


def _available(source: queries.ModerationCase) -> set[str]:
    if not source.writable or not source.case.current_revision:
        return set()
    if source.case.state == "waitlisted":
        return {"reopen"}
    if source.case.state != "open":
        return set()
    actions = {"moderate", "reopen"}
    if source.case.stage + 1 < len(source.stages):
        actions.add("advance")
    return actions


def _links(scope: ProgrammeReviewReadRequest) -> tuple[str, ...]:
    result = []
    for section, field in _SECTIONS.items():
        try:
            _authorize(replace(scope, requested_fields=frozenset({field})))
        except Denied:
            continue
        result.append(section)
    return tuple(result)


def _html(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
) -> HttpResponse:
    verify()
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        title="Programme moderation",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string("applications/programme_moderation.html", shell, request)
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _submit(
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    task: str,
    form: ModerationActionForm,
) -> tuple[Any, int]:
    if not form.is_valid():
        return None, 400
    try:
        return apply_programme_review_command(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            command=ProgrammeReviewCommandInput(
                _ACTIONS[task],
                case_id,
                stage=form.cleaned_data.get("stage"),
            ),
            expected_version=form.cleaned_data["expected_version"],
            retry_key=form.cleaned_data["retry_key"],
            reason=form.cleaned_data["reason"],
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        ), 200
    except ValidationError as error:
        _apply_errors(form, error)
        return None, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "This request was not confirmed. Inspect current state before starting "
            "a new intent. Original version, retry proof, selected stage and "
            "entered rationale remain unchanged.",
        )
        return None, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            "The review service is temporarily unavailable. Retain this exact "
            "request; do not replace its original version or retry proof.",
        )
        return None, 503


def _stage_label(stages: tuple[ProgrammeReviewStageInput, ...], index: Any) -> str:
    if type(index) is not int or not 0 <= index < len(stages):
        raise ProgrammeReviewUnavailableError
    return f"{index + 1}. {stages[index].code}"


def _projection(
    detail: Any, stages: tuple[ProgrammeReviewStageInput, ...]
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if detail.context_json is not None:
        context["review_context"] = json.loads(detail.context_json)
    if detail.answers_json is not None:
        context["answers"] = tuple(
            {
                "label": row["label"],
                "classification": row["classification"],
                "text": _answer_text(row),
                "person_key": row["key"]
                if (row.get("type"), row.get("reference_kind"))
                == ("person_reference", "programme.person")
                else None,
            }
            for row in json.loads(detail.answers_json)
        )
    if detail.evidence_json is not None:
        rows = []
        for row in json.loads(detail.evidence_json):
            payload = row.get("payload", {})
            facts = []
            for key, label in (
                ("evidence_version", "Inspected evidence version"),
                ("state", "Assignment state"),
                ("outcome", "Decision outcome"),
            ):
                if key in payload:
                    facts.append((label, payload[key]))
            for key, label in (
                ("from_stage", "Previous stage"),
                ("to_stage", "Destination stage"),
            ):
                if key in payload:
                    facts.append((label, _stage_label(stages, payload[key])))
            rows.append(
                {
                    "version": row["version"],
                    "stage": _stage_label(stages, row["stage"]),
                    "action": row["action"].replace("_", " "),
                    "reason": row.get("reason", ""),
                    "text": payload.get("text", ""),
                    "scores": tuple(payload.get("scores", {}).items()),
                    "facts": tuple(facts),
                    "actor": row.get("actor_id"),
                    "assignment": row.get("assignment_id"),
                    "reviewer": payload.get("reviewer_id"),
                }
            )
        context.update(evidence=tuple(rows), next_evidence=detail.next_evidence_version)
    return context


def _detail(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    task: str,
    cursors: dict[str, Any],
) -> HttpResponse:
    context: dict[str, Any] = {"task": task}
    status = 200
    form = None
    # No private source/evidence preflight may prevent an original receipt.
    if request.method == "POST":
        form = ModerationActionForm(request.POST, task=task)
        result, status = _submit(scope, case_id, task, form)
        if result is not None:
            return _html(request, scope, {"result": result}, lambda: _authorize(scope))

    def load() -> queries.ModerationCase:
        return queries.get_programme_moderation_case(request=scope, case_id=case_id)

    source = load()
    links = _links(scope)
    actions = _available(source)
    if "evidence" not in links:
        actions.discard("moderate")
    context.update(source=source, actions=actions, content_links=links)
    detail = None
    facts = None
    section = "evidence" if task == "moderate" else task

    def read() -> Any:
        protected = replace(scope, requested_fields=frozenset({_SECTIONS[section]}))
        if section == "evidence":
            return queries.get_programme_moderation_evidence(
                request=protected,
                case_id=case_id,
                after_version=cursors.get("after", 0),
            )
        return get_programme_review_detail(request=protected, case_id=case_id)

    if request.method == "GET" and section in _SECTIONS:
        projected = read()
        facts = projected if section == "evidence" else None
        detail = facts.detail if facts else projected
        if detail.version != source.case.version:
            raise Denied
        if cursors.get("version", detail.version) != detail.version:
            context["snapshot_stale"] = True
            status = 409
            detail = facts = None
        else:
            context.update(
                _projection(detail, source.stages), facts=facts, snapshot=detail.version
            )
    if (
        request.method == "GET"
        and task in actions
        and not context.get("snapshot_stale")
    ):
        form = ModerationActionForm(
            task=task,
            initial={"retry_key": uuid4(), "expected_version": source.case.version},
        )
    if form is not None and task == "reopen":
        # Bound invalid/conflict forms keep any original configured stage label.
        end = len(source.stages) if form.is_bound else source.case.stage + 1
        form.fields["stage"].widget.choices = [
            ("", "Choose a stage deliberately"),
            *[(i, _stage_label(source.stages, i)) for i in range(end)],
        ]
    context["form"] = form

    def verify() -> None:
        if load() != source or _links(scope) != links:
            raise Denied
        if detail is not None and read() != (facts or detail):
            raise Denied

    return _html(request, scope, context, verify, status)


def _queue(
    request: HttpRequest, scope: ProgrammeReviewReadRequest, cursors: dict[str, Any]
) -> HttpResponse:
    page = queries.list_programme_moderation_cases(request=scope, **cursors)

    def verify() -> None:
        if queries.list_programme_moderation_cases(request=scope, **cursors) != page:
            raise Denied

    return _html(request, scope, {"page": page}, verify)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_moderation(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID | None = None,
    task: str = "overview",
) -> HttpResponse:
    """Serve independently authorized moderation without final-decision authority.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with closed inputs and real CSRF protection.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact owning edition.
    department_id : UUID
        Independently authorized current owner Department.
    case_id : UUID | None, default=None
        Exact case, absent only for independent discovery.
    task : str, default="overview"
        Closed task or separately protected content section selected by the route.

    Returns
    -------
    HttpResponse
        Scoped task, original-intent form, minimal receipt or safe failure.
    """
    if not isinstance(request.user.pk, UUID):
        return _secure(
            HttpResponse("This moderation workspace is unavailable.", status=404)
        )
    scope = ProgrammeReviewReadRequest(
        request.user.pk,
        organization_id,
        edition_id,
        department_id,
        MODERATE,
        frozenset({"review_context"}),
        uuid4(),
        _SOURCE,
    )
    try:
        _authorize(scope)
        cursors = _transport(request, task, queue=case_id is None)
        if case_id is None:
            return _queue(request, scope, cursors)
        return _detail(request, scope, case_id, task, cursors)
    except Denied:
        return _secure(
            HttpResponse("This moderation workspace is unavailable.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use the complete bounded moderation request.", status=400)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("The review service is temporarily unavailable.", status=503)
        )
