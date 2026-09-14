"""Dormant named reviewer management through independently scoped owner commands."""

from __future__ import annotations

from dataclasses import replace
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django import forms
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.core.forms import StrictBase10IntegerField

from . import programme_review_management_queries as queries
from . import programme_reviewer_selection as selections
from .forms import RetryForm
from .models import ProgrammeReviewAction
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
from .programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from .programme_review_inputs import MAX_REVIEW_REASON, ProgrammeReviewCommandInput
from .programme_review_queries import ProgrammeReviewReadRequest
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-review-management"
_MAX_INPUT_BYTES = 12_000
_UUID_LENGTH = 36


class ReviewerPreviewForm(RetryForm):
    """Preview one known email with original case and retry proof, without assigning."""

    transport_field_names = RetryForm.transport_field_names | {"action"}

    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput
    )
    email = forms.EmailField(
        label="Known reviewer's email",
        max_length=254,
        help_text=(
            "Use one existing active verified person's exact address. "
            "No directory is searched or invitation sent."
        ),
    )


class ReviewerRemovalForm(RetryForm):
    """Confirm one retained assignment removal without rewriting its evidence."""

    transport_field_names = RetryForm.transport_field_names | {"action"}

    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput
    )
    reason = forms.CharField(
        label="Reason",
        max_length=MAX_REVIEW_REASON,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="I confirm removal of this exact reviewer assignment"
    )


class ReviewerAssignmentForm(ReviewerRemovalForm):
    """Confirm the exact purpose-signed person without resolving email again."""

    selection = forms.CharField(
        max_length=selections.MAX_REVIEWER_SELECTION_BYTES, widget=forms.HiddenInput
    )
    confirm = forms.BooleanField(
        label="I confirm assignment of this exact person to the current review stage",
        help_text=(
            "Assignment does not grant review permission or clear the person's "
            "conflicts of interest."
        ),
    )


def _setup_root(scope: ProgrammeReviewReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/"
    )


def _root(scope: ProgrammeReviewReadRequest) -> str:
    return f"{_setup_root(scope)}cases/"


def _authorize(scope: ProgrammeReviewReadRequest) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        capability_code=MANAGE_REVIEW,
        requested_fields=scope.requested_fields,
    )


def can_manage_programme_review_cases(scope: ProgrammeReviewReadRequest) -> bool:
    """Test independent manager-context entry without granting case access.

    Parameters
    ----------
    scope : ProgrammeReviewReadRequest
        Current authenticated review context; its field request is not inherited.

    Returns
    -------
    bool
        Whether a case-management destination may independently be offered.
    """
    try:
        _authorize(replace(scope, requested_fields=frozenset({"review_context"})))
    except Denied:
        return False
    return True


def _can_setup(scope: ProgrammeReviewReadRequest) -> bool:
    try:
        _authorize(replace(scope, requested_fields=frozenset({"review_setup"})))
    except Denied:
        return False
    return True


def _transport(request: HttpRequest, case_id: UUID | None, task: str) -> UUID | None:
    if (
        request.FILES
        or set(request.GET) - {"after"}
        or (case_id is not None and request.GET)
    ):
        raise ValueError
    if request.method == "POST":
        if case_id is None or request.GET or task not in {"assign", "remove"}:
            raise ValueError
        action = request.POST.get("action", "")
        form_type = {
            ("assign", "preview"): ReviewerPreviewForm,
            ("assign", "assign"): ReviewerAssignmentForm,
            ("remove", "remove"): ReviewerRemovalForm,
        }.get((task, action))
        if form_type is None or set(request.POST) - {
            *form_type.base_fields,
            "action",
            "csrfmiddlewaretoken",
        }:
            raise ValueError
        if any(
            len(values) != 1 or len(values[0].encode("utf-8")) > _MAX_INPUT_BYTES
            for _name, values in request.POST.lists()
        ):
            raise ValueError
    if "after" not in request.GET:
        return None
    if len(request.GET.getlist("after")) != 1:
        raise ValueError
    value = request.GET["after"]
    if len(value) != _UUID_LENGTH:
        raise ValueError
    identifier = UUID(value)
    if value != str(identifier) or not identifier.int:
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
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        title="Manage Programme reviewers",
        root_url=_root(scope),
        setup_url=_setup_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string(
        "applications/programme_review_management.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _choice(
    scope: ProgrammeReviewReadRequest, case_id: UUID, form: ReviewerAssignmentForm
) -> selections.ProgrammeReviewerSelection | None:
    if any(
        name not in form.cleaned_data
        for name in ("selection", "expected_version", "retry_key")
    ):
        return None
    return selections.read_programme_reviewer_selection(
        request=scope,
        case_id=case_id,
        token=form.cleaned_data["selection"],
        expected_version=form.cleaned_data["expected_version"],
        retry_key=form.cleaned_data["retry_key"],
    )


