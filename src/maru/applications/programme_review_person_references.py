"""Independently admitted exact-review-answer person viewers with anonymous omission."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from django.db import transaction

from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_person_references import (
    PERSON_REFERENCE_KIND,
    ProgrammePersonReferenceView,
    _view,
)
from .programme_review_authorization import DECIDE, MODERATE, REVIEW
from .programme_review_queries import (
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


def _source(
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> tuple[object, ...]:
    # The canonical answer query omits anonymous reference rows in SQL first.
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
    return detail, case.revision_id, case.policy_id, case.stage, assignment_id


@transaction.atomic
def get_programme_review_person_reference(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    question_key: str,
    assignment_id: UUID | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammePersonReferenceView:
    """Resolve an exact admitted nonanonymous answer, never a caller account identifier.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact reviewer, moderator or decider and review_answers-only field ceiling.
    case_id : UUID
        Exact current-revision case within the independently authorized Department.
    question_key : str
        Bounded immutable question key selected from the permitted answer task.
    assignment_id : UUID | None, default=None
        Exact own current assignment for a reviewer; absent for other roles.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Real policy or established isolated-test admission seam.

    Returns
    -------
    ProgrammePersonReferenceView
        Current minimized label and full source facts for final render comparison.

    Raises
    ------
    Denied
        If role, fields, assignment, source, type, kind or repeated admission fails.
    """
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
    source = _source(request, case_id, assignment_id, authorizer)
    detail = source[0]
    answers_json = getattr(detail, "answers_json", None)
    rows = json.loads(answers_json) if answers_json is not None else []
    selected = [row for row in rows if row.get("key") == question_key]
    if len(selected) != 1:
        raise Denied
    answer = selected[0]
    if (answer.get("type"), answer.get("reference_kind")) != (
        "person_reference",
        PERSON_REFERENCE_KIND,
    ):
        raise Denied
    result = _view(source, answer["label"], answer["value"])
    if _source(request, case_id, assignment_id, authorizer) != source:
        raise Denied
    _audit(request, "person_reference", case_id, authorizer)
    return result
