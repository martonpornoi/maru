"""Native Guides setup decisions using only the Events public authority seams."""

from __future__ import annotations

from functools import partial
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Never
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.authorization.page_access import fixed_page_access
from maru.identity.request_actor import RequestActor, authenticated_request_actor
from maru.knowledge.authorization import authorize_guidance_scope
from maru.knowledge.contracts import GuidanceReadRequest
from maru.knowledge.errors import GuidanceDeniedError, GuidanceError

from . import guidance_activation as commands
from .guidance_activation_forms import (
    GuidanceActivationAnswerForm,
    GuidanceActivationApplyForm,
    GuidanceActivationProposalForm,
)
from .guidance_activation_queries import (
    GuidanceActivationRequestView,
    GuidanceActivationStart,
    list_my_guidance_activation_requests,
    load_guidance_activation_request,
    load_guidance_activation_start,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from django import forms

_MAX_FORM_FIELDS = 12
_MAX_INPUT_LENGTH = 4096
_UNAVAILABLE = (
    "Guides setup is temporarily unavailable. Keep your original "
    "answers and retry this form if its outcome is uncertain."
)
_STATES = {
    "waiting": "Waiting for both people",
    "accepted": "Both people accepted",
    "applied": "Setup applied",
    "declined": "Declined",
    "expired": "Expired",
    "changed": "The event or responsibilities changed",
}


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


def _request_url(request_id: UUID, action: str = "detail") -> str:
    return reverse(f"guidance-activation-{action}", kwargs={"request_id": request_id})


def _content_url(
    actor: RequestActor,
    scope: GuidanceActivationStart | GuidanceActivationRequestView | None,
) -> str:
    if scope is None:
        return ""
    request = GuidanceReadRequest(
        actor.id, scope.organization_id, scope.edition_id, uuid4()
    )
    for capability, fields in (
        ("knowledge.view_current", frozenset({"current_summary"})),
        ("knowledge.view_working", frozenset()),
    ):
        try:
            authorize_guidance_scope(request, capability=capability, fields=fields)
        except GuidanceDeniedError:
            continue
        return reverse(
            "guidance-inventory",
            kwargs={
                "organization_id": scope.organization_id,
                "edition_id": scope.edition_id,
            },
        )
    return ""


def _input(request: HttpRequest, *, writable: bool) -> None:
    if request.GET or request.FILES or (request.method == "POST" and not writable):
        raise ValueError
    if len(request.POST) > _MAX_FORM_FIELDS or any(
        len(values) != 1 or any(len(value) > _MAX_INPUT_LENGTH for value in values)
        for _, values in request.POST.lists()
    ):
        raise ValueError


def _form(
    request: HttpRequest,
    action: str,
    page: GuidanceActivationStart
    | GuidanceActivationRequestView
    | tuple[GuidanceActivationRequestView, ...],
) -> forms.Form | None:
    data = request.POST if request.method == "POST" else None
    if isinstance(page, GuidanceActivationStart) and (
        page.can_propose or request.method == "POST"
    ):
        return GuidanceActivationProposalForm(
            data,
            operators=page.operators,
            initial={
                "expected_edition_version": page.edition_version,
                "idempotency_key": uuid4(),
            },
        )
    if isinstance(page, GuidanceActivationRequestView):
        initial = {"expected_version": page.version}
        if action == "answer" and (page.can_answer or request.method == "POST"):
            return GuidanceActivationAnswerForm(data, initial=initial)
        if action == "apply" and (page.can_apply or request.method == "POST"):
            return GuidanceActivationApplyForm(data, initial=initial)
    return None


def _post(
    actor: RequestActor,
    page: GuidanceActivationStart
    | GuidanceActivationRequestView
    | tuple[GuidanceActivationRequestView, ...],
    form: forms.Form,
) -> tuple[str | None, int]:
    if not form.is_valid():
        return None, 400
    data = form.cleaned_data
    try:
        if isinstance(page, GuidanceActivationStart) and isinstance(
            form, GuidanceActivationProposalForm
        ):
            result = commands.propose_guidance_activation(
                actor=actor,
                organization_id=page.organization_id,
                edition_id=page.edition_id,
                expected_edition_version=data["expected_edition_version"],
                operator_ids=form.operator_ids(),
                reason=data["reason"],
                idempotency_key=data["idempotency_key"],
                correlation_id=uuid4(),
            )
            return _request_url(result.request_id), 200
        if isinstance(page, GuidanceActivationRequestView):
            if isinstance(form, GuidanceActivationAnswerForm):
                commands.respond_to_guidance_activation(
                    actor=actor,
                    request_id=page.request_id,
                    expected_version=data["expected_version"],
                    accept=data["decision"] == "accept",
                    correlation_id=uuid4(),
                )
            elif isinstance(form, GuidanceActivationApplyForm):
                commands.apply_guidance_activation(
                    actor=actor,
                    request_id=page.request_id,
                    expected_version=data["expected_version"],
                    correlation_id=uuid4(),
                )
            else:
                _deny()
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
def guidance_activation_workspace(
    request: HttpRequest,
    *,
    action: str = "tasks",
    organization_id: UUID | None = None,
    edition_id: UUID | None = None,
    request_id: UUID | None = None,
) -> HttpResponse:
    """Present an exact proposal or actual person's decision without granting access.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated participant and original form values.
    action : str, default='tasks'
        Closed route-owned task, never a submitted action selector.
    organization_id : UUID | None, default=None
        Exact organization from the platform setup route for a new proposal.
    edition_id : UUID | None, default=None
        Same-parent event from the platform setup route for a new proposal.
    request_id : UUID | None, default=None
        Exact immutable proposal locator for participant decisions.

    Returns
    -------
    HttpResponse
        Rechecked full page, exact result redirect or non-disclosing failure.
    """
    try:
        actor = authenticated_request_actor(request)
        load: Callable[
            [],
            GuidanceActivationStart
            | GuidanceActivationRequestView
            | tuple[GuidanceActivationRequestView, ...],
        ]
        if action == "start" and organization_id is not None and edition_id is not None:
            load = partial(
                load_guidance_activation_start,
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=uuid4(),
            )
        elif action == "tasks":
            load = partial(
                list_my_guidance_activation_requests,
                actor=actor,
                correlation_id=uuid4(),
            )
        elif action in {"detail", "answer", "apply"} and request_id is not None:
            load = partial(
                load_guidance_activation_request,
                actor=actor,
                request_id=request_id,
                correlation_id=uuid4(),
            )
        else:
            _deny()
        page = load()
        _input(request, writable=action in {"start", "answer", "apply"})
        form = _form(request, action, page)
        status = 200
        if request.method == "POST":
            if form is None:
                _deny()
            destination, status = _post(actor, page, form)
            if destination:
                return _secure(HttpResponseRedirect(destination))
        nonce = token_urlsafe(32)
        start = page if isinstance(page, GuidanceActivationStart) else None
        proposal = page if isinstance(page, GuidanceActivationRequestView) else None
        scope = start or proposal
        content_url = _content_url(actor, scope)
        title = {
            "start": "Set up Guides",
            "tasks": "Your Guides setup decisions",
            "detail": "Guides setup request",
            "answer": "Decide about Guides responsibilities",
            "apply": "Apply Guides setup",
        }[action]
        context = dict(admin.site.each_context(request))
        context.update(
            title=title,
            action=action,
            form=form,
            start=start,
            proposal=proposal,
            content_url=content_url,
            has_permission=True,
            maru_csp_nonce=nonce,
            scope_label=f"{scope.organization_name} / {scope.edition_name}"
            if scope
            else "",
            maru_page_access_spec=fixed_page_access(
                policy="platform" if actor.is_platform_administrator else "fixed",
                scope_label="Guides setup decisions",
                explanation=(
                    "Only the platform administrator who requested setup and the "
                    "two named responsible people can review this request. Each "
                    "person makes their own decision; no access is granted until "
                    "the accepted setup is applied."
                ),
            ),
            tasks_url=reverse("guidance-activation-tasks"),
            representation_url=reverse(
                "organization-representation",
                kwargs={"organization_slug": scope.organization_slug},
            )
            if scope
            else "",
            request_url=_request_url(proposal.request_id) if proposal else "",
            answer_url=_request_url(proposal.request_id, "answer") if proposal else "",
            apply_url=_request_url(proposal.request_id, "apply") if proposal else "",
            task_rows=tuple(
                (item, _request_url(item.request_id), _STATES[item.state])
                for item in page
            )
            if isinstance(page, tuple)
            else (),
            state_label=_STATES.get(proposal.state, "Unavailable") if proposal else "",
            submit_label={
                "start": "Request this setup",
                "answer": "Save my decision",
                "apply": "Finish access setup",
            }.get(action, ""),
            baseline_hide_admin_scoped_navigation=True,
        )
        content = render_to_string(
            "events/guidance_activation.html", context, request=request
        )
        if load() != page or _content_url(actor, scope) != content_url:
            return _secure(
                HttpResponse(
                    (
                        "The event, request or your access changed. Reload before "
                        "continuing."
                    ),
                    status=409,
                ),
                nonce,
            )
        return _secure(HttpResponse(content, status=status), nonce)
    except PermissionDenied:
        return _secure(
            HttpResponse("This Guides setup decision is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Guides setup input.", status=400))
    except (ValidationError, DatabaseError, GuidanceError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
