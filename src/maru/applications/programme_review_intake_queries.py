"""Audited exact-seal discovery for independently scoped review case opening."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F

from .models import (
    ProgrammeProposalCollaborator,
    ProgrammeProposalRevision,
    ProgrammeProposalState,
    ProgrammeReviewCase,
)
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from .programme_inputs import require_programme_uuid
from .programme_review_queries import ProgrammeReviewReadRequest, _audit, _limit
from .programme_review_rules import is_proposal_contributor
from .programme_review_setup_queries import _calls, _scope

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ReviewIntakeSeal:
    """Identify one retained seal without answers or contributor identities.

    Attributes
    ----------
    revision_id : UUID
        Exact immutable seal identifier.
    proposal_id : UUID
        Exact proposal reference used by the canonical case command.
    sequence : int
        Proposal-local immutable revision sequence.
    sealed_at : datetime
        Actual sealing timestamp, not record creation time.
    """

    revision_id: UUID
    proposal_id: UUID
    sequence: int
    sealed_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewIntakePage:
    """Carry a complete bounded page of currently eligible submitted seals.

    Attributes
    ----------
    items : tuple[ReviewIntakeSeal, ...]
        Content-free eligible targets, filtered before pagination.
    next_cursor : UUID | None
        Exclusive last identifier when another page exists.
    """

    items: tuple[ReviewIntakeSeal, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class ReviewIntakeSelection:
    """Retain the selected source independently of fresh-command eligibility.

    Attributes
    ----------
    seal : ReviewIntakeSeal
        Exact originally selected seal metadata.
    eligible : bool
        Current source and independence checks; never a mutation guarantee.
    opened : bool
        Whether this exact seal already has a review case; no case evidence.
    writable : bool
        Current edition planning state, without implying write authority.
    """

    seal: ReviewIntakeSeal
    eligible: bool
    opened: bool
    writable: bool


def _seals(
    request: ProgrammeReviewReadRequest, call_id: UUID
) -> QuerySet[ProgrammeProposalRevision]:
    return ProgrammeProposalRevision.objects.select_related(
        "proposal__submission"
    ).filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        proposal__organization_id=request.organization_id,
        proposal__edition_id=request.edition_id,
        proposal__call_id__in=_calls(request).filter(id=call_id).values("id"),
    )


def _summary(row: ProgrammeProposalRevision) -> ReviewIntakeSeal:
    return ReviewIntakeSeal(row.id, row.proposal_id, row.sequence, row.sealed_at)


@transaction.atomic
def list_programme_review_intake_seals(
    *,
    request: ProgrammeReviewReadRequest,
    call_id: UUID,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewIntakePage:
    """Select current submitted sources, excluding conflicts before pagination.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department manager requesting only review_setup.
    call_id : UUID
        Exact owning call selected from independently authorized configuration.
    after_id : UUID | None, default=None
        Exclusive ascending seal identifier.
    limit : int, default=50
        Complete page size from one through 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ReviewIntakePage
        Audited complete page without answers, identities or hidden totals.
    """
    require_programme_uuid(call_id, field="call_id")
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    _scope(request, authorizer)
    collaborators = ProgrammeProposalCollaborator.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        account_id=request.actor_id,
    ).values("proposal_id")
    query = (
        _seals(request, call_id)
        .filter(
            proposal__state=ProgrammeProposalState.SUBMITTED,
            id=F("proposal__submitted_revision_id"),
            proposal__sealed_revision_id=F("id"),
        )
        .exclude(proposal__submission__account_id=request.actor_id)
        .exclude(proposal_id__in=collaborators)
        .exclude(
            id__in=ProgrammeReviewCase.objects.filter(
                revision__organization_id=request.organization_id,
                revision__edition_id=request.edition_id,
            ).values("revision_id")
        )
    )
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ReviewIntakePage(
        tuple(_summary(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "intake_seals", call_id, authorizer)
    return result


@transaction.atomic
def get_programme_review_intake_seal(
    *,
    request: ProgrammeReviewReadRequest,
    call_id: UUID,
    revision_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewIntakeSelection:
    """Read exact retained metadata so uncertain retries reach the owner writer.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department manager requesting only review_setup.
    call_id : UUID
        Exact owning call, never inferred from a foreign source.
    revision_id : UUID
        Original selected immutable seal, including a subsequently displaced seal.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ReviewIntakeSelection
        Audited metadata and advisory eligibility without answers or case content.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the exact seal is absent from this currently authorized call scope.
    """
    require_programme_uuid(call_id, field="call_id")
    require_programme_uuid(revision_id, field="revision_id")
    scope = _scope(request, authorizer)
    row = _seals(request, call_id).filter(id=revision_id).first()
    if row is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    opened = ProgrammeReviewCase.objects.filter(revision_id=row.id).exists()
    proposal = row.proposal
    eligible = (
        proposal.state == ProgrammeProposalState.SUBMITTED
        and proposal.submitted_revision_id == row.id
        and proposal.sealed_revision_id == row.id
        and not opened
        and not is_proposal_contributor(proposal, request.actor_id)
    )
    result = ReviewIntakeSelection(
        _summary(row), eligible, opened, scope.accepts_private_planning_writes
    )
    _audit(request, "intake_seal", revision_id, authorizer)
    return result