def _preview(
    scope: ProgrammeReviewReadRequest, case_id: UUID, form: ReviewerPreviewForm
) -> tuple[dict[str, Any], int]:
    selected = selections.prepare_programme_reviewer_selection(
        request=scope,
        case_id=case_id,
        email=form.cleaned_data["email"],
        expected_version=form.cleaned_data["expected_version"],
        retry_key=form.cleaned_data["retry_key"],
    )
    if selected is None:
        form.add_error(
            "email", "This address cannot be selected for this review assignment."
        )
        return {"form": form, "mode": "preview"}, 400
    return {
        "form": ReviewerAssignmentForm(
            initial={
                "expected_version": selected.expected_version,
                "retry_key": selected.retry_key,
                "selection": selected.token,
            }
        ),
        "mode": "assign",
        "selected": selected,
    }, 200


def _command(
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    form: ReviewerRemovalForm,
    reference_id: UUID,
    *,
    remove: bool,
) -> ProgrammeReviewResult:
    return apply_programme_review_command(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        command=ProgrammeReviewCommandInput(
            ProgrammeReviewAction.REVIEWER_REMOVED
            if remove
            else ProgrammeReviewAction.REVIEWER_ASSIGNED,
            case_id,
            reference_id=reference_id,
        ),
        expected_version=form.cleaned_data["expected_version"],
        retry_key=form.cleaned_data["retry_key"],
        reason=form.cleaned_data["reason"],
        correlation_id=scope.correlation_id,
        source_channel=_SOURCE,
    )


def _submit(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID | None,
) -> tuple[dict[str, Any], int]:
    action = request.POST["action"]
    forms_by_action: dict[str, type[ReviewerPreviewForm | ReviewerRemovalForm]] = {
        "preview": ReviewerPreviewForm,
        "assign": ReviewerAssignmentForm,
        "remove": ReviewerRemovalForm,
    }
    form = forms_by_action[action](request.POST)
    valid = form.is_valid()
    selected = (
        _choice(scope, case_id, form)
        if isinstance(form, ReviewerAssignmentForm)
        else None
    )
    context: dict[str, Any] = {"form": form, "mode": action, "selected": selected}
    status = 400
    if not valid:
        return context, status
    try:
        if isinstance(form, ReviewerPreviewForm):
            return _preview(scope, case_id, form)
        reference_id = (
            assignment_id
            if action == "remove"
            else selected.account_id
            if selected
            else None
        )
        if reference_id is None:
            raise Denied
        context["result"] = _command(
            scope, case_id, form, reference_id, remove=action == "remove"
        )
    except ValidationError as error:
        _apply_errors(form, error)
    except _CONFLICTS:
        status = 409
        form.add_error(
            None,
            "This request was not confirmed. Inspect current case and assignment "
            "state. Your original selected person, version, retry proof and entered "
            "reason remain unchanged; a different selection requires a deliberate "
            "new intent.",
        )
    except _UNAVAILABLE:
        status = 503
        form.add_error(
            None,
            "The review service is temporarily unavailable. Retain this exact "
            "request and inspect the roster after recovery before starting "
            "a new intent.",
        )
    else:
        context["form"] = None
        status = 200
    return context, status


