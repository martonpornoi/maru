"""Dormant read-only domain viewers under the exact admitted review purpose."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_views import _secure
from .programme_decision_views import _UNAVAILABLE
from .programme_review_authorization import (
    DECIDE,
    MODERATE,
    REVIEW,
    authorize_programme_review_scope,
)
from .programme_review_domain_references import get_programme_review_domain_reference
from .programme_review_queries import ProgrammeReviewReadRequest
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from .programme_domain_references import ProgrammeDomainReferenceView

_PURPOSES = {"reviewer": REVIEW, "moderator": MODERATE, "decider": DECIDE}


def _return_allowed(scope: ProgrammeReviewReadRequest) -> bool:
    try:
        authorize_programme_review_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            capability_code=scope.capability_code,
            requested_fields=frozenset({"review_context"}),
        )
    except Denied:
        return False
    return True


def _page(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID | None,
    question_key: str,
    purpose: str,
) -> HttpResponse:
    def read() -> ProgrammeDomainReferenceView:
        return get_programme_review_domain_reference(
            request=scope,
            case_id=case_id,
            assignment_id=assignment_id,
            question_key=question_key,
        )

    view = read()
    back = (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/"
    )
    suffix = {
        "reviewer": f"mine/{case_id}/{assignment_id}/",
        "moderator": f"moderation/{case_id}/",
        "decider": f"decisions/{case_id}/",
    }
    allowed = _return_allowed(scope)
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        maru_csp_nonce=nonce,
        title="Programme domain reference",
        domain_view=view,
        purpose=purpose,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        return_url=back + suffix[purpose] + "answers/" if allowed else None,
    )
    content = render_to_string(
        "applications/programme_review_domain_reference.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    if read() != view or _return_allowed(scope) != allowed:
        raise Denied
    return _secure(HttpResponse(content), nonce)


def _transport(request: HttpRequest, purpose: str) -> None:
    if request.GET or request.POST or request.FILES or purpose not in _PURPOSES:
        raise ValueError


@login_required
@never_cache
@require_GET
def programme_review_domain_reference(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID,
    question_key: str,
    *,
    purpose: str,
    assignment_id: UUID | None = None,
) -> HttpResponse:
    """View a retained domain reference without granting another review role.

    Parameters
    ----------
    request : HttpRequest
        Authenticated read-only request with no query, body or file overrides.
    organization_id : UUID
        Exact expected organization.
    edition_id : UUID
        Exact expected edition.
    department_id : UUID
        Exact current owner Department, not authority.
    case_id : UUID
        Exact authorized current-seal case.
    question_key : str
        Bounded original question key, never a person identifier.
    purpose : str
        Code-owned reviewer, moderator or decider route purpose.
    assignment_id : UUID | None, default=None
        Exact own current assignment for reviewer purpose only.

    Returns
    -------
    HttpResponse
        Protected minimal label or generic invalid, denied or unavailable response.
    """
    try:
        _transport(request, purpose)
        scope = ProgrammeReviewReadRequest(
            UUID(str(request.user.pk)),
            organization_id,
            edition_id,
            department_id,
            _PURPOSES[purpose],
            frozenset({"review_answers"}),
            uuid4(),
            "programme-review-person",
        )
        return _page(request, scope, case_id, assignment_id, question_key, purpose)
    except Denied:
        return _secure(
            HttpResponse("This domain reference is unavailable.", status=404)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse("The review service is temporarily unavailable.", status=503)
        )
    except (ValueError, TypeError):
        return _secure(
            HttpResponse("Use the exact person-reference viewer request.", status=400)
        )
