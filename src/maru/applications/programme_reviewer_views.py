"""Dormant own reviewer tasks using canonical commands and protected projections."""

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

from . import programme_reviewer_queries as queries
from .models import ProgrammeReviewAction
from .programme_answer_display import programme_review_answer_text
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_decision_views import _CONFLICTS, _UNAVAILABLE
from .programme_domain_targets import DOMAIN_REFERENCE_KINDS
from .programme_review_authorization import REVIEW, authorize_programme_review_scope
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import ProgrammeReviewCommandInput
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    get_programme_review_detail,
)
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_reviewer_forms import ReviewerActionForm

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-reviewer-work"
_ACTIONS = {
    "clear": ProgrammeReviewAction.CONFLICT_CLEARED,
    "recuse": ProgrammeReviewAction.REVIEWER_RECUSED,
    "score": ProgrammeReviewAction.SCORED,
    "discuss": ProgrammeReviewAction.DISCUSSED,
}
_SECTIONS = {
    "context": "review_context",
    "answers": "review_answers",
    "evidence": "review_evidence",
}
_MAX_INPUT_BYTES = 12_000
_UUID_LENGTH = 36
_MAX_VERSION_DIGITS = 19


def _root(scope: ProgrammeReviewReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/mine/"
    )


def _authorize(scope: ProgrammeReviewReadRequest) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        capability_code=REVIEW,
        requested_fields=scope.requested_fields,
    )


def _available(source: queries.ReviewerWork) -> set[str]:
    if not source.writable or not source.case.current_revision:
        return set()
    actions = {"recuse"} if source.state in {"pending", "active"} else set()
    if source.case.state != "open" or source.stage != source.case.stage:
        return actions
    if source.state == "pending":
        actions.add("clear")
    elif source.state == "active":
        actions.add("score")
        if source.rubric.discussion and source.has_scored:
            actions.add("discuss")
    return actions


def _content_links(
    scope: ProgrammeReviewReadRequest, source: queries.ReviewerWork
) -> tuple[str, ...]:
    if (
        source.state != "active"
        or source.stage != source.case.stage
        or not source.case.current_revision
    ):
        return ()
    result = []
    for section, field in _SECTIONS.items():
        try:
            _authorize(replace(scope, requested_fields=frozenset({field})))
        except Denied:
            continue
        result.append(section)
    return tuple(result)


def _transport(request: HttpRequest, task: str, *, queue: bool) -> UUID | int | None:
    if (
        request.FILES
        or task not in {"overview", *_ACTIONS, *_SECTIONS}
        or (queue and task != "overview")
    ):
        raise ValueError
    if request.method == "POST":
        if (
            queue
            or task not in _ACTIONS
            or request.GET
            or request.POST.get("action") != task
        ):
            raise ValueError
        if any(
            len(values) != 1 or len(values[0].encode("utf-8")) > _MAX_INPUT_BYTES
            for _name, values in request.POST.lists()
        ):
            raise ValueError
    allowed = {"after"} if queue or task == "evidence" else set()
    if set(request.GET) - allowed:
        raise ValueError
    if "after" not in request.GET:
        return None
    values = request.GET.getlist("after")
    if len(values) != 1:
        raise ValueError
    value = values[0]
    if queue:
        if len(value) != _UUID_LENGTH:
            raise ValueError
        identifier = UUID(value)
        if value != str(identifier) or not identifier.int:
            raise ValueError
        return identifier
    if not value.isascii() or not value.isdecimal() or len(value) > _MAX_VERSION_DIGITS:
        raise ValueError
    version = int(value)
    if str(version) != value or not 1 <= version <= 2**63 - 1:
        raise ValueError
    return version


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
        title="My Programme reviews",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string(
        "applications/programme_reviewer_work.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _submit(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    source: queries.ReviewerWork,
    task: str,
) -> tuple[dict[str, Any], int]:
    form = ReviewerActionForm(request.POST, task=task, rubric=source.rubric)
    context: dict[str, Any] = {"form": form}
    if not form.is_valid():
        return context, 400
    scores = (
        tuple(
            (criterion.code, form.cleaned_data[f"score_{criterion.code}"])
            for criterion in source.rubric.criteria
        )
        if task == "score"
        else ()
    )
    try:
        context["result"] = apply_programme_review_command(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            command=ProgrammeReviewCommandInput(
                _ACTIONS[task],
                source.case.case_id,
                reference_id=source.assignment_id,
                scores=scores,
                text=form.cleaned_data.get("text", ""),
            ),
            expected_version=form.cleaned_data["expected_version"],
            retry_key=form.cleaned_data["retry_key"],
            reason=form.cleaned_data["reason"],
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except ValidationError as error:
        _apply_errors(form, error)
        return context, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "This request was not confirmed. Inspect current state before starting "
            "a new intent. Original assignment, rubric, version, retry proof and "
            "entered values remain unchanged.",
        )
        return context, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            "The review service is temporarily unavailable. Retain this exact "
            "request and inspect current state after recovery before creating "
            "a new intent.",
        )
        return context, 503
    context["form"] = None
    return context, 200


def _answer_text(row: dict[str, Any]) -> str:
    return programme_review_answer_text(row)


