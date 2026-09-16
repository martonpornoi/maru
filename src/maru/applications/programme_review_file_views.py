"""Exact-purpose private file metadata and attachments for independent review roles."""

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
from .programme_file_preparation import ProgrammeFileUnavailableError
from .programme_file_views import _attachment, _read_transport
from .programme_review_domain_views import _PURPOSES, _return_allowed
from .programme_review_file_queries import get_programme_review_file
from .programme_review_queries import ProgrammeReviewReadRequest
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from .programme_file_queries import ProgrammeFileProjection


def _page(
    request: HttpRequest,
    scope: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID | None,
    question_key: str,
    purpose: str,
    *,
    download: bool,
) -> HttpResponse:
    def read(*, include_bytes: bool = False) -> ProgrammeFileProjection:
        return get_programme_review_file(
            request=scope,
            case_id=case_id,
            assignment_id=assignment_id,
            question_key=question_key,
            include_bytes=include_bytes,
        )

    if download:
        return _attachment(lambda: read(include_bytes=True), read)
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
        title="Programme supporting file",
        file_view=view,
        purpose=purpose,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
        download_url=request.path + "download/",
        return_url=back + suffix[purpose] + "answers/" if allowed else None,
    )
    content = render_to_string(
        "applications/programme_review_file.html", shell, request
    )
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeReviewUnavailableError
    if read() != view or _return_allowed(scope) != allowed:
        raise Denied
    return _secure(HttpResponse(content), nonce)


@login_required
@never_cache
@require_GET
def programme_review_file(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    case_id: UUID,
    question_key: str,
    *,
    purpose: str,
    assignment_id: UUID | None = None,
    download: bool = False,
) -> HttpResponse:
    """View or download only the exact independently admitted review answer.

    Parameters
    ----------
    request : HttpRequest
        Authenticated body-free request with no query overrides.
    organization_id : UUID
        Exact expected organization.
    edition_id : UUID
        Exact event edition.
    department_id : UUID
        Exact owner Department, not authority.
    case_id : UUID
        Exact current-seal case.
    question_key : str
        Bounded original allowed question key, not a file identifier.
    purpose : str
        Code-owned reviewer, moderator or decider route purpose.
    assignment_id : UUID | None, default=None
        Exact own assignment for reviewer purpose only.
    download : bool, default=False
        Code-owned explicit attachment route.

    Returns
    -------
    HttpResponse
        Protected metadata or attachment, or minimized failure.
    """
    try:
        _read_transport(request)
        scope = ProgrammeReviewReadRequest(
            UUID(str(request.user.pk)),
            organization_id,
            edition_id,
            department_id,
            _PURPOSES[purpose],
            frozenset({"review_answers"}),
            uuid4(),
            "programme-review-file",
        )
        return _page(
            request,
            scope,
            case_id,
            assignment_id,
            question_key,
            purpose,
            download=download,
        )
    except Denied:
        return _secure(HttpResponse("This supporting file is unavailable.", status=404))
    except (*_UNAVAILABLE, ProgrammeFileUnavailableError):
        return _secure(
            HttpResponse("Supporting-file handling is unavailable.", status=503)
        )
    except (ValueError, TypeError, KeyError):
        return _secure(
            HttpResponse("Use the exact supporting-file viewer request.", status=400)
        )
