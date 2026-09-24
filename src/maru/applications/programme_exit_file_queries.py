"""Archive-only exact retained review attachments through Applications custody."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_file_preparation import ProgrammeFileUnavailableError
from .programme_file_queries import _metadata, _projection
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import DECIDE
from .programme_review_file_queries import _answer_binding, _ReviewSource
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    _audit,
    get_programme_review_detail,
)
from .programme_review_rules import load_review_case

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_QUESTION_KEY = 80


@dataclass(frozen=True, slots=True)
class ProgrammeExitReviewFile:
    """One current-authorized retained file and explicit immutable source linkage.

    Attributes
    ----------
    file_id, case_id, revision_id, question_id
        Opaque owner identities, not file-directory or foreign read authority.
    question_key, answer_version
        Exact immutable answer key and its original resulting submission version.
    size_bytes, sha256
        Verified byte count and digest, not permanent disclosure permission.
    data
        Restricted original clean bytes; never included in repr or inline HTML.
    """

    file_id: UUID = field(repr=False)
    case_id: UUID = field(repr=False)
    revision_id: UUID = field(repr=False)
    question_id: UUID = field(repr=False)
    question_key: str = field(repr=False)
    answer_version: int
    size_bytes: int
    sha256: str = field(repr=False)
    data: bytes = field(repr=False)


def _source(
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> _ReviewSource:
    detail = get_programme_review_detail(
        request=request, case_id=case_id, authorizer=authorizer
    )
    case = load_review_case(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        case_id=case_id,
    )
    if (
        detail.case_id != case_id
        or detail.version != case.version
        or case.policy.stages[case.stage]["anonymous"]
    ):
        raise Denied
    return _ReviewSource(
        detail, case.revision_id, case.policy_id, case.stage, None, case.proposal_id
    )


@transaction.atomic
def load_programme_exit_review_file(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    question_key: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitReviewFile:
    """Read one archive-authorized historical attachment, never an arbitrary receipt.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Actual independent current decider and exact Department/answer field scope.
    case_id : UUID
        Exact retained case whose original sealed answer is still authorized today.
    question_key : str
        Explicit immutable allowed safe-file answer, never a submitted file UUID.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Ordinary source policy with its existing sealed test replacement guard.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional archive-purpose authority, independent of source access.

    Returns
    -------
    ProgrammeExitReviewFile
        Integrity-checked clean bytes and exact lineage, or no disclosed result.

    Raises
    ------
    Denied
        If request purpose, exact answer, anonymity or repeated source is unavailable.
    ProgrammeFileUnavailableError
        If there are no eligible bytes or final custody/integrity no longer agrees.

    Notes
    -----
    Ordinary browser readers retain their current-seal requirement. This distinct
    extra-purpose reader admits only an original case history still readable by
    the current independent decider; it never impersonates the original reviewer
    or uploader. Both paths share actual custody validation, clean state, quotas
    and byte verification. Anonymous/withheld answers cause no custody lookup.
    """
    require_programme_uuid(case_id, field="case_id")
    if (
        type(request) is not ProgrammeReviewReadRequest
        or request.capability_code != DECIDE
        or request.department_id is None
        or request.requested_fields != frozenset({"review_answers"})
        or type(question_key) is not str
        or len(question_key) > _MAX_QUESTION_KEY
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", question_key) is None
    ):
        raise Denied

    def purpose() -> None:
        authorize_programme_archive_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    purpose()
    source = _source(request, case_id, authorizer)
    try:
        rows = json.loads(source.detail.answers_json or "[]")
    except (TypeError, ValueError) as error:
        raise Denied from error
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise Denied
    answers = [row for row in rows if row.get("key") == question_key]
    if (
        len(answers) != 1
        or answers[0].get("type") != "safe_file"
        or answers[0].get("classification") not in {"C1", "C2", "C3"}
        or "value" not in answers[0]
        or type(answers[0].get("label")) is not str
    ):
        raise Denied
    answer = answers[0]
    if answer["value"] is None:
        raise ProgrammeFileUnavailableError
    question_id, answer_version = _answer_binding(
        request, source, question_key, answer["value"]
    )
    arguments = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "proposal_id": source.proposal_id,
        "question_id": question_id,
        "value": answer["value"],
        "answer_version": answer_version,
    }
    projection = _projection(
        source=source, label=answer["label"], include_bytes=True, **arguments
    )
    if projection.data is None or projection.size_bytes != len(projection.data):
        raise ProgrammeFileUnavailableError
    digest = hashlib.sha256(projection.data).hexdigest()
    purpose()
    if _source(request, case_id, authorizer) != source:
        raise Denied
    current = _metadata(**arguments)
    if current.file_receipt.size_bytes != len(
        projection.data
    ) or not hmac.compare_digest(current.file_receipt.sha256, digest):
        raise ProgrammeFileUnavailableError
    _audit(request, "exit_file", case_id, authorizer)
    return ProgrammeExitReviewFile(
        UUID(answer["value"]),
        case_id,
        source.revision_id,
        question_id,
        question_key,
        answer_version,
        len(projection.data),
        digest,
        projection.data,
    )
