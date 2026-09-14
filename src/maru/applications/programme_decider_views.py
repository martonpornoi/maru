"""Dormant independent decision composition and exact-preview receipt recovery."""

from __future__ import annotations

from dataclasses import asdict, replace
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

from . import programme_decider_queries as queries
from .models import ProgrammeReviewAction
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_decider_forms import (
    OUTCOME_LABELS,
    DecisionConfirmForm,
    DecisionDraftForm,
)
from .programme_decider_preview import (
    DecisionIntent,
    DecisionPreview,
    prepare_programme_decision_preview,
    verify_programme_decision_preview,
)
from .programme_decision_views import _CONFLICTS, _UNAVAILABLE
from .programme_moderation_views import _integer, _projection
from .programme_review_authorization import DECIDE, authorize_programme_review_scope
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import ProgrammeReviewCommandInput
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    get_programme_review_detail,
)
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-decision-compose"
_SECTIONS = {
    "context": "review_context",
    "answers": "review_answers",
    "evidence": "review_evidence",
    "messages": "review_evidence",
}
_MAX_INPUT_BYTES = 12_000


def _root(scope: ProgrammeReviewReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/decisions/"
    )


def _authorize(scope: ProgrammeReviewReadRequest) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        capability_code=DECIDE,
        requested_fields=scope.requested_fields,
    )


def _transport(request: HttpRequest, task: str, *, queue: bool) -> dict[str, Any]:
    if request.FILES or task not in {"overview", "decide", *_SECTIONS}:
        raise ValueError
    if queue and (task != "overview" or request.method != "GET"):
        raise ValueError
    if request.method == "POST" and (
        task != "decide"
        or request.GET
        or request.POST.get("action") not in {"preview", "confirm"}
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
        else (
            {"after", "version"}
            if task in {"evidence", "messages", "decide"}
            else set()
        )
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


def _available(source: queries.DecisionWork) -> bool:
    return (
        source.writable
        and source.case.current_revision
        and source.case.state in {"open", "waitlisted"}
        and source.case.stage == len(source.policy.stages) - 1
    )


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
        title="Programme decisions",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string("applications/programme_decider.html", shell, request)
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _confirm(
    scope: ProgrammeReviewReadRequest, case_id: UUID, form: DecisionConfirmForm
) -> tuple[Any, DecisionIntent | None, int]:
    if not form.is_valid():
        return None, None, 400
    intent = None
    try:
        intent = verify_programme_decision_preview(
            request=scope,
            case_id=case_id,
            intent=form.to_intent(),
            proof=form.cleaned_data["preview_proof"],
        )
        result = apply_programme_review_command(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            command=ProgrammeReviewCommandInput(
                ProgrammeReviewAction.DECIDED,
                case_id,
                outcome=intent.outcome,
                text=intent.text,
            ),
            expected_version=intent.expected_version,
            retry_key=intent.retry_key,
            reason=intent.reason,
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except ValidationError as error:
        _apply_errors(form, error)
        return None, intent, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "This decision was not confirmed. Keep the original version, retry, "
            "outcome, recipient text and private rationale. "
            "Inspect current state before starting a new intent.",
        )
        return None, intent, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            "The decision service is temporarily unavailable. Keep this exact "
            "confirmed request for original receipt recovery; "
            "do not replace its version or retry proof.",
        )
        return None, intent, 503
    return result, intent, 200


def _prepare(
    scope: ProgrammeReviewReadRequest, case_id: UUID, form: DecisionDraftForm
) -> tuple[DecisionPreview | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        return prepare_programme_decision_preview(
            request=scope, case_id=case_id, intent=form.to_intent()
        ), 200
    except ValidationError as error:
        _apply_errors(form, error)
        return None, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "A new preview is unavailable for this original version or decision "
            "state. Every stage needs fresh moderation and sufficient valid "
            "reviews. Original input and retry identity remain unchanged.",
        )
        return None, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            "The preview service is temporarily unavailable. No decision was "
            "recorded; keep the original intent and inspect current state "
            "after recovery.",
        )
        return None, 503


def _message(source: queries.DecisionWork, intent: DecisionIntent) -> dict[str, Any]:
    template = next(
        row for row in source.policy.templates if row.outcome == intent.outcome
    )
    return {
        "preview_template": template,
        "preview_intent": intent,
        "preview_message": template.text + "\n\n" + intent.text,
        "preview_outcome": OUTCOME_LABELS[intent.outcome],
    }


