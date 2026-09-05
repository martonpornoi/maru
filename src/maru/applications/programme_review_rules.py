"""Applications-owned exact-revision and independent-review eligibility rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from maru.applications.models import (
    ProgrammeProposalCollaborator,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalState,
    ProgrammeReviewAction,
    ProgrammeReviewAssignment,
    ProgrammeReviewAssignmentState,
    ProgrammeReviewCase,
    ProgrammeReviewEntry,
    ProgrammeReviewState,
)
from maru.identity.queries import resolve_active_verified_person_reference

if TYPE_CHECKING:
    from uuid import UUID

    from maru.applications.models import ProgrammeProposal, ProgrammeReviewDecision

_STAGE_CHANGES: Final = frozenset(
    {
        ProgrammeReviewAction.REVIEWER_ASSIGNED,
        ProgrammeReviewAction.CONFLICT_CLEARED,
        ProgrammeReviewAction.REVIEWER_RECUSED,
        ProgrammeReviewAction.REVIEWER_REMOVED,
        ProgrammeReviewAction.SCORED,
        ProgrammeReviewAction.DISCUSSED,
    }
)


class ProgrammeReviewConflictError(RuntimeError):
    """Reject stale, incompatible, or insufficient review evidence without detail."""

    reason_code = "applications_programme_review_conflict"


class ProgrammeReviewUnavailableError(RuntimeError):
    """Hide an absent, foreign-scope, or unavailable review object."""

    reason_code = "applications_programme_review_unavailable"


def load_review_case(
    *, organization_id: UUID, edition_id: UUID, case_id: UUID
) -> ProgrammeReviewCase:
    """Load one coherent, exact-tenant review aggregate after entry authorization.

    Parameters
    ----------
    organization_id : UUID
        Authorized organization identifier.
    edition_id : UUID
        Authorized exact edition identifier.
    case_id : UUID
        Caller-supplied opaque review identifier.

    Returns
    -------
    ProgrammeReviewCase
        The owned aggregate with its exact source and policy relations.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If any requested source or scope relation is unavailable.
    """
    case = (
        ProgrammeReviewCase.objects.select_related(
            "proposal__submission",
            "proposal__call__definition",
            "policy",
            "revision",
            "revision__selection_revision__track",
            "revision__selection_revision__format",
        )
        .filter(
            id=case_id,
            proposal__organization_id=organization_id,
            proposal__edition_id=edition_id,
            revision__organization_id=organization_id,
            revision__edition_id=edition_id,
            policy__call__organization_id=organization_id,
            policy__call__edition_id=edition_id,
        )
        .first()
    )
    if (
        case is None
        or case.revision.proposal_id != case.proposal_id
        or case.policy.call_id != case.proposal.call_id
    ):
        raise ProgrammeReviewUnavailableError
    return case


def revision_is_current(case: ProgrammeReviewCase) -> bool:
    """Return whether the case still names the proposal's exact submitted seal.

    Parameters
    ----------
    case : ProgrammeReviewCase
        Exact authorized aggregate with the proposal relation loaded.

    Returns
    -------
    bool
        Whether reopening, withdrawal, or a newer seal has not displaced it.
    """
    return (
        case.proposal.state == ProgrammeProposalState.SUBMITTED
        and case.proposal.submitted_revision_id == case.revision_id
        and case.proposal.sealed_revision_id == case.revision_id
    )


def is_proposal_contributor(proposal: ProgrammeProposal, account_id: UUID) -> bool:
    """Identify current or retained contributor conflicts without disclosing names.

    Parameters
    ----------
    proposal : ProgrammeProposal
        Scoped proposal with its submission relation available.
    account_id : UUID
        Exact proposed reviewer, moderator, or decision maker.

    Returns
    -------
    bool
        Whether this person is the lead or has a retained collaborator record.
    """
    return proposal.submission.account_id == account_id or (
        ProgrammeProposalCollaborator.objects.filter(
            proposal_id=proposal.id,
            organization_id=proposal.organization_id,
            edition_id=proposal.edition_id,
            account_id=account_id,
        ).exists()
    )


def require_independent_actor(
    case: ProgrammeReviewCase, actor_id: UUID, *, decision: bool = False
) -> None:
    """Reject contributors, assigned reviewers, and conflicting decision actors.

    Parameters
    ----------
    case : ProgrammeReviewCase
        Scoped review aggregate.
    actor_id : UUID
        Exact moderation or final-decision actor.
    decision : bool, default=False
        Whether prior moderation additionally excludes this final decision maker.

    Raises
    ------
    ProgrammeReviewConflictError
        If the actor is not independent of the evidence they would approve.
    """
    if (
        is_proposal_contributor(case.proposal, actor_id)
        or ProgrammeReviewAssignment.objects.filter(
            case=case, account_id=actor_id
        ).exists()
        or (
            decision
            and ProgrammeReviewEntry.objects.filter(
                case=case, actor_id=actor_id, action=ProgrammeReviewAction.MODERATED
            ).exists()
        )
    ):
        raise ProgrammeReviewConflictError


def latest_stage_scores(
    case: ProgrammeReviewCase, stage: int
) -> tuple[ProgrammeReviewEntry, ...]:
    """Return one latest score for each live, active verified stage assignment.

    Parameters
    ----------
    case : ProgrammeReviewCase
        Scoped exact-revision review case.
    stage : int
        Exact configured stage index.

    Returns
    -------
    tuple[ProgrammeReviewEntry, ...]
        Bounded latest score evidence, excluding removed or recused assignments.
    """
    entries = (
        ProgrammeReviewEntry.objects.filter(
            case=case,
            stage=stage,
            action=ProgrammeReviewAction.SCORED,
            assignment__case=case,
            assignment__stage=stage,
            assignment__state=ProgrammeReviewAssignmentState.ACTIVE,
        )
        .order_by("assignment_id", "-version")
        .distinct("assignment_id")
    )
    return tuple(
        entry
        for entry in entries
        if resolve_active_verified_person_reference(account_id=entry.actor_id)
        is not None
    )


def stage_is_ready(case: ProgrammeReviewCase, stage: int) -> bool:
    """Check explicit score count and fresh independent moderation for one stage.

    Parameters
    ----------
    case : ProgrammeReviewCase
        Scoped aggregate with its immutable policy loaded.
    stage : int
        Exact configured stage index.

    Returns
    -------
    bool
        Whether effective scoring and moderation satisfy the pinned stage policy.
    """
    moderation = (
        ProgrammeReviewEntry.objects.filter(
            case=case, stage=stage, action=ProgrammeReviewAction.MODERATED
        )
        .order_by("-version")
        .first()
    )
    if (
        moderation is None
        or len(latest_stage_scores(case, stage))
        < case.policy.stages[stage]["required_reviews"]
    ):
        return False
    if ProgrammeReviewEntry.objects.filter(
        case=case,
        stage=stage,
        action__in=_STAGE_CHANGES,
        version__gt=moderation.version,
    ).exists():
        return False
    # Explicit reopening invalidates moderation for that stage and every later
    # stage without rewriting any historical reviewer or moderator record.
    return not ProgrammeReviewEntry.objects.filter(
        case=case,
        action=ProgrammeReviewAction.STAGE_REOPENED,
        stage__lte=stage,
        version__gt=moderation.version,
    ).exists()


def accepted_review_is_effective(case: ProgrammeReviewCase) -> bool:
    """Check the review-side conditions a later target adapter must revalidate.

    Owner Department and adoption authority are deliberately separate proofs.
    This function alone never authorizes a target creation or content read.

    Parameters
    ----------
    case : ProgrammeReviewCase
        Scoped and current review aggregate under the caller's consistency lock.

    Returns
    -------
    bool
        Whether the exact accepted review retains all stage and revision evidence.
    """
    return (
        case.state == ProgrammeReviewState.ACCEPTED
        and revision_is_current(case)
        and all(stage_is_ready(case, stage) for stage in range(len(case.policy.stages)))
    )


def is_decision_recipient(decision: ProgrammeReviewDecision, actor_id: UUID) -> bool:
    """Resolve an exact included contributor from the decision's immutable seal.

    Parameters
    ----------
    decision : ProgrammeReviewDecision
        Decision reached through a scoped review case.
    actor_id : UUID
        Current verified person requesting their own message or acknowledgement.

    Returns
    -------
    bool
        Whether the actor was actually included in this exact reviewed seal.
    """
    return ProgrammeProposalRevisionContributor.objects.filter(
        revision_id=decision.revision_id,
        organization_id=decision.revision.organization_id,
        edition_id=decision.revision.edition_id,
        account_id=actor_id,
    ).exists()
