"""Read exact nonanonymous review attachments under each independent role ceiling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from .models import ProgrammeProposalRevisionAnswer
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_file_preparation import ProgrammeFileUnavailableError
from .programme_file_queries import ProgrammeFileProjection, _projection
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import DECIDE, MODERATE, REVIEW
from .programme_review_queries import (
    ProgrammeReviewDetail,
    ProgrammeReviewReadRequest,
    _audit,
    _detail_assignment,
    _locked_scope,
    get_programme_review_detail,
)
from .programme_review_rules import load_review_case, revision_is_current

if TYPE_CHECKING:
    from uuid import UUID

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_QUESTION_KEY = 80


@dataclass(frozen=True, slots=True)
class _ReviewSource:
    detail: ProgrammeReviewDetail
    revision_id: UUID
    policy_id: UUID
    stage: int
    assignment_id: UUID | None
    proposal_id: UUID


def _source(
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> _ReviewSource:
    # Canonical anonymous answers are omitted in SQL before identifying lookup.
    detail = get_programme_review_detail(
        request=request, case_id=case_id, authorizer=authorizer
    )
    _locked_scope(request, authorizer)
    case = load_review_case(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        case_id=case_id,
    )
    assignment = _detail_assignment(request, case)
    if (
        detail.case_id != case_id
        or detail.version != case.version
        or not revision_is_current(case)
        or case.policy.stages[case.stage]["anonymous"]
        or (
            request.capability_code == REVIEW
            and (assignment is None or assignment.id != assignment_id)
        )
    ):
        raise Denied
    return _ReviewSource(
        detail,
        case.revision_id,
        case.policy_id,
        case.stage,
        assignment_id,
        case.proposal_id,
    )


def _answer_binding(
    request: ProgrammeReviewReadRequest,
    source: _ReviewSource,
    question_key: str,
    value: object,
) -> tuple[UUID, int]:
    row = (
        ProgrammeProposalRevisionAnswer.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            revision_id=source.revision_id,
            revision__proposal_id=source.proposal_id,
            question_key=question_key,
            question_type="safe_file",
            question__field_type="safe_file",
            question__key=question_key,
            question__definition__organization_id=request.organization_id,
            question__definition__edition_id=request.edition_id,
            answer_revision__value=value,
            answer_revision__submission__programme_proposal__id=source.proposal_id,
        )
        .values_list("question_id", "answer_revision__resulting_version")
        .first()
    )
    if row is None or type(row[1]) is not int:
        raise ProgrammeFileUnavailableError
    return row[0], row[1]


@transaction.atomic
def get_programme_review_file(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    question_key: str,
    assignment_id: UUID | None = None,
    include_bytes: bool = False,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeFileProjection:
    """Read an exact allowed sealed file, never an arbitrary receipt or anonymous file.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Reviewer, moderator or decider with the exact review_answers field ceiling.
    case_id : UUID
        Exact current-seal case within independently authorized Department scope.
    question_key : str
        Immutable stage-allowlisted safe-file answer key, not a file identifier.
    assignment_id : UUID | None, default=None
        Exact active own assignment for a reviewer; absent for other roles.
    include_bytes : bool, default=False
        Explicit integrity-checked attachment read instead of metadata only.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independently evaluated real policy or established isolated-test adapter.

    Returns
    -------
    ProgrammeFileProjection
        Audited minimized attachment facts and optional bytes with full source proof.

    Raises
    ------
    Denied
        If role, fields, anonymity, assignment, exact answer or repeated source fails.
    ProgrammeFileUnavailableError
        If a download is requested for an answer without a supporting file.

    Notes
    -----
    Omission/denial precedes custody lookup. Sensitive classifications use the
    canonical independent sensitive-review check. Missing/corrupt custody is
    unavailable; a prior upload or result receipt supplies no read authority.
    """
    if (
        type(request) is not ProgrammeReviewReadRequest
        or type(include_bytes) is not bool
    ):
        raise Denied
    require_programme_uuid(case_id, field="case_id")
    if assignment_id is not None:
        require_programme_uuid(assignment_id, field="assignment_id")
    if (
        request.capability_code not in {REVIEW, MODERATE, DECIDE}
        or request.requested_fields != frozenset({"review_answers"})
        or (request.capability_code == REVIEW) != (assignment_id is not None)
        or not isinstance(question_key, str)
        or len(question_key) > _MAX_QUESTION_KEY
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", question_key) is None
    ):
        raise Denied
    original = _source(request, case_id, assignment_id, authorizer)
    rows = json.loads(original.detail.answers_json or "[]")
    answers = [row for row in rows if row.get("key") == question_key]
    if len(answers) != 1 or answers[0].get("type") != "safe_file":
        raise Denied
    answer = answers[0]
    if answer["value"] is None:
        if include_bytes:
            raise ProgrammeFileUnavailableError
        result = ProgrammeFileProjection(
            original, answer["label"], present=False, size_bytes=None, data=None
        )
    else:
        question_id, answer_version = _answer_binding(
            request, original, question_key, answer["value"]
        )
        result = _projection(
            source=original,
            label=answer["label"],
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            proposal_id=original.proposal_id,
            question_id=question_id,
            value=answer["value"],
            answer_version=answer_version,
            include_bytes=include_bytes,
        )
    if _source(request, case_id, assignment_id, authorizer) != original:
        raise Denied
    _audit(
        request,
        "file_download" if include_bytes else "file_reference",
        case_id,
        authorizer,
    )
    return result
