"""Dormant labelled exact-source case opening through the canonical review writer."""

from __future__ import annotations

from dataclasses import asdict
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

from . import programme_review_intake_queries as queries
from . import programme_review_setup_queries as setup
from .forms import RetryForm
from .models import ProgrammeReviewAction
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_decision_views import _CONFLICTS, _UNAVAILABLE
from .programme_review_authorization import MANAGE_REVIEW
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import MAX_REVIEW_REASON, ProgrammeReviewCommandInput
from .programme_review_queries import ProgrammeReviewReadRequest
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_review_setup_views import _authorize, _root, _summary

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-review-intake"
_UUID_LENGTH = 36
_MAX_INPUT_BYTES = 12_000


class ProgrammeReviewOpenForm(RetryForm):
    """Confirm one exact URL-bound seal and policy with original creation proof."""

    expected_version = StrictBase10IntegerField(
        min_value=0, max_value=0, widget=forms.HiddenInput
    )
    reason = forms.CharField(
        label="Reason for opening this review case",
        max_length=MAX_REVIEW_REASON,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="Open a case for this exact submitted revision using this policy",
        help_text="This does not assign reviewers, decide or create a Programme item.",
    )


def _cursor(request: HttpRequest, revision_id: UUID | None) -> UUID | None:
    if request.FILES or set(request.GET) - {"after"}:
        raise ValueError
    if revision_id is not None and request.GET:
        raise ValueError
    if request.method == "POST":
        if revision_id is None or request.GET:
            raise ValueError
        allowed = {*ProgrammeReviewOpenForm.base_fields, "csrfmiddlewaretoken"}
        if set(request.POST) - allowed or any(
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
        title="Open a Programme review case",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string(
        "applications/programme_review_intake.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _open(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    source: setup.ReviewSetupContext,
    policy: setup.ReviewSetupPolicy,
    revision_id: UUID,
) -> tuple[dict[str, Any], int]:
    selected = queries.get_programme_review_intake_seal(
        request=scope, call_id=source.call.call_id, revision_id=revision_id
    )
    form = ProgrammeReviewOpenForm(
        request.POST if request.method == "POST" else None,
        initial={"retry_key": uuid4(), "expected_version": 0},
    )
    status = 200
    result = None
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                result = apply_programme_review_command(
                    actor_id=scope.actor_id,
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    department_id=scope.department_id,
                    command=ProgrammeReviewCommandInput(
                        ProgrammeReviewAction.CASE_OPENED,
                        selected.seal.proposal_id,
                        policy_id=policy.policy_id,
                        reference_id=revision_id,
                    ),
                    expected_version=form.cleaned_data["expected_version"],
                    retry_key=form.cleaned_data["retry_key"],
                    reason=form.cleaned_data["reason"],
                    correlation_id=scope.correlation_id,
                    source_channel=_SOURCE,
                )
            except ValidationError as error:
                _apply_errors(form, error)
            except _CONFLICTS:
                status = 409
                form.add_error(
                    None,
                    "This case opening was not confirmed. The selected source or "
                    "retry evidence has changed. Your original seal, policy, "
                    "reason and retry proof are retained. Inspect current sources "
                    "before deliberately starting a different intent.",
                )
            except _UNAVAILABLE:
                status = 503
                form.add_error(
                    None,
                    "The case service is temporarily unavailable. Keep this exact "
                    "request and retry it after recovery; do not assume it failed "
                    "or silently select a different revision.",
                )
            else:
                status = 200
            selected = queries.get_programme_review_intake_seal(
                request=scope, call_id=source.call.call_id, revision_id=revision_id
            )
    return {
        "selected": selected,
        "result": result,
        "form": form
        if result is None
        and (form.is_bound or (selected.eligible and selected.writable))
        else None,
    }, status


def _workspace(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    call_id: UUID,
    version: int,
    revision_id: UUID | None,
    cursor: UUID | None,
) -> HttpResponse:
    source = setup.get_programme_review_setup(request=scope, call_id=call_id)
    policy = setup.get_programme_review_setup_policy(
        request=scope, call_id=call_id, version=version
    )
    context: dict[str, Any] = {
        "source": source,
        "policy": policy,
        "summary": _summary(asdict(policy.policy), source),
        "intake_url": f"{_root(scope)}{call_id}/policies/{version}/cases/",
    }
    status = 200
    if revision_id is None:
        context["page"] = queries.list_programme_review_intake_seals(
            request=scope, call_id=call_id, after_id=cursor
        )
    else:
        selected, status = _open(request, scope, source, policy, revision_id)
        context.update(selected)

    def verify() -> None:
        if setup.get_programme_review_setup(request=scope, call_id=call_id) != source:
            raise Denied
        if (
            setup.get_programme_review_setup_policy(
                request=scope, call_id=call_id, version=version
            )
            != policy
        ):
            raise Denied
        current = (
            queries.list_programme_review_intake_seals(
                request=scope, call_id=call_id, after_id=cursor
            )
            if revision_id is None
            else queries.get_programme_review_intake_seal(
                request=scope, call_id=call_id, revision_id=revision_id
            )
        )
        if current != context["page" if revision_id is None else "selected"]:
            raise Denied

    return _html(request, scope, context, verify, status)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_review_intake(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID,
    version: int,
    revision_id: UUID | None = None,
) -> HttpResponse:
    """Choose and confirm an exact submitted seal without proposal-content access.

    Parameters
    ----------
    request : HttpRequest
        Authenticated manager request with ordinary CSRF protection.
    organization_id : UUID
        Exact owning organization from the reserved route.
    edition_id : UUID
        Exact authorized edition.
    department_id : UUID
        Current call-owning Department, independently authorized.
    call_id : UUID
        Selected owning call.
    version : int
        Explicit immutable policy sequence, never implicitly rebased.
    revision_id : UUID | None, default=None
        Original selected seal, absent for the bounded source chooser.

    Returns
    -------
    HttpResponse
        Protected selection, owner receipt, retained-input recovery or safe error.
    """
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        return _secure(HttpResponse("This review task is unavailable.", status=404))
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
        cursor = _cursor(request, revision_id)
        return _workspace(request, scope, call_id, version, revision_id, cursor)
    except Denied:
        return _secure(HttpResponse("This review task is unavailable.", status=404))
    except (ValueError, ValidationError):
        return _secure(HttpResponse("Use the complete review request.", status=400))
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("The review service is temporarily unavailable.", status=503)
        )
