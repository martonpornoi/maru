"""Purpose-specific Guides access pages with named independent approval."""

from __future__ import annotations

from functools import partial
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Never
from uuid import UUID, uuid4

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.authorization import guidance_access as commands
from maru.authorization.guidance_access_queries import (
    GuidanceAccessRequestView,
    GuidanceAccessWorkspace,
    list_my_guidance_access_requests,
    load_guidance_access_request,
    load_guidance_access_workspace,
)
from maru.authorization.page_access import fixed_page_access
from maru.identity.request_actor import RequestActor, authenticated_request_actor

from .access_forms import (
    CAPABILITY_LABELS,
    ROLE_LABELS,
    GuidanceAccessAnswerForm,
    GuidanceAccessRequestForm,
    GuidanceAccessRevokeForm,
)
from .authorization import authorize_guidance_scope
from .contracts import GuidanceReadRequest
from .errors import GuidanceDeniedError, GuidanceError

if TYPE_CHECKING:
    from collections.abc import Callable

    from django import forms

_MAX_FORM_FIELDS = 12
_MAX_INPUT_LENGTH = 4096
_UNAVAILABLE = (
    "Guides access is temporarily unavailable. Keep your original "
    "answers and retry this form if its outcome is uncertain."
)
_STATES = {
    "waiting": "Waiting for approval",
    "accepted": "Approved",
    "declined": "Declined",
    "expired": "Expired",
    "changed": "Responsibilities changed",
}
type AccessPage = (
    GuidanceAccessWorkspace
    | GuidanceAccessRequestView
    | tuple[GuidanceAccessRequestView, ...]
)


def _unsupported_definition() -> Never:
    raise ValidationError("Unsupported responsibility definition.")


def _deny() -> Never:
    raise PermissionDenied


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _workspace_url(
    organization_id: UUID,
    edition_id: UUID,
    action: str = "workspace",
    assignment_id: UUID | None = None,
) -> str:
    kwargs = {"organization_id": organization_id, "edition_id": edition_id}
    if assignment_id is not None:
        kwargs["assignment_id"] = assignment_id
    return reverse(f"guidance-access-{action}", kwargs=kwargs)


def _request_url(request_id: UUID, action: str = "detail") -> str:
    return reverse(f"guidance-access-{action}", kwargs={"request_id": request_id})


def _content_url(
    actor: RequestActor, organization_id: UUID | None, edition_id: UUID | None
) -> str:
    if organization_id is None or edition_id is None:
        return ""
    scope = GuidanceReadRequest(actor.id, organization_id, edition_id, uuid4())
    for capability, fields in (
        ("knowledge.view_current", frozenset({"current_summary"})),
        ("knowledge.view_working", frozenset()),
    ):
        try:
            authorize_guidance_scope(scope, capability=capability, fields=fields)
        except GuidanceDeniedError:
            continue
        return reverse(
            "guidance-inventory",
            kwargs={"organization_id": organization_id, "edition_id": edition_id},
        )
    return ""


def _input(request: HttpRequest, action: str) -> None:
    if (
        request.GET
        or request.FILES
        or (request.method == "POST" and action not in {"new", "answer", "revoke"})
    ):
        raise ValueError
    if len(request.POST) > _MAX_FORM_FIELDS or any(
        len(values) != 1 or any(len(value) > _MAX_INPUT_LENGTH for value in values)
        for _, values in request.POST.lists()
    ):
        raise ValueError


