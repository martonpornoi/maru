"""Server-rendered scoped access management and non-impersonating preview."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from maru.audit.models import AuditEvent
from maru.authorization.access import (
    AccessPreviewResult,
    preview_exact_person_access,
    preview_role_bundle_access,
)
from maru.authorization.commands import assign_role, revoke_role_assignment
from maru.authorization.page_access import decode_page_access_target
from maru.authorization.page_access_forms import (
    PageAccessAssignmentForm,
    PageAccessPersonPreviewForm,
    PageAccessRevokeForm,
    PageAccessRolePreviewForm,
    UnsupportedPageAccessActionForm,
)
from maru.authorization.page_access_workspace import (
    PageAccessWorkspace,
    audit_page_access_preview,
    audit_page_access_relationship_denial,
    exact_active_approver,
    exact_active_person,
    exact_assignment_for_target,
    exact_role_version,
    load_page_access_workspace,
    require_page_access_authority,
)
from maru.identity.models import Account

if TYPE_CHECKING:
    from django.forms import Form

    from maru.authorization.policy import ResolvedAuthorizationTarget

type AccessForm = (
    PageAccessAssignmentForm
    | PageAccessRevokeForm
    | PageAccessPersonPreviewForm
    | PageAccessRolePreviewForm
    | UnsupportedPageAccessActionForm
)


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied("Access management is unavailable.")
    return request.user


def _correlation_id(request: HttpRequest) -> UUID:
    return UUID(request.correlation_id)  # type: ignore[attr-defined]


def _target(scope_token: str) -> ResolvedAuthorizationTarget:
    target = decode_page_access_target(scope_token)
    if target is None:
        raise Http404
    return target


def _form_for_request(request: HttpRequest) -> AccessForm:
    actions = request.POST.getlist("action")
    if len(actions) != 1:
        return UnsupportedPageAccessActionForm(request.POST)
    if actions[0] == "assign":
        return PageAccessAssignmentForm(request.POST)
    if actions[0] == "revoke":
        return PageAccessRevokeForm(request.POST)
    if actions[0] == "preview_person":
        return PageAccessPersonPreviewForm(request.POST)
    if actions[0] == "preview_role":
        return PageAccessRolePreviewForm(request.POST)
    return UnsupportedPageAccessActionForm(request.POST)


def _add_validation_errors(form: Form, error: ValidationError) -> None:
    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            target = field_name if field_name in form.fields else None
            for field_error in field_errors:
                form.add_error(target, field_error)
        return
    for message in error.messages:
        form.add_error(None, message)


def _new_forms() -> dict[str, Form]:
    return {
        "assignment_form": PageAccessAssignmentForm(initial={"action": "assign"}),
        "person_preview_form": PageAccessPersonPreviewForm(
            initial={"action": "preview_person"}
        ),
        "role_preview_form": PageAccessRolePreviewForm(
            initial={"action": "preview_role"}
        ),
    }


def _render_workspace(
    request: HttpRequest,
    *,
    scope_token: str,
    workspace: PageAccessWorkspace,
    active_form: AccessForm | None = None,
    preview: AccessPreviewResult | None = None,
    status: int = 200,
) -> HttpResponse:
    context: dict[str, object] = {
        "title": f"Access to {workspace.scope_label}",
        "workspace": workspace,
        "scope_token": scope_token,
        "preview": preview,
        "page_access_preview_active": preview is not None,
        "maru_suppress_page_access_component": True,
        **_new_forms(),
    }
    if isinstance(active_form, PageAccessAssignmentForm):
        context["assignment_form"] = active_form
    elif isinstance(active_form, PageAccessPersonPreviewForm):
        context["person_preview_form"] = active_form
    elif isinstance(active_form, PageAccessRolePreviewForm):
        context["role_preview_form"] = active_form
    elif active_form is not None:
        context["action_form"] = active_form
    response = TemplateResponse(
        request,
        "authorization/page_access_workspace.html",
        context,
        status=status,
    )
    response["Cache-Control"] = "private, no-store"
    return response


def _run_preview(
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    form: PageAccessPersonPreviewForm | PageAccessRolePreviewForm,
    correlation_id: UUID,
) -> AccessPreviewResult:
    if isinstance(form, PageAccessPersonPreviewForm):
        person = exact_active_person(str(form.cleaned_data["person_email"]))
        result = preview_exact_person_access(
            viewer=actor,
            person=person,
            target=target,
        )
    else:
        role = exact_role_version(
            target=target,
            role_version_id=form.cleaned_data["role_version_id"],
        )
        result = preview_role_bundle_access(
            viewer=actor,
            role_bundle=role,
            target=target,
        )
    audit_page_access_preview(
        actor=actor,
        target=target,
        correlation_id=correlation_id,
        outcome=AuditEvent.Outcome.ALLOW,
        reason_code="computed_effective_access",
        mode=result.mode,
        subject_id=result.subject_id,
        target_count=len(result.capabilities),
    )
    return result


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(["GET", "POST"])
def page_access_workspace(
    request: HttpRequest,
    scope_token: str,
) -> HttpResponse:
    """Manage canonical scoped assignments or explain a read-only preview.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    scope_token : str
        The opaque scope token supplied by the caller.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks the authority required by the operation.
    """
    if request.method == "GET" and request.GET:
        return HttpResponse("Unsupported query parameters.", status=400)
    actor = _actor(request)
    target = _target(scope_token)
    correlation_id = _correlation_id(request)
    try:
        require_page_access_authority(actor=actor, target=target)
    except PermissionDenied:
        audit_page_access_relationship_denial(
            actor=actor,
            target=target,
            correlation_id=correlation_id,
        )
        raise
    active_form: AccessForm | None = None
    preview: AccessPreviewResult | None = None
    status = 200

    if request.method == "POST":
        active_form = _form_for_request(request)
        if not active_form.is_valid():
            status = 400
        else:
            try:
                if isinstance(active_form, PageAccessAssignmentForm):
                    person = exact_active_person(
                        str(active_form.cleaned_data["person_email"])
                    )
                    approver = exact_active_approver(
                        str(active_form.cleaned_data["approver_email"])
                    )
                    role = exact_role_version(
                        target=target,
                        role_version_id=active_form.cleaned_data["role_version_id"],
                    )
                    assign_role(
                        actor=actor,
                        approver=approver,
                        recipient=person,
                        target=target,
                        role_bundle_id=role.id,
                        effective_from=timezone.now(),
                        expires_at=active_form.cleaned_data.get("expires_at"),
                        reason=str(active_form.cleaned_data["reason"]),
                        correlation_id=correlation_id,
                        request_id=correlation_id,
                        source_channel="html",
                    )
                    messages.success(request, "Scoped access was assigned.")
                    return redirect(
                        "page-access-workspace",
                        scope_token=scope_token,
                    )
                if isinstance(active_form, PageAccessRevokeForm):
                    assignment = exact_assignment_for_target(
                        target=target,
                        assignment_id=active_form.cleaned_data["assignment_id"],
                    )
                    revoke_role_assignment(
                        actor=actor,
                        target=target,
                        assignment_id=assignment.id,
                        reason=str(active_form.cleaned_data["reason"]),
                        correlation_id=correlation_id,
                        request_id=correlation_id,
                        source_channel="html",
                    )
                    messages.success(request, "Scoped access was removed.")
                    return redirect(
                        "page-access-workspace",
                        scope_token=scope_token,
                    )
                if isinstance(
                    active_form,
                    (PageAccessPersonPreviewForm, PageAccessRolePreviewForm),
                ):
                    preview = _run_preview(
                        actor=actor,
                        target=target,
                        form=active_form,
                        correlation_id=correlation_id,
                    )
            except ValidationError as error:
                _add_validation_errors(active_form, error)
                if isinstance(
                    active_form,
                    (PageAccessPersonPreviewForm, PageAccessRolePreviewForm),
                ):
                    audit_page_access_preview(
                        actor=actor,
                        target=target,
                        correlation_id=correlation_id,
                        outcome=AuditEvent.Outcome.DENY,
                        reason_code="preview_subject_unavailable",
                        mode=(
                            "person"
                            if isinstance(active_form, PageAccessPersonPreviewForm)
                            else "role"
                        ),
                    )
                status = 400

    workspace = load_page_access_workspace(
        actor=actor,
        target=target,
        correlation_id=correlation_id,
    )
    return _render_workspace(
        request,
        scope_token=scope_token,
        workspace=workspace,
        active_form=active_form,
        preview=preview,
        status=status,
    )
