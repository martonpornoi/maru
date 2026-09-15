"""Dormant shared-shell release controls dispatching the canonical original intent."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.events.queries import resolve_edition_series_identity
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.venues.scheduling_queries import VenueSchedulingSourceDeniedError
from maru.venues.services import VenueAuthorizationDeniedError
from maru.workforce.programme_release_queries import ProgrammeReleaseSourceDeniedError
from maru.workforce.programme_staffing_queries import ProgrammeStaffingDeniedError

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import (
    SchedulingCommandResult,
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingVersionConflictError,
)
from .inputs import SchedulingCommandRequest
from .planning_queries import SchedulingReadRequest
from .release_inputs import (
    ReleaseApprovalIntent,
    ReleasePublicationIntent,
    ReleaseWarningIntent,
    ReleaseWithdrawalIntent,
)
from .release_publication_commands import (
    publish_programme_release,
    withdraw_programme_release,
)
from .release_review_commands import (
    acknowledge_programme_release_warning,
    approve_programme_release,
)
from .release_workspace import (
    COMMAND_CAPABILITIES,
    TASK_LABELS,
    authorize_release_action,
    authorize_release_task,
    compose_release_task,
)
from .release_workspace_forms import (
    ReleaseApproveForm,
    ReleaseCommandForm,
    ReleasePublishForm,
    ReleaseWarningForm,
    ReleaseWithdrawForm,
    restore_pending_warning_choice,
)

_FORMS: dict[str, type[ReleaseCommandForm]] = {
    "acknowledge": ReleaseWarningForm,
    "approve": ReleaseApproveForm,
    "publish": ReleasePublishForm,
    "withdraw": ReleaseWithdrawForm,
}
_TASK_ACTIONS = {
    "review": {"acknowledge", "approve"},
    "publish": {"publish"},
    "withdraw": {"withdraw"},
    "history": set(),
}
_DENIALS = (
    SchedulingAuthorizationDeniedError,
    ProgrammeAuthorizationDeniedError,
    ProgrammeReleaseSourceDeniedError,
    ProgrammeStaffingDeniedError,
    VenueSchedulingSourceDeniedError,
    VenueAuthorizationDeniedError,
)
_CONFLICTS = (
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingVersionConflictError,
)
_MAX_INPUT_BYTES = 512 * 1024
_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_MAX_INPUT_FIELDS = 20


def _secure(response: HttpResponse, nonce: str) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _html(
    request: HttpRequest, context: dict[str, Any], *, status: int = 200
) -> HttpResponse:
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        title="Release Programme timetable", has_permission=True, maru_csp_nonce=nonce
    )
    shell.update(context)
    content = render_to_string(
        "scheduling/release_workspace.html", shell, request=request
    ).encode("utf-8")
    if len(content) > _MAX_OUTPUT_BYTES:
        raise RuntimeError("Release workspace output exceeds its complete bound.")
    return _secure(HttpResponse(content, status=status), nonce)


def _failure(message: str, status: int) -> HttpResponse:
    # Do not reuse any partially rendered shell or source context after denial.
    return _secure(
        HttpResponse(message, status=status, content_type="text/plain; charset=utf-8"),
        token_urlsafe(32),
    )


def _series(scope: SchedulingReadRequest, series_id: UUID) -> None:
    if (
        resolve_edition_series_identity(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        != series_id
    ):
        raise SchedulingAuthorizationDeniedError


def _root(scope: SchedulingReadRequest, series_id: UUID) -> str:
    return (
        f"/admin/platform/organizations/{scope.organization_id}/series/{series_id}/"
        f"editions/{scope.edition_id}/programme/release/"
    )


def _post_action(request: HttpRequest) -> str | None:
    if request.GET or request.FILES:
        raise ValueError
    if request.method == "GET":
        return None
    # Bound transport before field construction; unknown keys/cardinality are
    # rejected by each closed form, never silently discarded by dispatch.
    if (
        len(request.POST) > _MAX_INPUT_FIELDS
        or sum(
            len(key.encode("utf-8"))
            + sum(len(value.encode("utf-8")) for value in values)
            for key, values in request.POST.lists()
        )
        > _MAX_INPUT_BYTES
        or len(request.POST.getlist("action")) != 1
    ):
        raise ValueError
    return request.POST["action"]


def _submit(
    scope: SchedulingReadRequest, form: ReleaseCommandForm
) -> SchedulingCommandResult:
    data = form.cleaned_data
    command = SchedulingCommandRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        data["retry_key"],
        scope.correlation_id,
        data["reason"],
        "release-workspace",
    )
    if isinstance(form, ReleaseWarningForm):
        return acknowledge_programme_release_warning(
            command,
            intent=ReleaseWarningIntent(form.selection(), data["finding_fingerprint"]),
        )
    if isinstance(form, ReleaseApproveForm):
        return approve_programme_release(
            command,
            intent=ReleaseApprovalIntent(form.selection(), data["acknowledgement_ids"]),
        )
    if isinstance(form, ReleasePublishForm):
        return publish_programme_release(
            command,
            intent=ReleasePublicationIntent(
                data["approval_id"],
                data["expected_active_release_id"],
                data["expected_release_version"],
                data["source_snapshot_digest"],
            ),
        )
    if isinstance(form, ReleaseWithdrawForm):
        return withdraw_programme_release(
            command,
            intent=ReleaseWithdrawalIntent(
                data["active_release_id"], data["expected_release_version"]
            ),
        )
    raise ValueError


def _command_response(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    series_id: UUID,
    task: str,
    action: str,
) -> HttpResponse:
    authorize_release_action(scope, action)
    form = _FORMS[action](request.POST)
    if isinstance(form, ReleaseWarningForm):
        restore_pending_warning_choice(form)
    context: dict[str, Any] = {
        "root_url": _root(scope, series_id),
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "task": task,
        "task_label": TASK_LABELS[task],
        "pending_form": form,
        "pending": True,
        "action": action,
        "message": "Review the marked fields. The original source and retry key "
        "have not been refreshed.",
    }
    status = 400
    if form.is_valid():
        try:
            # Do not load candidates, preflight, history, approval or pointer here.
            # The canonical command owns reauthorized exact receipt recovery
            # before fresh source collection, including a retry after withdrawal.
            result = _submit(scope, form)
        except _DENIALS:
            raise
        except _CONFLICTS:
            status = 409
            context["message"] = (
                "This exact intent conflicts with current source, lifecycle, "
                "independence or retained retry evidence. Your original input is "
                "retained. Check the recorded result before deliberately "
                "refreshing and starting a new intent."
            )
        except ValidationError:
            context["message"] = (
                "The owner could not accept this exact input. Review its fields; "
                "no source or retry key was replaced."
            )
        except (RuntimeError, DatabaseError):
            status = 503
            context["message"] = (
                "Completion could not be confirmed. Retain these exact values and "
                "retry "
                "key; retry the same intent before starting a different command."
            )
        else:
            status = 200
            context = {
                "root_url": _root(scope, series_id),
                "organization_id": scope.organization_id,
                "edition_id": scope.edition_id,
                "task": task,
                "task_label": TASK_LABELS[task],
                "receipt": result,
                "action": action,
                "message": "Previously completed action confirmed; no duplicate change."
                if result.replayed
                else "The exact release action completed. "
                "Its retained receipt is shown below.",
            }
    response = _html(request, context, status=status)
    authorize_release_action(scope, action)
    _series(scope, series_id)
    return response


def _task_chooser(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    series_id: UUID,
) -> HttpResponse:
    links = []
    for code, label in TASK_LABELS.items():
        try:
            authorize_release_task(scope, code)
        except SchedulingAuthorizationDeniedError:
            continue
        links.append((code, label))
    if not links:
        raise SchedulingAuthorizationDeniedError
    response = _html(
        request,
        {
            "links": links,
            "root_url": _root(scope, series_id),
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
        },
    )
    for code, _label in links:
        authorize_release_task(scope, code)
    return response


def _dispatch(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    series_id: UUID,
    task: str | None,
) -> HttpResponse:
    _series(scope, series_id)
    action = _post_action(request)
    if action in COMMAND_CAPABILITIES:
        if task is None or action not in _TASK_ACTIONS[task]:
            raise ValueError
        return _command_response(request, scope, series_id, task, action)
    if task is None:
        if action is not None:
            raise ValueError
        response = _task_chooser(request, scope, series_id)
    else:
        authorize_release_task(scope, task)
        context, guards = compose_release_task(
            scope,
            task,
            request.POST if action is not None else None,
        )
        context.update(
            root_url=_root(scope, series_id),
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            task=task,
            task_label=TASK_LABELS[task],
        )
        response = _html(request, context)
        for guard in guards:
            guard()
        authorize_release_task(scope, task)
    _series(scope, series_id)
    return response


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def programme_release_workspace(
    request: HttpRequest,
    *,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    task: str | None = None,
) -> HttpResponse:
    """Serve an isolated release workspace without mounting a current-profile route.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with normal CSRF and sensitive-input masking.
    organization_id : UUID
        Exact organization selected by the trusted route.
    series_id : UUID
        Expected parent series, independently checked against the edition owner.
    edition_id : UUID
        Exact edition; neither route nor hidden input grants permission.
    task : str | None, default=None
        Closed human task, or the independently admitted task chooser.

    Returns
    -------
    HttpResponse
        Complete escaped no-store task, original-intent recovery, minimized receipt,
        or a generic response which discards all prior private source content.

    Notes
    -----
    No current-source read precedes command receipt recovery. Read responses render
    first, then repeat their owner observations and field admission before release.
    Successful receipts do not depend on optional current-source or navigation reads.
    """
    actor_id = getattr(request.user, "pk", None)
    if not request.user.is_authenticated or not isinstance(actor_id, UUID):
        return _failure(
            "This Programme release workspace is not available to this account.", 403
        )
    if task is not None and task not in TASK_LABELS:
        return _failure("This Programme release task is not available.", 404)
    scope = SchedulingReadRequest(actor_id, organization_id, edition_id, uuid4())
    try:
        response = _dispatch(request, scope, series_id, task)
    except _DENIALS:
        return _failure(
            "Current permission for this release task or one of its owner fields "
            "is unavailable. If you submitted a change, verify its retained "
            "result when access returns.",
            403,
        )
    except (ValueError, ValidationError, UnicodeError):
        return _failure(
            "Use the native release controls without extra, repeated or URL input. "
            "No command was dispatched for this invalid selection.",
            400,
        )
    except (RuntimeError, DatabaseError):
        return _failure(
            "The complete release task could not be verified. No partial source "
            "is shown. If you submitted a command, retry the exact original "
            "intent before starting a new one.",
            503,
        )
    else:
        return response
