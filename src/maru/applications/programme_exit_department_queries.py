"""Complete declared reviewed-proposal archive scope for one exact Department."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from django.db import transaction

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from .programme_exit_configuration_queries import (
    ProgrammeExitConfiguration,
    load_programme_exit_configuration,
)
from .programme_exit_file_queries import (
    ProgrammeExitReviewFile,
    load_programme_exit_review_file,
)
from .programme_exit_review_queries import (
    ProgrammeExitReviewCase,
    load_programme_exit_review_case,
)
from .programme_review_authorization import DECIDE, MANAGE_REVIEW, REVIEW_FIELDS
from .programme_review_queries import (
    ProgrammeReviewCaseSummary,
    ProgrammeReviewReadRequest,
    _audit,
    _locked_scope,
    list_programme_review_cases,
)
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

    from .programme_authorization import ApplicationsProgrammeAuthorizer

MAX_EXIT_CASES: Final = 2_000
MAX_EXIT_ENTRIES: Final = 100_000
MAX_EXIT_FILES: Final = 1_000
MAX_EXIT_FILE_BYTES: Final = 268_435_456
_PAGE_SIZE = 100
_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammeExitCaseBundle:
    """One completely authorized review and exact disclosed answer/file bindings.

    Attributes
    ----------
    review, files
        Complete retained case and each currently disclosed nonempty attachment.
        Anonymous and stage-withheld answers are not looked up or reconstructed.
    """

    review: ProgrammeExitReviewCase = field(repr=False)
    files: tuple[ProgrammeExitReviewFile, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProgrammeExitDepartment:
    """Complete declared configuration and reviewed-proposal scope, not drafts.

    Attributes
    ----------
    configuration, cases
        Independently authorized owner projections for one exact Department.
        Every retained case must be readable; denial never becomes omission.
    """

    configuration: ProgrammeExitConfiguration = field(repr=False)
    cases: tuple[ProgrammeExitCaseBundle, ...] = field(repr=False)


def _inventory(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> tuple[ProgrammeReviewCaseSummary, ...]:
    manager = replace(
        request,
        capability_code=MANAGE_REVIEW,
        requested_fields=frozenset({"review_context"}),
    )
    rows: list[ProgrammeReviewCaseSummary] = []
    cursor = None
    while True:
        page = list_programme_review_cases(
            request=manager, after_id=cursor, limit=_PAGE_SIZE, authorizer=authorizer
        )
        if len(page.items) > _PAGE_SIZE or len(rows) + len(page.items) > MAX_EXIT_CASES:
            raise ProgrammeReviewUnavailableError
        for item in page.items:
            if cursor is not None and item.case_id <= cursor:
                raise ProgrammeReviewUnavailableError
            cursor = item.case_id
            rows.append(item)
        if page.next_cursor is None:
            return tuple(rows)
        if (
            not page.items
            or len(page.items) != _PAGE_SIZE
            or page.next_cursor != cursor
        ):
            raise ProgrammeReviewUnavailableError


@transaction.atomic
def load_programme_exit_department(
    *,
    request: ProgrammeReviewReadRequest,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitDepartment:
    """Collect every retained case without widening any source or file ceiling.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department independent-decider purpose and all review fields.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Actual source policy; manager/setup and call permissions are also required.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional explicit bulk purpose, separate from every source decision.

    Returns
    -------
    ProgrammeExitDepartment
        Complete declared reviewed-proposal scope with explicit private exclusions.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the request or any mandatory source is denied.
    ProgrammeReviewUnavailableError
        If collection bounds, complete paging or selected source consistency fails.

    Notes
    -----
    The full archive must prelock its complete Department/person closure before
    this component. The exact Department lock serializes its source writes while
    paging. Private unreviewed proposals and withheld identifying answers are
    deliberately outside this source contract, never discovered through an ORM
    dump or by impersonating the lead. Any required reviewed case/file failure
    propagates and leaves no successful partial result.
    """
    if (
        type(request) is not ProgrammeReviewReadRequest
        or request.capability_code != DECIDE
        or request.requested_fields != REVIEW_FIELDS
        or request.department_id is None
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError

    def purpose() -> None:
        authorize_programme_archive_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    purpose()
    _locked_scope(request, authorizer)
    configuration = load_programme_exit_configuration(
        request=replace(
            request,
            capability_code=MANAGE_REVIEW,
            requested_fields=frozenset({"review_setup"}),
        ),
        authorizer=authorizer,
        programme_authorizer=programme_authorizer,
    )
    if configuration.department_id != request.department_id:
        raise ProgrammeReviewUnavailableError
    inventory = _inventory(request, authorizer)
    calls = {call.configuration.summary.call_id for call in configuration.calls}
    cases = []
    entry_count = file_count = byte_count = 0
    for summary in inventory:
        review = load_programme_exit_review_case(
            request=request,
            case_id=summary.case_id,
            authorizer=authorizer,
            programme_authorizer=programme_authorizer,
        )
        if (
            review.case_id != summary.case_id
            or review.version != summary.version
            or review.department_id != request.department_id
            or review.call_id not in calls
        ):
            raise ProgrammeReviewUnavailableError
        entry_count += len(review.evidence_lineage)
        if entry_count > MAX_EXIT_ENTRIES:
            raise ProgrammeReviewUnavailableError
        attachments = []
        for answer in json.loads(review.answers_json):
            if answer["type"] != "safe_file" or answer["value"] is None:
                continue
            file_count += 1
            if file_count > MAX_EXIT_FILES:
                raise ProgrammeReviewUnavailableError
            attachment = load_programme_exit_review_file(
                request=replace(
                    request, requested_fields=frozenset({"review_answers"})
                ),
                case_id=review.case_id,
                question_key=answer["key"],
                authorizer=authorizer,
                programme_authorizer=programme_authorizer,
            )
            if (
                attachment.case_id != review.case_id
                or attachment.revision_id != review.revision_id
                or attachment.question_key != answer["key"]
                or str(attachment.file_id) != answer["value"]
                or attachment.size_bytes != len(attachment.data)
            ):
                raise ProgrammeReviewUnavailableError
            byte_count += len(attachment.data)
            if byte_count > MAX_EXIT_FILE_BYTES:
                raise ProgrammeReviewUnavailableError
            attachments.append(attachment)
        cases.append(ProgrammeExitCaseBundle(review, tuple(attachments)))
    if _inventory(request, authorizer) != inventory:
        raise ProgrammeReviewUnavailableError
    purpose()
    _audit(request, "exit_department", request.department_id, authorizer)
    return ProgrammeExitDepartment(configuration, tuple(cases))