def _projection(detail: Any) -> dict[str, Any]:
    context = (
        json.loads(detail.context_json) if detail.context_json is not None else None
    )
    answers = (
        json.loads(detail.answers_json) if detail.answers_json is not None else None
    )
    evidence = (
        json.loads(detail.evidence_json) if detail.evidence_json is not None else None
    )
    if answers is not None:
        answers = tuple(
            {
                "label": row["label"],
                "classification": row["classification"],
                "text": _answer_text(row),
                "file_key": row["key"] if row.get("type") == "safe_file" else None,
                "domain_key": row["key"]
                if row.get("type") == "domain_reference"
                and row.get("reference_kind") in DOMAIN_REFERENCE_KINDS
                else None,
                "person_key": row["key"]
                if (row.get("type"), row.get("reference_kind"))
                == ("person_reference", "programme.person")
                else None,
            }
            for row in answers
        )
    if evidence is not None:
        evidence = tuple(
            {
                "version": row["version"],
                "action": row["action"].replace("_", " "),
                "reason": row.get("reason", ""),
                "text": row.get("payload", {}).get("text", ""),
                "scores": tuple(row.get("payload", {}).get("scores", {}).items()),
            }
            for row in evidence
        )
    return {
        "review_context": context,
        "answers": answers,
        "evidence": evidence,
        "next_evidence": detail.next_evidence_version,
    }


def _detail(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID,
    task: str,
    cursor: int,
) -> HttpResponse:
    def load() -> queries.ReviewerWork:
        return queries.get_programme_reviewer_work(
            request=scope, case_id=case_id, assignment_id=assignment_id
        )

    source = load()
    context: dict[str, Any] = {"task": task}
    status = 200
    detail = None
    if request.method == "POST":
        submitted, status = _submit(request, scope, source, task)
        context.update(submitted)
        source = load()
    elif task in _ACTIONS and task in _available(source):
        context["form"] = ReviewerActionForm(
            task=task,
            rubric=source.rubric,
            initial={"retry_key": uuid4(), "expected_version": source.case.version},
        )
    elif task in _SECTIONS:
        if source.state != "active" or source.stage != source.case.stage:
            raise Denied
        detail = get_programme_review_detail(
            request=replace(scope, requested_fields=frozenset({_SECTIONS[task]})),
            case_id=case_id,
            after_version=cursor,
        )
        if detail.version != source.case.version:
            raise Denied
        context.update(_projection(detail))
    links = _content_links(scope, source)
    context.update(source=source, actions=_available(source), content_links=links)

    def verify() -> None:
        if load() != source or _content_links(scope, source) != links:
            raise Denied
        if (
            detail is not None
            and get_programme_review_detail(
                request=replace(scope, requested_fields=frozenset({_SECTIONS[task]})),
                case_id=case_id,
                after_version=cursor,
            )
            != detail
        ):
            raise Denied

    return _html(request, scope, context, verify, status)


def _queue(
    request: HttpRequest, scope: ProgrammeReviewReadRequest, cursor: UUID | None
) -> HttpResponse:
    page = queries.list_programme_reviewer_work(request=scope, after_id=cursor)

    def verify() -> None:
        if queries.list_programme_reviewer_work(request=scope, after_id=cursor) != page:
            raise Denied

    return _html(request, scope, {"page": page}, verify)


def _route(case_id: UUID | None, assignment_id: UUID | None) -> None:
    if (case_id is None) != (assignment_id is None):
        raise ValueError


def _assignment_id(value: UUID | None) -> UUID:
    if value is None:
        raise ValueError
    return value


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_reviewer_work(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID | None = None,
    assignment_id: UUID | None = None,
    task: str = "overview",
) -> HttpResponse:
    """Serve exact own review tasks without granting manager or decision authority.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with real CSRF and closed input validation.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact owning edition.
    department_id : UUID
        Independently authorized current owner Department.
    case_id : UUID | None, default=None
        Exact case, absent only for own discovery.
    assignment_id : UUID | None, default=None
        Exact own retained assignment, absent only for discovery.
    task : str, default="overview"
        Closed task or protected content section selected by the route.

    Returns
    -------
    HttpResponse
        Independently scoped tasks, original-intent forms, receipt or safe error.
    """
    if not isinstance(request.user.pk, UUID):
        return _secure(
            HttpResponse("This review workspace is unavailable.", status=404)
        )
    scope = ProgrammeReviewReadRequest(
        request.user.pk,
        organization_id,
        edition_id,
        department_id,
        REVIEW,
        frozenset({"review_context"}),
        uuid4(),
        _SOURCE,
    )
    try:
        _authorize(scope)
        _route(case_id, assignment_id)
        cursor = _transport(request, task, queue=case_id is None)
        if case_id is None:
            return _queue(request, scope, cursor if isinstance(cursor, UUID) else None)
        return _detail(
            request,
            scope,
            case_id,
            _assignment_id(assignment_id),
            task,
            cursor if isinstance(cursor, int) else 0,
        )
    except Denied:
        return _secure(
            HttpResponse("This review workspace is unavailable.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use the complete bounded reviewer request.", status=400)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("The review service is temporarily unavailable.", status=503)
        )
