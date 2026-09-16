"""Read exact authorized Programme attachments without exposing storage references."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from . import programme_personal_queries as personal
from . import programme_queries as queries
from .models import ProgrammeFileContent, ProgrammeFileIntake
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_file_preparation import (
    MAX_PROGRAMME_FILE_BYTES,
    ProgrammeFileUnavailableError,
)
from .programme_inputs import require_programme_uuid
from .programme_personal_queries import _same_scope
from .programme_queries import _append_sensitive_read, _audit_inputs
from .programme_reference_sources import (
    ProgrammeAnswerReferenceRequest,
    _scope,
    _values,
)

if TYPE_CHECKING:
    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_FIELDS = frozenset({"proposal_summary", "answers"})
_FROZEN_FIELDS = frozenset({"proposal_summary", "frozen_revision"})


@dataclass(frozen=True, slots=True)
class ProgrammeFileProjection:
    """Return only minimized attachment facts and explicitly requested private bytes.

    Attributes
    ----------
    source : object
        Complete owner evidence for final response comparison; never render wholesale.
    question_label : str
        Independently authorized immutable question label.
    present : bool
        Whether this exact answer contains an admitted supporting file.
    size_bytes : int | None
        Bounded retained byte count, absent for an empty answer.
    data : bytes | None
        Integrity-checked bytes only for an explicit download; hidden from repr.
    """

    source: object = field(repr=False)
    question_label: str
    present: bool
    size_bytes: int | None
    data: bytes | None = field(repr=False)


def _metadata(
    *,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    value: object,
    answer_version: int | None,
) -> ProgrammeFileIntake:
    if not isinstance(value, str):
        raise Denied
    try:
        receipt_id = UUID(value)
    except ValueError as error:
        raise Denied from error
    if not receipt_id.int or str(receipt_id) != value:
        raise Denied
    if type(answer_version) is not int or answer_version <= 1:
        raise ProgrammeFileUnavailableError
    row = (
        ProgrammeFileIntake.objects.select_related("file_receipt")
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            question_id=question_id,
            file_receipt_id=receipt_id,
            source_version__lt=answer_version,
        )
        .first()
    )
    if row is None:
        raise ProgrammeFileUnavailableError
    receipt = row.file_receipt
    if (
        receipt.organization_id != organization_id
        or receipt.edition_id != edition_id
        or receipt.account_id != row.actor_id
        or receipt.status != "clean"
        or receipt.media_type != "application/pdf"
        or receipt.storage_key != f"programme-db/{row.id}"
        or receipt.scanner_receipt != "clamav-instream@1"
        or type(receipt.size_bytes) is not int
        or not 1 <= receipt.size_bytes <= MAX_PROGRAMME_FILE_BYTES
        or not isinstance(receipt.sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt.sha256) is None
    ):
        raise ProgrammeFileUnavailableError
    return row


def _bytes(intake: ProgrammeFileIntake) -> bytes:
    payload = (
        ProgrammeFileContent.objects.filter(
            intake_id=intake.id,
            intake__organization_id=intake.organization_id,
            intake__edition_id=intake.edition_id,
            intake__proposal_id=intake.proposal_id,
            intake__question_id=intake.question_id,
            intake__file_receipt_id=intake.file_receipt_id,
        )
        .values_list("payload", flat=True)
        .first()
    )
    if not isinstance(payload, (bytes, memoryview)):
        raise ProgrammeFileUnavailableError
    length = payload.nbytes if isinstance(payload, memoryview) else len(payload)
    if (
        length != intake.file_receipt.size_bytes
        or not 1 <= length <= MAX_PROGRAMME_FILE_BYTES
    ):
        raise ProgrammeFileUnavailableError
    data = bytes(payload)
    if not hmac.compare_digest(
        hashlib.sha256(data).hexdigest(), intake.file_receipt.sha256
    ):
        raise ProgrammeFileUnavailableError
    return data


def _projection(
    *,
    source: object,
    label: str,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    value: object,
    answer_version: int | None,
    include_bytes: bool,
) -> ProgrammeFileProjection:
    if value is None:
        if include_bytes:
            raise ProgrammeFileUnavailableError
        return ProgrammeFileProjection(
            source, label, present=False, size_bytes=None, data=None
        )
    intake = _metadata(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        question_id=question_id,
        value=value,
        answer_version=answer_version,
    )
    return ProgrammeFileProjection(
        source,
        label,
        present=True,
        size_bytes=intake.file_receipt.size_bytes,
        data=_bytes(intake) if include_bytes else None,
    )


def _self_source(
    request: ProgrammeAnswerReferenceRequest,
    revision_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> (
    queries.ProgrammeProposalDetailProjection | personal.ProgrammePersonalFrozenRevision
):
    values = _values(request)
    fields = _FIELDS if revision_id is None else _FROZEN_FIELDS
    admitted = _scope(request, authorizer, fields=fields)
    if revision_id is None:
        result = queries.get_self_programme_proposal_detail(
            **values, requested_fields=fields, authorizer=authorizer
        )
        if result.summary is None or result.requested_fields != fields:
            raise Denied
        _same_scope(result.summary, admitted)
        return result
    frozen = personal.get_self_programme_frozen_revision(
        **values, revision_id=revision_id, authorizer=authorizer
    )
    _same_scope(frozen.summary, admitted)
    if frozen.revision.revision_id != revision_id:
        raise Denied
    return frozen


@transaction.atomic
def get_self_programme_file(
    *,
    request: ProgrammeAnswerReferenceRequest,
    revision_id: UUID | None = None,
    include_bytes: bool = False,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeFileProjection:
    """Read only a current or exact-sealed file answer under independent authority.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Genuine contributor and exact proposal/question, never a receipt identifier.
    revision_id : UUID | None, default=None
        Exact current seal including the viewer, or the current shared answer.
    include_bytes : bool, default=False
        Explicit attachment read; metadata-only tasks never fetch the byte relation.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independently evaluated owner policy, not uploader or retry authority.

    Returns
    -------
    ProgrammeFileProjection
        Audited minimized facts and optional verified bytes with complete source proof.

    Raises
    ------
    Denied
        If exact answer, relationship, fields or repeated source admission fails.

    Notes
    -----
    Missing/corrupt custody is unavailable, never a generic media fallback. The
    transport must send attachment-only, no-store and nosniff responses and recheck
    source after response preparation. This query does not activate any route.
    """
    if (
        type(request) is not ProgrammeAnswerReferenceRequest
        or type(include_bytes) is not bool
    ):
        raise Denied
    if revision_id is not None:
        require_programme_uuid(revision_id, field="revision_id")
    original = _self_source(request, revision_id, authorizer)
    answers = tuple(
        row
        for row in original.answers or ()
        if row.question.question_id == request.question_id
    )
    if len(answers) != 1 or answers[0].question.field_type != "safe_file":
        raise Denied
    answer = answers[0]
    result = _projection(
        source=original,
        label=answer.question.label,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        proposal_id=request.proposal_id,
        question_id=request.question_id,
        value=answer.value,
        answer_version=answer.resulting_version,
        include_bytes=include_bytes,
    )
    if _self_source(request, revision_id, authorizer) != original:
        raise Denied
    correlation, channel = _audit_inputs(
        correlation_id=request.correlation_id, source_channel=request.source_channel
    )
    fields = _FIELDS if revision_id is None else _FROZEN_FIELDS
    _append_sensitive_read(
        scope=_scope(request, authorizer, fields=fields),
        operation=(
            "applications.programme.query.file_download"
            if include_bytes
            else "applications.programme.query.file_reference"
        ),
        target_id=request.proposal_id,
        correlation_id=correlation,
        source_channel=channel,
        occurred_at=timezone.now(),
    )
    return result
