"""Private exact-answer metadata and attachments, never inline PDF rendering."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_views import _secure
from .programme_file_preparation import ProgrammeFileUnavailableError
from .programme_file_queries import ProgrammeFileProjection, get_self_programme_file
from .programme_file_transport import _source_request
from .programme_proposal_views import _UNAVAILABLE, _html, _root, _Scope

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


def _attachment(
    read_bytes: Callable[[], ProgrammeFileProjection],
    read_metadata: Callable[[], ProgrammeFileProjection],
) -> HttpResponse:
    view = read_bytes()
    if not view.present or view.data is None:
        raise ProgrammeFileUnavailableError
    response = _secure(HttpResponse(view.data, content_type="application/pdf"))
    response["Content-Disposition"] = (
        'attachment; filename="programme-supporting-file.pdf"'
    )
    response["Content-Length"] = str(len(view.data))
    if read_metadata() != replace(view, data=None):
        raise Denied
    return response


def _unchanged(
    current: ProgrammeFileProjection, expected: ProgrammeFileProjection
) -> None:
    if current != expected:
        raise Denied


def _read_transport(request: HttpRequest) -> None:
    if (
        request.META.get("QUERY_STRING", "")
        or request.META.get("CONTENT_LENGTH", "") not in ("", "0")
        or request.headers.get("Content-Encoding")
    ):
        raise ValueError


@login_required
@never_cache
@require_GET
def programme_file_view(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    *,
    revision_id: UUID | None = None,
    download: bool = False,
) -> HttpResponse:
    """View or explicitly download an independently authorized exact file answer.

    Parameters
    ----------
    request : HttpRequest
        Authenticated body-free request.
    organization_id : UUID
        Exact expected organization, not authority.
    edition_id : UUID
        Exact event edition.
    proposal_id : UUID
        Relationship-owned proposal.
    question_id : UUID
        Exact safe-file question, never a file identifier.
    revision_id : UUID | None, default=None
        Optional exact current seal.
    download : bool, default=False
        Code-owned route purpose for explicit attachment download.

    Returns
    -------
    HttpResponse
        No-store metadata or attachment, or minimized failure.
    """
    try:
        _read_transport(request)
        source = _source_request(
            request, organization_id, edition_id, proposal_id, question_id
        )

        def read(*, include_bytes: bool = False) -> ProgrammeFileProjection:
            return get_self_programme_file(
                request=source, revision_id=revision_id, include_bytes=include_bytes
            )

        if download:
            return _attachment(lambda: read(include_bytes=True), read)
        view = read()

        def verify() -> None:
            _unchanged(read(), view)

        scope = _Scope(
            source.actor_id, organization_id, edition_id, source.correlation_id
        )
        return _html(
            request,
            scope,
            {
                "task": "file",
                "file_view": view,
                "question_label": view.question_label,
                "download_url": request.path + "download/",
                "proposal_url": f"{_root(scope)}{proposal_id}/work/",
            },
            verify,
        )
    except Denied:
        return _secure(HttpResponse("This supporting file is unavailable.", status=404))
    except (*_UNAVAILABLE, ProgrammeFileUnavailableError):
        return _secure(
            HttpResponse(
                "Supporting-file handling is temporarily unavailable.", status=503
            )
        )
    except (ValueError, TypeError):
        return _secure(
            HttpResponse("Use the exact supporting-file viewer request.", status=400)
        )