def _detail(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    task: str,
    assignment_id: UUID | None,
) -> HttpResponse:
    source = queries.get_programme_review_management(request=scope, case_id=case_id)
    context: dict[str, Any] = {
        "source": source,
        "task": task,
        "can_setup": _can_setup(scope),
    }
    assignment = next(
        (row for row in source.assignments if row.assignment_id == assignment_id), None
    )
    if task == "remove" and assignment is None:
        raise Denied
    fresh = source.writable and source.case.current_revision
    context.update(assignment=assignment, fresh=fresh)
    status = 200
    if request.method == "POST":
        submitted, status = _submit(request, scope, case_id, assignment_id)
        context.update(submitted)
        source = queries.get_programme_review_management(request=scope, case_id=case_id)
        context["source"] = source
        context["fresh"] = source.writable and source.case.current_revision
        context["assignment"] = next(
            (row for row in source.assignments if row.assignment_id == assignment_id),
            None,
        )
        if task == "remove" and context["assignment"] is None:
            raise Denied
    elif task == "assign" and fresh and source.case.state == "open":
        context.update(
            form=ReviewerPreviewForm(
                initial={"retry_key": uuid4(), "expected_version": source.case.version}
            ),
            mode="preview",
        )
    elif (
        task == "remove"
        and fresh
        and assignment is not None
        and assignment.state in {"pending", "active"}
    ):
        context.update(
            form=ReviewerRemovalForm(
                initial={"retry_key": uuid4(), "expected_version": source.case.version}
            ),
            mode="remove",
        )

    def verify() -> None:
        if (
            queries.get_programme_review_management(request=scope, case_id=case_id)
            != source
            or _can_setup(scope) != context["can_setup"]
        ):
            raise Denied
        selected = context.get("selected")
        if (
            selected is not None
            and selections.read_programme_reviewer_selection(
                request=scope,
                case_id=case_id,
                token=selected.token,
                expected_version=selected.expected_version,
                retry_key=selected.retry_key,
            )
            != selected
        ):
            raise Denied

    return _html(request, scope, context, verify, status)


def _queue(
    request: HttpRequest, scope: ProgrammeReviewReadRequest, cursor: UUID | None
) -> HttpResponse:
    page = queries.list_programme_review_management_cases(
        request=scope, after_id=cursor
    )
    can_setup = _can_setup(scope)

    def verify() -> None:
        if (
            queries.list_programme_review_management_cases(
                request=scope, after_id=cursor
            )
            != page
            or _can_setup(scope) != can_setup
        ):
            raise Denied

    return _html(request, scope, {"page": page, "can_setup": can_setup}, verify)


def _route(case_id: UUID | None, task: str, assignment_id: UUID | None) -> None:
    if (
        task not in {"overview", "assign", "remove"}
        or ((assignment_id is not None) != (task == "remove"))
        or (case_id is None and task != "overview")
    ):
        raise ValueError


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_review_management(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID | None = None,
    task: str = "overview",
    assignment_id: UUID | None = None,
) -> HttpResponse:
    """Manage exact named review assignments without granting review-content access.

    Parameters
    ----------
    request : HttpRequest
        Authenticated manager request with ordinary CSRF protection.
    organization_id : UUID
        Exact owning organization from the reserved route.
    edition_id : UUID
        Exact current edition scope.
    department_id : UUID
        Current owner Department, independently authorized.
    case_id : UUID | None, default=None
        Selected case, absent for the complete bounded management queue.
    task : str, default="overview"
        Closed overview, assign or remove task selected by the route.
    assignment_id : UUID | None, default=None
        Exact retained assignment for removal, absent otherwise.

    Returns
    -------
    HttpResponse
        Scoped ordinary forms, retained-intent recovery, owner receipt or safe error.
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
        frozenset({"review_context"}),
        uuid4(),
        _SOURCE,
    )
    try:
        _authorize(scope)
        _route(case_id, task, assignment_id)
        cursor = _transport(request, case_id, task)
        return (
            _queue(request, scope, cursor)
            if case_id is None
            else _detail(request, scope, case_id, task, assignment_id)
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