def _post(  # noqa: PLR0911 - one explicit owner command per closed action
    actor: RequestActor, page: AccessPage, form: forms.Form, assignment_id: UUID | None
) -> tuple[str | None, int]:
    if not form.is_valid():
        return None, 400
    data = form.cleaned_data
    try:
        if isinstance(page, GuidanceAccessWorkspace):
            scope = page.scope
            if isinstance(form, GuidanceAccessRequestForm):
                result = commands.request_guidance_access(
                    actor=actor,
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    recipient_email=data["recipient_email"],
                    approver_id=UUID(data["approver_id"]),
                    recipe_code=data["recipe_code"],
                    reason=data["reason"],
                    expires_at=data["expires_at"],
                    idempotency_key=data["idempotency_key"],
                    correlation_id=uuid4(),
                )
                return _request_url(result.request_id), 200
            if isinstance(form, GuidanceAccessRevokeForm) and assignment_id is not None:
                commands.revoke_guidance_access(
                    actor=actor,
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    assignment_id=assignment_id,
                    reason=data["reason"],
                    correlation_id=uuid4(),
                )
                assignment = next(
                    item
                    for item in page.assignments
                    if item.assignment_id == assignment_id
                )
                if (
                    assignment.recipe_code == "guidance-access-controller"
                    and assignment.recipient.account_id == actor.id
                ):
                    return reverse("admin:index"), 200
                return _workspace_url(scope.organization_id, scope.edition_id), 200
        if isinstance(page, GuidanceAccessRequestView) and isinstance(
            form, GuidanceAccessAnswerForm
        ):
            commands.respond_to_guidance_access(
                actor=actor,
                request_id=page.request_id,
                expected_digest=data["expected_digest"],
                accept=data["decision"] == "accept",
                correlation_id=uuid4(),
            )
            return _request_url(page.request_id), 200
        _deny()
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            for field, values in error.message_dict.items():
                for value in values:
                    form.add_error(field if field in form.fields else None, value)
        else:
            form.add_error(None, " ".join(error.messages))
        return None, 409
    except DatabaseError:
        form.add_error(None, _UNAVAILABLE)
        return None, 503


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def guidance_access_workspace(  # noqa: PLR0912, PLR0915 - closed native task dispatch and final disclosure recheck
    request: HttpRequest,
    organization_id: UUID | None = None,
    edition_id: UUID | None = None,
    *,
    action: str = "workspace",
    request_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> HttpResponse:
    """Serve exact-event access management without treating content roles as control.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated person and original decision values.
    organization_id : UUID | None, default=None
        Route-owned organization, absent for personal request tasks.
    edition_id : UUID | None, default=None
        Route-owned same-parent event, absent for personal request tasks.
    action : str, default='workspace'
        Closed route-owned task.
    request_id : UUID | None, default=None
        Exact retained access request, never an alternate actor.
    assignment_id : UUID | None, default=None
        Exact retained assignment selected for removal within the admitted event.

    Returns
    -------
    HttpResponse
        Fully rechecked page, original result redirect or safe failure.
    """
    try:
        actor = authenticated_request_actor(request)
        load: Callable[[], AccessPage]
        if (
            action in {"workspace", "new", "revoke"}
            and organization_id is not None
            and edition_id is not None
        ):
            load = partial(
                load_guidance_access_workspace,
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=uuid4(),
            )
        elif action in {"detail", "answer"} and request_id is not None:
            load = partial(
                load_guidance_access_request,
                actor=actor,
                request_id=request_id,
                correlation_id=uuid4(),
            )
        elif action == "tasks":
            load = partial(
                list_my_guidance_access_requests, actor=actor, correlation_id=uuid4()
            )
        else:
            _deny()
        page = load()
        _input(request, action)
        workspace = page if isinstance(page, GuidanceAccessWorkspace) else None
        proposal = page if isinstance(page, GuidanceAccessRequestView) else None
        assignment = (
            next(
                (
                    item
                    for item in workspace.assignments
                    if item.assignment_id == assignment_id
                ),
                None,
            )
            if workspace and action == "revoke"
            else None
        )
        if action == "revoke" and assignment is None:
            _deny()
        if workspace:
            for recipe in workspace.recipes:
                if (
                    recipe.code not in ROLE_LABELS
                    or set(recipe.capability_codes) - CAPABILITY_LABELS.keys()
                ):
                    _unsupported_definition()
            if any(
                item.recipe_code not in ROLE_LABELS for item in workspace.assignments
            ):
                _unsupported_definition()
        if proposal and (
            proposal.recipe_code not in ROLE_LABELS
            or set(proposal.capability_codes) - CAPABILITY_LABELS.keys()
        ):
            _unsupported_definition()
        form: forms.Form | None = None
        data = request.POST if request.method == "POST" else None
        if (
            workspace
            and action == "new"
            and (workspace.approvers or request.method == "POST")
        ):
            form = GuidanceAccessRequestForm(
                data, workspace=workspace, initial={"idempotency_key": uuid4()}
            )
        elif (
            proposal
            and action == "answer"
            and (proposal.can_answer or request.method == "POST")
        ):
            form = GuidanceAccessAnswerForm(
                data, initial={"expected_digest": proposal.request_digest}
            )
        elif assignment:
            form = GuidanceAccessRevokeForm(data)
        status = 200
        with timezone.override(workspace.scope.time_zone if workspace else "UTC"):
            if request.method == "POST":
                if form is None:
                    _deny()
                destination, status = _post(actor, page, form, assignment_id)
                if destination:
                    messages.success(
                        request,
                        {
                            "new": (
                                "Access request saved. The named approver must "
                                "make their own decision."
                            ),
                            "answer": "Your access decision is saved.",
                            "revoke": (
                                "The assignment was removed. Its history is kept."
                            ),
                        }[action],
                    )
                    return _secure(HttpResponseRedirect(destination))
            scope_org = (
                workspace.scope.organization_id
                if workspace
                else (proposal.organization_id if proposal else None)
            )
            scope_edition = (
                workspace.scope.edition_id
                if workspace
                else (proposal.edition_id if proposal else None)
            )
            content_url = _content_url(actor, scope_org, scope_edition)
            nonce = token_urlsafe(32)
            context = dict(admin.site.each_context(request))
            context.update(
                title={
                    "workspace": "Manage access to guides",
                    "new": "Request access for someone",
                    "revoke": "Remove Guides access",
                    "detail": "Guides access request",
                    "answer": "Decide about Guides access",
                    "tasks": "Your Guides access decisions",
                }[action],
                action=action,
                form=form,
                access_workspace=workspace,
                proposal=proposal,
                assignment=assignment,
                has_permission=True,
                maru_csp_nonce=nonce,
                content_url=content_url,
                guidance_scope=workspace.scope if workspace else None,
                scope_label=(
                    f"{workspace.scope.organization_name} / "
                    f"{workspace.scope.edition_name}"
                )
                if workspace
                else (proposal.edition_name if proposal else ""),
                maru_page_access_spec=fixed_page_access(
                    policy="fixed",
                    scope_label="Guides access for this event",
                    explanation=(
                        "Current responsibility for managing Guides access "
                        "is required. A named second person must approve each "
                        "new content assignment "
                        "through their own account. Reading or writing guides does not "
                        "grant access-management powers."
                    ),
                ),
                tasks_url=reverse("guidance-access-tasks"),
                setup_tasks_url=reverse("guidance-activation-tasks"),
                access_url=_workspace_url(scope_org, scope_edition)
                if scope_org and scope_edition
                else "",
                new_url=_workspace_url(scope_org, scope_edition, "new")
                if scope_org and scope_edition
                else "",
                request_url=_request_url(proposal.request_id) if proposal else "",
                answer_url=_request_url(proposal.request_id, "answer")
                if proposal
                else "",
                recipe_rows=tuple(
                    (
                        ROLE_LABELS[recipe.code],
                        tuple(
                            CAPABILITY_LABELS[code] for code in recipe.capability_codes
                        ),
                    )
                    for recipe in workspace.recipes
                )
                if workspace
                else (),
                assignment_rows=tuple(
                    (
                        item,
                        ROLE_LABELS[item.recipe_code],
                        _workspace_url(
                            workspace.scope.organization_id,
                            workspace.scope.edition_id,
                            "revoke",
                            item.assignment_id,
                        ),
                    )
                    for item in workspace.assignments
                )
                if workspace
                else (),
                assignment_label=ROLE_LABELS[assignment.recipe_code]
                if assignment
                else "",
                recipe_label=ROLE_LABELS[proposal.recipe_code] if proposal else "",
                powers=tuple(
                    CAPABILITY_LABELS[code] for code in proposal.capability_codes
                )
                if proposal
                else (),
                task_rows=tuple(
                    (item, _request_url(item.request_id), _STATES[item.state])
                    for item in page
                )
                if isinstance(page, tuple)
                else (),
                state_label=_STATES[proposal.state] if proposal else "",
                submit_label={
                    "new": "Request this access",
                    "answer": "Save my decision",
                    "revoke": "Remove this access",
                }.get(action, ""),
                baseline_hide_admin_scoped_navigation=workspace is None,
            )
            content = render_to_string(
                "knowledge/access.html", context, request=request
            )
        if (
            load() != page
            or _content_url(actor, scope_org, scope_edition) != content_url
        ):
            return _secure(
                HttpResponse(
                    (
                        "The access request, event or your responsibilities changed. "
                        "Reload before continuing."
                    ),
                    status=409,
                ),
                nonce,
            )
        return _secure(HttpResponse(content, status=status), nonce)
    except PermissionDenied:
        return _secure(
            HttpResponse("This Guides access page is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Guides access input.", status=400))
    except (ValidationError, DatabaseError, GuidanceError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
