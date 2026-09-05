"""Exact purpose, Department, and field proofs for dormant Programme review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    _require_complete_decision,
    _require_test_authorizer,
)
from maru.events.queries import resolve_private_planning_edition_reference
from maru.identity.queries import resolve_active_verified_person_reference
from maru.workforce.queries import resolve_current_department_reference

if TYPE_CHECKING:
    from uuid import UUID

    from maru.applications.models import ProgrammeReviewCase
    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )
    from maru.authorization.policy import PolicyDecision

MANAGE_REVIEW: Final = "applications.manage_programme_review"
REVIEW: Final = "applications.review_programme"
MODERATE: Final = "applications.moderate_programme_review"
DECIDE: Final = "applications.decide_programme"
VIEW_DECISION_SELF: Final = "applications.view_programme_decision_self"
ACKNOWLEDGE_SELF: Final = "applications.acknowledge_programme_decision_self"
SENSITIVE_REVIEW: Final = "applications.review_sensitive"
REVIEW_STAFF_CAPABILITIES: Final = frozenset({MANAGE_REVIEW, REVIEW, MODERATE, DECIDE})
REVIEW_SELF_CAPABILITIES: Final = frozenset({VIEW_DECISION_SELF, ACKNOWLEDGE_SELF})
PROGRAMME_REVIEW_CAPABILITIES: Final = (
    REVIEW_STAFF_CAPABILITIES | REVIEW_SELF_CAPABILITIES
)
REVIEW_FIELDS: Final = frozenset(
    {"review_context", "review_answers", "review_evidence"}
)
DECISION_SELF_FIELDS: Final = frozenset({"decision_message", "own_acknowledgement"})
_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeReviewScope:
    """Carry identifier-only proof before any protected review payload lookup.

    Attributes
    ----------
    actor_id
        Exact active verified actor.
    organization_id
        Organization owning the resolved edition.
    edition_id
        Exact private-planning edition.
    department_id
        Current exact Department for staff, or None for recipient self access.
    capability_code
        The one closed purpose capability evaluated.
    accepts_private_planning_writes
        Whether ordinary staff planning mutations remain permitted.
    decision
        Complete current policy result, including field ceilings.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID | None
    capability_code: str
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def authorize_programme_review_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID | None,
    capability_code: str,
    requested_fields: frozenset[str] = frozenset(),
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> AuthorizedProgrammeReviewScope:
    """Prove exact identity, adopted purpose, Department, and requested fields.

    This entry proof does not establish assignment, conflict, independence, or
    recipient membership. The owning command or query must prove those against
    its exact object before mutation or content disclosure, and reauthorize
    after the canonical writer locks or before returning a protected projection.

    Parameters
    ----------
    actor_id : UUID
        Authenticated person whose exact capability is required.
    organization_id : UUID
        Expected owner of the edition and Department.
    edition_id : UUID
        Exact edition containing the requested review object.
    department_id : UUID | None
        Required current staff Department; recipient self access requires None.
    capability_code : str
        One closed review, recipient, or independent sensitive-review capability.
    requested_fields : frozenset[str], default=frozenset()
        Complete code-owned field ceiling; mutations do not imply content reads.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real exact policy adapter or the existing two-factor isolated-test seam.

    Returns
    -------
    AuthorizedProgrammeReviewScope
        Non-disclosing scope and complete decision proof.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If any identity, scope, adoption, purpose, or field proof fails.
    """
    if (
        not isinstance(capability_code, str)
        or capability_code not in PROGRAMME_REVIEW_CAPABILITIES | {SENSITIVE_REVIEW}
        or not isinstance(requested_fields, frozenset)
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    if capability_code in REVIEW_SELF_CAPABILITIES:
        if department_id is not None or not requested_fields <= DECISION_SELF_FIELDS:
            raise ApplicationsProgrammeAuthorizationDeniedError
        decision = authorizer.authorize_self(
            principal_id=actor.account_id,
            owner_account_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )
    else:
        ceiling = (
            frozenset({"review_context"})
            if capability_code == MANAGE_REVIEW
            else REVIEW_FIELDS
        )
        if department_id is None or not requested_fields <= ceiling:
            raise ApplicationsProgrammeAuthorizationDeniedError
        department = resolve_current_department_reference(
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            department_id=department_id,
        )
        if department is None:
            raise ApplicationsProgrammeAuthorizationDeniedError
        decision = authorizer.authorize_department(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            department_id=department.department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )
    return AuthorizedProgrammeReviewScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=department_id,
        capability_code=capability_code,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=_require_complete_decision(
            decision, requested_fields=requested_fields
        ),
    )


def require_sensitive_programme_review_authority(  # noqa: DOC502 -- Delegated policy proof denies.
    *,
    scope: AuthorizedProgrammeReviewScope,
    case: ProgrammeReviewCase,
    requested_fields: frozenset[str] = frozenset(),
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> None:
    """Require independent sensitive-review authority for restricted definitions.

    Parameters
    ----------
    scope : AuthorizedProgrammeReviewScope
        Already-proven exact staff scope and purpose.
    case : ProgrammeReviewCase
        Scoped aggregate whose pinned proposal definition sets classification.
    requested_fields : frozenset[str], default=frozenset()
        Complete requested content ceiling, or empty for protected review writes.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real exact policy or the guarded isolated-test admission seam.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the definition requires sensitive authority which this actor lacks.
    """
    if case.proposal.call.definition.is_sensitive:
        authorize_programme_review_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            capability_code=SENSITIVE_REVIEW,
            requested_fields=requested_fields,
            authorizer=authorizer,
        )
