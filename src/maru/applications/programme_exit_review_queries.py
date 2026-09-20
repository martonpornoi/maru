"""Collect complete private case evidence without widening the ordinary review DTO."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from django.db import transaction

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .models import ProgrammeReviewEntry
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_decider_queries import DecisionMessage, list_programme_decision_messages
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import DECIDE, REVIEW_FIELDS
from .programme_review_queries import (
    ProgrammeReviewDetail,
    ProgrammeReviewReadRequest,
    _audit,
    _locked_scope,
    get_programme_review_detail,
)
from .programme_review_rules import ProgrammeReviewUnavailableError, load_review_case

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer

    from .programme_authorization import ApplicationsProgrammeAuthorizer

MAX_EXIT_REVIEW_ENTRIES: Final = 20_000
_PAGE_SIZE: Final = 100
_DEFAULT: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammeExitReviewCase:
    """Explicit authorized source links and complete ordinary-ceiling case history.

    Attributes
    ----------
    case_id, version
        Exact reviewed case and fixed inclusive evidence ceiling.
    proposal_id, revision_id, policy_id, call_id, department_id
        Archive-purpose original source references, not foreign read authority.
    context_json, answers_json, evidence_json
        Existing source-authorized projections; evidence joins every page in
        original version order. Anonymous and stage withholding remain unchanged.
    evidence_lineage
        Immutable entry ID, original version and server timestamp for each entry.
        Invitation secrets, retry keys and unrelated proposal data are absent.
    decisions
        Complete decider-authorized outgoing messages; no recipient directory or
        additional receipt-state disclosure is introduced.
    """

    case_id: UUID = field(repr=False)
    version: int
    proposal_id: UUID = field(repr=False)
    revision_id: UUID = field(repr=False)
    policy_id: UUID = field(repr=False)
    call_id: UUID = field(repr=False)
    department_id: UUID = field(repr=False)
    context_json: str = field(repr=False)
    answers_json: str = field(repr=False)
    evidence_json: str = field(repr=False)
    evidence_lineage: tuple[tuple[UUID, int, datetime], ...] = field(repr=False)
    decisions: tuple[DecisionMessage, ...] = field(repr=False)


def _evidence_page(
    page: ProgrammeReviewDetail, after: int, through: int
) -> list[dict[str, object]]:
    if page.version != through or page.evidence_json is None:
        raise ProgrammeReviewUnavailableError
    try:
        entries = json.loads(page.evidence_json)
    except (ValueError, TypeError):
        raise ProgrammeReviewUnavailableError from None
    expected = min(through - after, _PAGE_SIZE)
    if (
        type(entries) is not list
        or len(entries) != expected
        or any(
            type(row) is not dict
            or type(row.get("version")) is not int
            or row["version"] != after + index + 1
            for index, row in enumerate(entries)
        )
        or page.next_evidence_version
        != (after + expected if after + expected < through else None)
    ):
        raise ProgrammeReviewUnavailableError
    return entries


def _messages(
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    version: int,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> tuple[DecisionMessage, ...]:
    result: list[DecisionMessage] = []
    after = 0
    identifiers = set()
    while True:
        page = list_programme_decision_messages(
            request=request,
            case_id=case_id,
            after_version=after,
            limit=_PAGE_SIZE,
            authorizer=authorizer,
        )
        if page.version != version or len(page.items) > _PAGE_SIZE:
            raise ProgrammeReviewUnavailableError
        for item in page.items:
            if (
                type(item.version) is not int
                or not after < item.version <= version
                or item.decision_id in identifiers
                or len(result) >= MAX_EXIT_REVIEW_ENTRIES
            ):
                raise ProgrammeReviewUnavailableError
            identifiers.add(item.decision_id)
            after = item.version
            result.append(item)
        if page.next_version is None:
            return tuple(result)
        if len(page.items) != _PAGE_SIZE or page.next_version != after:
            raise ProgrammeReviewUnavailableError


@transaction.atomic
def load_programme_exit_review_case(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitReviewCase:
    """Collect one exact case completely under independent archive and decider rights.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Actual independent decider, exact Department and all three review fields.
    case_id : UUID
        Known case in that scope; no inventory discovery is performed here.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Existing source policy and its sealed isolated-test replacement guard.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent additional archive-purpose policy, never source authority.

    Returns
    -------
    ProgrammeExitReviewCase
        Fixed-source, contiguous evidence with explicit lineage, or no projection.

    Raises
    ------
    Denied
        If the request lacks the exact independent decider purpose and fields.
    ProgrammeReviewUnavailableError
        If source, classification, complete bounds or retained evidence disagree.

    Notes
    -----
    Calls the ordinary source reader, including independence, sensitive answers
    and anonymous SQL omissions. It does not read files or private drafts. The
    outer owner transaction retains the canonical scope while paging; the full
    archive must establish its wider lock closure before invoking this component.
    """
    require_programme_uuid(case_id, field="case_id")
    if (
        type(request) is not ProgrammeReviewReadRequest
        or request.capability_code != DECIDE
        or request.requested_fields != REVIEW_FIELDS
        or request.department_id is None
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
    _locked_scope(request, authorizer)
    first = get_programme_review_detail(
        request=request, case_id=case_id, limit=_PAGE_SIZE, authorizer=authorizer
    )
    if (
        first.case_id != case_id
        or type(first.version) is not int
        or not 1 <= first.version <= MAX_EXIT_REVIEW_ENTRIES
        or first.context_json is None
        or first.answers_json is None
    ):
        raise ProgrammeReviewUnavailableError
    try:
        answers = json.loads(first.answers_json)
    except (ValueError, TypeError):
        raise ProgrammeReviewUnavailableError from None
    if type(answers) is not list or any(
        type(row) is not dict or row.get("classification") not in {"C1", "C2", "C3"}
        for row in answers
    ):
        raise ProgrammeReviewUnavailableError
    entries = _evidence_page(first, 0, first.version)
    evidence_request = replace(request, requested_fields=frozenset({"review_evidence"}))
    while len(entries) < first.version:
        page = get_programme_review_detail(
            request=evidence_request,
            case_id=case_id,
            after_version=len(entries),
            limit=_PAGE_SIZE,
            authorizer=authorizer,
        )
        if page.case_id != case_id:
            raise ProgrammeReviewUnavailableError
        entries.extend(_evidence_page(page, len(entries), first.version))
    case = load_review_case(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        case_id=case_id,
    )
    lineage = tuple(
        ProgrammeReviewEntry.objects.filter(
            case_id=case_id,
            case__proposal__organization_id=request.organization_id,
            case__proposal__edition_id=request.edition_id,
            case__revision__organization_id=request.organization_id,
            case__revision__edition_id=request.edition_id,
        )
        .order_by("version")
        .values_list("id", "version", "created_at")[: MAX_EXIT_REVIEW_ENTRIES + 1]
    )
    if (
        case.version != first.version
        or len(lineage) != first.version
        or any(row[1] != index + 1 for index, row in enumerate(lineage))
    ):
        raise ProgrammeReviewUnavailableError
    decisions = _messages(evidence_request, case_id, first.version, authorizer)
    final = get_programme_review_detail(
        request=request,
        case_id=case_id,
        after_version=first.version,
        limit=_PAGE_SIZE,
        authorizer=authorizer,
    )
    if (
        final.case_id != case_id
        or final.version != first.version
        or final.context_json != first.context_json
        or final.answers_json != first.answers_json
        or final.evidence_json != "[]"
        or final.next_evidence_version is not None
    ):
        raise ProgrammeReviewUnavailableError
    purpose()
    result = ProgrammeExitReviewCase(
        case_id,
        first.version,
        case.proposal_id,
        case.revision_id,
        case.policy_id,
        case.proposal.call_id,
        request.department_id,
        first.context_json,
        first.answers_json,
        json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        lineage,
        decisions,
    )
    _audit(request, "exit_case", case_id, authorizer)
    return result