def _detail(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    task: str,
    cursors: dict[str, Any],
) -> HttpResponse:
    form: DecisionDraftForm | None = None
    preview = None
    intent = None
    status = 200
    if request.method == "POST":
        if request.POST["action"] == "confirm":
            confirmation = DecisionConfirmForm(request.POST)
            result, intent, status = _confirm(scope, case_id, confirmation)
            if result is not None:
                return _html(
                    request, scope, {"result": result}, lambda: _authorize(scope)
                )
            form = confirmation
        else:
            form = DecisionDraftForm(request.POST)
            preview, status = _prepare(scope, case_id, form)
            if preview is not None:
                intent = preview.intent
                form = DecisionConfirmForm(
                    initial=asdict(intent) | {"preview_proof": preview.proof}
                )

    return _inspect(
        request, scope, case_id, task, cursors, form, preview, intent, status
    )


def _inspect(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    task: str,
    cursors: dict[str, Any],
    form: DecisionDraftForm | None,
    preview: DecisionPreview | None,
    intent: DecisionIntent | None,
    status: int,
) -> HttpResponse:

    def load() -> queries.DecisionWork:
        return queries.get_programme_decision_work(request=scope, case_id=case_id)

    source = preview.work if preview else load()
    links = _links(scope)
    context: dict[str, Any] = {
        "source": source,
        "task": task,
        "content_links": links,
        "can_decide": _available(source) and "evidence" in links,
    }
    facts = preview.evidence if preview else None
    detail = facts.detail if facts else None
    messages = None
    section = "evidence" if task == "decide" else task

    def read() -> Any:
        protected = replace(scope, requested_fields=frozenset({_SECTIONS[section]}))
        if section == "evidence":
            return queries.get_programme_decision_evidence(
                request=protected,
                case_id=case_id,
                after_version=cursors.get("after", 0),
            )
        if section == "messages":
            return queries.list_programme_decision_messages(
                request=protected,
                case_id=case_id,
                after_version=cursors.get("after", 0),
            )
        return get_programme_review_detail(request=protected, case_id=case_id)

    if request.method == "GET" and section in _SECTIONS:
        projected = read()
        if section == "messages":
            messages = projected
        elif section == "evidence":
            facts, detail = projected, projected.detail
        else:
            detail = projected
        version = (
            projected.version if section != "evidence" else projected.detail.version
        )
        if version != source.case.version:
            raise Denied
        if cursors.get("version", version) != version:
            context["snapshot_stale"] = True
            detail = facts = messages = None
            status = 409
    if detail is not None:
        # Shared formatting consumes only already-authorized projections; no
        # moderator capability or query is inherited by this decider surface.
        context.update(
            _projection(detail, source.policy.stages), snapshot=detail.version
        )
    if messages is not None:
        context.update(decision_messages=messages, snapshot=messages.version)
    context["facts"] = facts
    if (
        request.method == "GET"
        and task == "decide"
        and context["can_decide"]
        and facts is not None
        and all(stage.ready for stage in facts.stages)
    ):
        form = DecisionDraftForm(
            initial={"expected_version": source.case.version, "retry_key": uuid4()}
        )
    if intent is not None:
        context.update(_message(source, intent))
    context.update(form=form, confirmation=isinstance(form, DecisionConfirmForm))

    def verify() -> None:
        if load() != source or _links(scope) != links:
            raise Denied
        if facts is not None and read() != facts:
            raise Denied
        if facts is None and detail is not None and read() != detail:
            raise Denied
        if messages is not None and read() != messages:
            raise Denied

    return _html(request, scope, context, verify, status)


def _queue(
    request: HttpRequest, scope: ProgrammeReviewReadRequest, cursors: dict[str, Any]
) -> HttpResponse:
    page = queries.list_programme_decision_cases(request=scope, **cursors)

    def verify() -> None:
        if queries.list_programme_decision_cases(request=scope, **cursors) != page:
            raise Denied

    return _html(request, scope, {"page": page}, verify)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_decider(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID | None = None,
    task: str = "overview",
) -> HttpResponse:
    """Serve independent exact-preview decisions without conversion authority.

    Parameters
    ----------
    request : HttpRequest
        Authenticated closed request with real CSRF and bounded input.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact owning edition.
    department_id : UUID
        Independently authorized current owner Department.
    case_id : UUID | None, default=None
        Exact retained case, absent only for discovery.
    task : str, default="overview"
        Closed composition or protected history/content task from the route.

    Returns
    -------
    HttpResponse
        Independent task, explicit preview, original receipt or safe failure.
    """
    if not isinstance(request.user.pk, UUID):
        return _secure(
            HttpResponse("This decision workspace is unavailable.", status=404)
        )
    scope = ProgrammeReviewReadRequest(
        request.user.pk,
        organization_id,
        edition_id,
        department_id,
        DECIDE,
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
            HttpResponse("This decision workspace is unavailable.", status=404)
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use the complete bounded decision request.", status=400)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("The decision service is temporarily unavailable.", status=503)
        )
