"""Dormant exact-recipient Programme messages and deliberate own receipts."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django import forms
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.core.forms import StrictBase10IntegerField

from . import programme_review_queries as queries
from .forms import RetryForm
from .models import ProgrammeReviewAction
from .programme_authorization import (
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_proposal_scope,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_commands import ApplicationsProgrammeIdempotencyConflictError
from .programme_review_authorization import (
    ACKNOWLEDGE_SELF,
    VIEW_DECISION_SELF,
    authorize_programme_review_scope,
)
from .programme_review_commands import apply_programme_review_command
from .programme_review_inputs import ProgrammeReviewCommandInput
from .programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
)
from .programme_write_scope import ApplicationsProgrammeWriteScopeUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

_FIELDS = frozenset({"decision_message", "own_acknowledgement"})
_PROPOSAL_FIELDS = frozenset({"proposal_summary", "selection", "own_invitation"})
_SOURCE = "programme-decision-receipts"
_MAX_INPUT_LENGTH = 200
_UUID_LENGTH = 36
_OUTCOMES = {
    "accepted": "Accepted",
    "rejected": "Rejected",
    "waitlisted": "Wait-listed",
    "revision_requested": "Revision requested",
}
_UNAVAILABLE = (
    DatabaseError,
    ProgrammeReviewUnavailableError,
    ApplicationsProgrammeWriteScopeUnavailableError,
)
_CONFLICTS = (
    ProgrammeReviewConflictError,
    ApplicationsProgrammeIdempotencyConflictError,
)


class ProgrammeDecisionReceiptForm(RetryForm):
    """Confirm only personal receipt with the original exact case-version proof."""

    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput
    )
    confirm = forms.BooleanField(
        label="I confirm that I received this exact decision message",
        help_text="Receipt is not agreement, hosting consent or publication consent.",
    )


def _root(scope: queries.ProgrammeReviewReadRequest) -> str:
    return (
        f"/my/applications/programme/{scope.organization_id}/"
        f"{scope.edition_id}/decisions/"
    )


def _authorize(
    scope: queries.ProgrammeReviewReadRequest, *, write: bool = False
) -> None:
    authorize_programme_review_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=None,
        capability_code=ACKNOWLEDGE_SELF if write else VIEW_DECISION_SELF,
        requested_fields=frozenset() if write else scope.requested_fields,
    )


def _can_acknowledge(scope: queries.ProgrammeReviewReadRequest) -> bool:
    try:
        _authorize(scope, write=True)
    except ApplicationsProgrammeAuthorizationDeniedError:
        return False
    return True


def _cursor(request: HttpRequest, decision_id: UUID | None) -> UUID | None:
    if request.FILES or set(request.GET) - {"after"}:
        raise ValueError
    if decision_id is not None and request.GET:
        raise ValueError
    if request.method == "POST":
        if decision_id is None or request.GET:
            raise ValueError
        allowed = {*ProgrammeDecisionReceiptForm.base_fields, "csrfmiddlewaretoken"}
        if set(request.POST) - allowed:
            raise ValueError
        if any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
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
    if value != str(identifier) or identifier.int == 0:
        raise ValueError
    return identifier


def _html(
    request: HttpRequest,
    scope: queries.ProgrammeReviewReadRequest,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
    continuation: Callable[[], str | None] | None = None,
) -> HttpResponse:
    verify()
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_personal_surface=True,
        maru_csp_nonce=nonce,
        title="My Programme decisions",
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    shell.update(context)
    shell["source_url"] = continuation() if continuation is not None else None
    content = render_to_string("applications/programme_decisions.html", shell, request)
    if (
        shell["source_url"]
        and continuation is not None
        and continuation() != shell["source_url"]
    ):
        shell["source_url"] = None
        content = render_to_string(
            "applications/programme_decisions.html", shell, request
        )
    verify()
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    return _secure(HttpResponse(content, status=status), nonce)


def _history(
    request: HttpRequest, scope: queries.ProgrammeReviewReadRequest, cursor: UUID | None
) -> HttpResponse:
    page = queries.list_self_programme_decisions(request=scope, after_id=cursor)

    def verify() -> None:
        if (
            queries.list_self_programme_decisions(request=scope, after_id=cursor)
            != page
        ):
            raise ApplicationsProgrammeAuthorizationDeniedError

    return _html(
        request,
        scope,
        {"page": page, "rows": tuple((row, _label(row.outcome)) for row in page.items)},
        verify,
    )


def _label(outcome: str | None) -> str:
    if outcome not in _OUTCOMES:
        raise ProgrammeReviewUnavailableError
    return _OUTCOMES[outcome]


def _source_url(
    scope: queries.ProgrammeReviewReadRequest,
    source: queries.ProgrammeDecisionSource | None,
) -> str | None:
    if source is None:
        return None
    values: dict[str, Any] = {
        "actor_id": scope.actor_id,
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "proposal_id": source.proposal_id,
        "capability_code": APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    }
    try:
        admitted = authorize_programme_proposal_scope(
            **values, requested_fields=_PROPOSAL_FIELDS
        )
        fields = (
            _PROPOSAL_FIELDS
            if admitted.relationship == "invited"
            else _PROPOSAL_FIELDS | {"contributor_profiles"}
        )
        current = authorize_programme_proposal_scope(**values, requested_fields=fields)
        if (
            current.relationship != admitted.relationship
            or current.relationship not in {"lead", "collaborator", "invited"}
            or any(
                row.proposal_id != source.proposal_id or row.call_id != source.call_id
                for row in (admitted, current)
            )
        ):
            return None
    except (ApplicationsProgrammeAuthorizationDeniedError, *_UNAVAILABLE):
        return None
    return (
        f"/my/applications/programme/{scope.organization_id}/{scope.edition_id}/"
        f"{source.proposal_id}/"
    )


def _detail(
    request: HttpRequest, scope: queries.ProgrammeReviewReadRequest, decision_id: UUID
) -> HttpResponse:
    message = queries.get_self_programme_decision(
        request=scope, decision_id=decision_id
    )
    if message.decision_id != decision_id:
        raise ApplicationsProgrammeAuthorizationDeniedError
    writable = _can_acknowledge(scope)
    form = ProgrammeDecisionReceiptForm(
        request.POST if request.method == "POST" else None,
        initial={"retry_key": uuid4(), "expected_version": message.case_version},
    )
    status = 200
    if request.method == "POST":
        _authorize(scope, write=True)
        status = 400
        if form.is_valid():
            try:
                apply_programme_review_command(
                    actor_id=scope.actor_id,
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    department_id=None,
                    command=ProgrammeReviewCommandInput(
                        ProgrammeReviewAction.ACKNOWLEDGED,
                        message.case_id,
                        reference_id=message.decision_id,
                    ),
                    expected_version=form.cleaned_data["expected_version"],
                    retry_key=form.cleaned_data["retry_key"],
                    reason="",
                    correlation_id=scope.correlation_id,
                    source_channel=_SOURCE,
                )
            except ValidationError as error:
                _apply_errors(form, error)
            except _CONFLICTS:
                status = 409
                message = queries.get_self_programme_decision(
                    request=scope, decision_id=decision_id
                )
                form.add_error(
                    None,
                    "This receipt was not confirmed. The case or retry evidence "
                    "has changed. Inspect current history before deliberately "
                    "reloading; your original confirmation proof is retained.",
                )
            else:
                return _secure(HttpResponseRedirect(f"{_root(scope)}{decision_id}/"))

    def verify() -> None:
        current = queries.get_self_programme_decision(
            request=scope, decision_id=decision_id
        )
        if current != message or _can_acknowledge(scope) != writable:
            raise ApplicationsProgrammeAuthorizationDeniedError

    show_form = writable and (
        form.is_bound
        or (message.acknowledgement_required and not message.own_acknowledged)
    )
    return _html(
        request,
        scope,
        {
            "message": message,
            "outcome_label": _label(message.outcome),
            "form": form if show_form else None,
        },
        verify,
        status,
        continuation=lambda: _source_url(scope, message.source),
    )


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_decisions(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    decision_id: UUID | None = None,
) -> HttpResponse:
    """Read exact addressed decisions or explicitly record the caller's receipt.

    Parameters
    ----------
    request : HttpRequest
        Authenticated genuine-person request without scope or subject overrides.
    organization_id : UUID
        Exact owning organization from the reserved route.
    edition_id : UUID
        Exact edition from the reserved route.
    decision_id : UUID | None, default=None
        Exact selected addressed message, absent for paginated history.

    Returns
    -------
    HttpResponse
        Private history/detail, exact success redirect or a non-disclosing error.
    """
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        return _secure(
            HttpResponse("This decision workspace is unavailable.", status=404)
        )
    scope = queries.ProgrammeReviewReadRequest(
        actor_id,
        organization_id,
        edition_id,
        None,
        VIEW_DECISION_SELF,
        _FIELDS,
        uuid4(),
        _SOURCE,
    )
    try:
        _authorize(scope)
        cursor = _cursor(request, decision_id)
        return (
            _history(request, scope, cursor)
            if decision_id is None
            else _detail(request, scope, decision_id)
        )
    except ApplicationsProgrammeAuthorizationDeniedError:
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
