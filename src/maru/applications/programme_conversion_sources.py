"""Applications-owned exact source proof for the Programme acceptance adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import connection

from maru.applications.models import (
    ProgrammeAcceptedTransition,
    ProgrammeReviewAction,
    ProgrammeReviewDecision,
    ProgrammeReviewState,
)
from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
)
from maru.applications.programme_conversion_authorization import (
    AuthorizedProgrammeConversionScope,
    authorize_programme_conversion_scope,
)
from maru.applications.programme_inputs import require_programme_uuid
from maru.applications.programme_review_rules import (
    accepted_review_is_effective,
    load_review_case,
)
from maru.applications.programme_write_scope import lock_programme_edition_write_scope

if TYPE_CHECKING:
    from uuid import UUID

    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )


_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


class ProgrammeConversionConflictError(RuntimeError):
    """Reject stale, consumed, or ineffective conversion without source detail."""

    reason_code = "applications_programme_conversion_conflict"


class ProgrammeConversionUnavailableError(RuntimeError):
    """Hide absent, foreign-scope, or unavailable conversion dependencies."""

    reason_code = "applications_programme_conversion_unavailable"


@dataclass(frozen=True, slots=True)
class AcceptedProgrammeSource:
    """Return only the exact identifiers needed by the Programme-owned writer.

    Attributes
    ----------
    transition_id
        Immutable Applications source receipt, always at source version one.
    item_id
        Exact Programme item identity reserved by the atomic conversion.
    actor_id
        Same currently authorized actor on both owners' evidence.
    organization_id
        Exact common source/target organization.
    edition_id
        Exact common source/target edition.
    expected_programme_version
        Programme edition-control version supplied in the conversion intent.
    resulting_programme_version
        Exactly the next Programme edition-control version.
    """

    transition_id: UUID
    item_id: UUID
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    expected_programme_version: int
    resulting_programme_version: int


def _current_accepted_decision(
    *,
    scope: AuthorizedProgrammeConversionScope,
    decision_id: UUID,
    revision_id: UUID,
    expected_review_version: int,
) -> ProgrammeReviewDecision:
    decision = (
        ProgrammeReviewDecision.objects.select_related("entry")
        .filter(
            id=decision_id,
            revision_id=revision_id,
            revision__organization_id=scope.organization_id,
            revision__edition_id=scope.edition_id,
            entry__case__revision_id=revision_id,
        )
        .first()
    )
    if decision is None:
        raise ProgrammeConversionUnavailableError
    case = load_review_case(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        case_id=decision.entry.case_id,
    )
    if case.proposal.call.owner_department_id != scope.department_id:
        raise ProgrammeConversionUnavailableError
    if (
        not scope.accepts_private_planning_writes
        or case.version != expected_review_version
        or decision.outcome != ProgrammeReviewState.ACCEPTED
        or decision.entry.action != ProgrammeReviewAction.DECIDED
        or decision.entry.version > case.version
        or not accepted_review_is_effective(case)
    ):
        raise ProgrammeConversionConflictError
    return decision


def resolve_accepted_programme_source(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    transition_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> AcceptedProgrammeSource:
    """Revalidate one owned conversion source inside the caller's transaction.

    This internal command query is not a review-content or administrative
    disclosure endpoint. It keeps the canonical edition locks held until the
    calling conversion transaction commits or rolls back, and returns no
    proposal, decision, contributor, or private-text projection.

    Parameters
    ----------
    actor_id : UUID
        Exact actor recorded on the in-progress source transition.
    organization_id : UUID
        Expected source and target organization.
    edition_id : UUID
        Expected exact source and target edition.
    department_id : UUID
        Current exact owner Department required for fresh conversion.
    transition_id : UUID
        Applications-owned source receipt; not an unchecked external identity.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the independently guarded isolated-test admission seam.

    Returns
    -------
    AcceptedProgrammeSource
        Minimized exact source and reserved target proof after fresh validation.

    Raises
    ------
    ProgrammeConversionUnavailableError
        If transaction context or an exact actor-owned source is unavailable.
    """
    for name, value in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("department_id", department_id),
        ("transition_id", transition_id),
    ):
        require_programme_uuid(value, field=name)
    identifiers = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "department_id": department_id,
    }
    authorize_programme_conversion_scope(**identifiers, authorizer=authorizer)
    if not connection.in_atomic_block:
        raise ProgrammeConversionUnavailableError
    lock_programme_edition_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(department_id,),
    )
    scope = authorize_programme_conversion_scope(**identifiers, authorizer=authorizer)
    source = ProgrammeAcceptedTransition.objects.filter(
        id=transition_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        actor_id=scope.actor_id,
    ).first()
    if source is None:
        raise ProgrammeConversionUnavailableError
    _current_accepted_decision(
        scope=scope,
        decision_id=source.decision_id,
        revision_id=source.revision_id,
        expected_review_version=source.review_version,
    )
    return AcceptedProgrammeSource(
        transition_id=source.id,
        item_id=source.programme_item_id,
        actor_id=source.actor_id,
        organization_id=source.organization_id,
        edition_id=source.edition_id,
        expected_programme_version=source.expected_programme_version,
        resulting_programme_version=source.resulting_programme_version,
    )


__all__ = [
    "AcceptedProgrammeSource",
    "ProgrammeConversionConflictError",
    "ProgrammeConversionUnavailableError",
    "resolve_accepted_programme_source",
]
