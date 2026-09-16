"""CSRF-protected raw upload and body-free result transport, never multipart intake."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from . import programme_file_commands as commands
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_views import _secure
from .programme_file_forms import _decode
from .programme_file_preparation import (
    MAX_PROGRAMME_FILE_BYTES,
    ProgrammeFileRejectedError,
    ProgrammeFileUnavailableError,
)
from .programme_proposal_views import _CONFLICTS, _UNAVAILABLE
from .programme_reference_sources import ProgrammeAnswerReferenceRequest

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-file-upload"
_INTENT_HEADER = "X-Maru-File-Intent"
_MAX_LENGTH_DIGITS = 10


def _source_request(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
) -> ProgrammeAnswerReferenceRequest:
    return ProgrammeAnswerReferenceRequest(
        UUID(str(request.user.pk)),
        organization_id,
        edition_id,
        proposal_id,
        question_id,
        uuid4(),
        _SOURCE,
    )


def _transport(request: HttpRequest) -> int:
    if request.META.get("QUERY_STRING", "") or request.headers.get("Content-Encoding"):
        raise ValueError
    raw_length = request.META.get("CONTENT_LENGTH", "")
    if request.method == "GET":
        if raw_length not in ("", "0"):
            raise ValueError
        return 0
    if (
        request.content_type != "application/pdf"
        or request.content_params
        or not isinstance(raw_length, str)
        or not raw_length.isascii()
        or not raw_length.isdecimal()
        or len(raw_length) > _MAX_LENGTH_DIGITS
    ):
        raise ValueError
    length = int(raw_length)
    if not 1 <= length <= MAX_PROGRAMME_FILE_BYTES:
        raise ProgrammeFileRejectedError
    return length


def _body_reader(request: HttpRequest, expected_length: int) -> Callable[[], bytes]:
    def read() -> bytes:
        data = request.read(MAX_PROGRAMME_FILE_BYTES + 1)
        if len(data) != expected_length or len(data) > MAX_PROGRAMME_FILE_BYTES:
            raise ProgrammeFileRejectedError
        return data

    return read


def _json(state: str, message: str, *, status: int = 200) -> HttpResponse:
    return _secure(JsonResponse({"state": state, "message": message}, status=status))


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "PUT"])
@transaction.non_atomic_requests
def programme_file_intake(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
) -> HttpResponse:
    """Receive one raw PDF only after owning admission, or check its original result.

    Parameters
    ----------
    request : HttpRequest
        Normal CSRF-protected PUT or body-free GET with a bounded signed intent header.
    organization_id : UUID
        Exact expected organization, not caller authority.
    edition_id : UUID
        Exact expected edition.
    proposal_id : UUID
        Original proposal retained in the purpose-bound intent.
    question_id : UUID
        Exact original safe-file question, never an arbitrary receipt.

    Returns
    -------
    HttpResponse
        No-store minimized saved/pending/unconfirmed JSON without private file metadata.

    Notes
    -----
    PUT lets ordinary CSRF middleware validate its header without parsing multipart
    file bytes. The command invokes the bounded reader only after current admission.
    Network/server buffering is outside this application boundary. A missing result
    is not proof that an earlier request cannot still complete; never auto-resend.
    """
    try:
        length = _transport(request)
        source = _source_request(
            request, organization_id, edition_id, proposal_id, question_id
        )
        intent = _decode(
            source, request.headers.get(_INTENT_HEADER, ""), purpose="upload"
        )
        if request.method == "GET":
            result = commands.get_programme_file_upload_result(
                request=source, intent=intent
            )
            if result is None:
                return _json(
                    "pending",
                    "No completed upload is currently recorded. An earlier request "
                    "may still be running. Check again or inspect authorized proposal "
                    "history before starting a new upload.",
                )
        else:
            commands.upload_and_use_programme_file(
                request=source, intent=intent, read_bytes=_body_reader(request, length)
            )
        return _json(
            "saved",
            "The original supporting file was saved as this answer. Current proposal "
            "and download access are checked independently.",
        )
    except Denied:
        message, status = (
            "This upload task is unavailable. Do not assume an earlier attempt "
            "failed; check authorized proposal history.",
            404,
        )
    except _CONFLICTS:
        message, status = (
            "The original upload intent conflicts with current state or a previous "
            "attempt. Check its previous result and proposal history; do not "
            "automatically resend the file.",
            409,
        )
    except ProgrammeFileRejectedError:
        message, status = (
            "The PDF could not be accepted. Use one supported PDF of at most "
            "10 MiB. Preserve the original intent when checking a previous result.",
            400,
        )
    except (*_UNAVAILABLE, ProgrammeFileUnavailableError, OSError):
        message, status = (
            "Supporting-file handling is unavailable. An earlier attempt may have "
            "committed; check the original result before starting a new upload.",
            503,
        )
    except (ValueError, TypeError, ValidationError):
        message, status = (
            "Use the complete original file task with one bounded raw PDF and "
            "its original intent.",
            400,
        )
    return _json("unconfirmed", message, status=status)
