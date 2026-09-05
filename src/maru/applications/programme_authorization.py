"""Fail-closed authority seams for Programme calls and self proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from maru.applications.adoption import profile_allows_application_target
from maru.applications.models import (
    ProgrammeCollaboratorState,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalState,
)
from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
    profile_allows_application_programme_self,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_department,
    decide_verified_principal_exact_edition,
    decide_verified_principal_exact_self,
)
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import resolve_active_verified_person_reference
from maru.workforce.queries import resolve_current_department_reference

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

APPLICATIONS_MANAGE_PROGRAMME_CALLS: Final = "applications.manage_programme_calls"
APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF: Final = (
    "applications.view_programme_proposal_self"
)
APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF: Final = (
    "applications.edit_programme_proposal_self"
)
APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF: Final = (
    "applications.respond_programme_invitation_self"
)
APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF: Final = (
    "applications.manage_programme_proposal_self"
)
APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF: Final = (
    "applications.submit_programme_proposal_self"
)
APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP: Final = (
    "applications.recover_programme_department_ownership"
)

APPLICATIONS_PROGRAMME_CAPABILITY_CODES: Final = frozenset(
    {
        APPLICATIONS_MANAGE_PROGRAMME_CALLS,
        APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
        APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
        APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    }
)
APPLICATIONS_PROGRAMME_PROPOSAL_CAPABILITY_CODES: Final = frozenset(
    {
        APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
        APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    }
)

_FULL_PROPOSAL_VIEW_FIELDS: Final = frozenset(
    {
        "proposal_summary",
        "selection",
        "answers",
        "contributors",
        "contributor_profiles",
        "revision_history",
        "revision_responses",
        "own_invitation",
    }
)
_INVITEE_PROPOSAL_VIEW_FIELDS: Final = frozenset(
    {"proposal_summary", "selection", "own_invitation"}
)


class ApplicationsProgrammeAuthorizationDeniedError(RuntimeError):
    """Hide which identity, scope, relationship, or profile caused denial."""

    reason_code = "applications_programme_authorization_denied"


class ApplicationsProgrammeAuthorizer(Protocol):
    """Evaluate exact call and relationship-derived proposal capabilities."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Return one complete exact-Department policy decision.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the scope.
        edition_id : UUID
            Exact event edition identifier.
        department_id : UUID
            Exact current Department identifier.
        capability_code : str
            Registered Programme call capability.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling.

        Returns
        -------
        PolicyDecision
            Complete allow-or-deny policy decision.
        """
        ...

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Return one complete exact-self policy decision.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        owner_account_id : UUID
            Account whose self scope is being proven.
        organization_id : UUID
            Organization expected to own the scope.
        edition_id : UUID
            Exact event edition identifier.
        capability_code : str
            Registered Programme proposal self capability.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling.

        Returns
        -------
        PolicyDecision
            Complete allow-or-deny policy decision.
        """
        ...

    def authorize_recovery(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Return one exact-Edition ownership-recovery decision.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the edition.
        edition_id : UUID
            Exact event edition containing the caller-supplied target.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling. Recovery requests no content
            fields and grants no discovery or listing authority.

        Returns
        -------
        PolicyDecision
            Complete exact-Edition break-glass policy decision.
        """
        ...

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Return adoption-only authority for retained receipt replay.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the receipt scope.
        edition_id : UUID
            Exact event edition identifier.

        Returns
        -------
        PolicyDecision
            Complete adoption-scoped replay decision.
        """
        ...

    def authorize_recovery_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Re-prove exact-Edition recovery authority before receipt lookup.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the retained receipt.
        edition_id : UUID
            Exact edition containing the retained recovery receipt.

        Returns
        -------
        PolicyDecision
            Complete recovery-capability decision with no resource fields.
        """
        ...


def _profile_denial() -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="module_not_adopted",
    )


@dataclass(frozen=True, slots=True)
class ExactPolicyApplicationsProgrammeAuthorizer:
    """Invoke ordinary policy after exact future-profile adapter checks."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate current Department authority for a Programme call.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the scope.
        edition_id : UUID
            Exact event edition identifier.
        department_id : UUID
            Exact current Department identifier.
        capability_code : str
            Registered Programme call capability.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling.

        Returns
        -------
        PolicyDecision
            Complete adapter and policy decision.
        """
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if profile is None or not profile_allows_application_target(
            profile.code,
            profile.version,
            APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
        ):
            return _profile_denial()
        return decide_verified_principal_exact_department(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate one Applications-proven proposal self relationship.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        owner_account_id : UUID
            Applications-proven account owning the self scope.
        organization_id : UUID
            Organization expected to own the scope.
        edition_id : UUID
            Exact event edition identifier.
        capability_code : str
            Registered Programme proposal self capability.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling.

        Returns
        -------
        PolicyDecision
            Complete adapter and policy decision.
        """
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if (
            profile is None
            or not profile_allows_application_programme_self(
                profile.code,
                profile.version,
            )
            or not profile_allows_application_target(
                profile.code,
                profile.version,
                APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
            )
        ):
            return _profile_denial()
        return decide_verified_principal_exact_self(
            principal_id=principal_id,
            owner_account_id=owner_account_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_recovery(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate the dormant exact-Edition break-glass capability.

        The capability is globally declared but intentionally absent from all
        current profiles and grant paths. Keeping the ordinary policy call
        behind the adopted Programme target check makes this boundary ready
        for a future governed operator without activating it today.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the edition.
        edition_id : UUID
            Exact adopted edition containing the recovery target.
        requested_fields : frozenset[str] | None
            Optional code-owned field ceiling; recovery supplies no content
            fields.

        Returns
        -------
        PolicyDecision
            Exact-Edition recovery decision, denied while the capability is
            dormant or the Programme target is not adopted.
        """
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if profile is None or not profile_allows_application_target(
            profile.code,
            profile.version,
            APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
        ):
            return _profile_denial()
        return decide_verified_principal_exact_edition(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
            requested_fields=requested_fields,
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Gate replay by current identity scope and exact adopted Programme.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the receipt scope.
        edition_id : UUID
            Exact event edition identifier.

        Returns
        -------
        PolicyDecision
            Complete adoption-scoped replay decision.
        """
        del principal_id
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if profile is None or not profile_allows_application_target(
            profile.code,
            profile.version,
            APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
        ):
            return _profile_denial()
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="applications_programme_retry_receipt_scope",
        )

    def authorize_recovery_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Re-prove dormant recovery capability for an exact receipt scope.

        Parameters
        ----------
        principal_id : UUID
            Exact authenticated principal identifier.
        organization_id : UUID
            Organization expected to own the retained receipt.
        edition_id : UUID
            Exact edition containing the retained recovery receipt.

        Returns
        -------
        PolicyDecision
            Complete exact-Edition recovery decision with no requested fields.
        """
        return self.authorize_recovery(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=None,
        )


DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER: Final = (
    ExactPolicyApplicationsProgrammeAuthorizer()
)
_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeCallScope:
    """Retain minimized current facts for one authorized call operation.

    Attributes
    ----------
    actor_id : UUID
        Exact active verified account authorized for the operation.
    organization_id : UUID
        Organization that owns the authorized scope.
    edition_id : UUID
        Exact private-planning edition identifier.
    department_id : UUID
        Exact current owner Department identifier.
    accepts_private_planning_writes : bool
        Whether the edition currently accepts protected planning writes.
    decision : PolicyDecision
        Complete allow decision and its field and audit obligations.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeSelfEntryScope:
    """Retain exact self authority before a proposal relationship exists.

    Attributes
    ----------
    actor_id : UUID
        Exact active verified account authorized for self entry.
    organization_id : UUID
        Organization that owns the authorized scope.
    edition_id : UUID
        Exact private-planning edition identifier.
    accepts_private_planning_writes : bool
        Whether the edition currently accepts protected planning writes.
    decision : PolicyDecision
        Complete self-policy decision and disclosure obligations.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeRetryScope:
    """Retain only current identity, edition, and adopted Programme proof.

    Attributes
    ----------
    actor_id : UUID
        Exact active verified account requesting replay.
    organization_id : UUID
        Organization that owns the retained receipt scope.
    edition_id : UUID
        Exact private-planning edition identifier.
    accepts_private_planning_writes : bool
        Whether the edition currently accepts protected planning writes.
    decision : PolicyDecision
        Complete adoption-scoped replay decision.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeRecoveryScope:
    """Retain lifecycle-neutral exact-Edition recovery authority.

    Attributes
    ----------
    actor_id : UUID
        Exact active verified account authorized for recovery.
    organization_id : UUID
        Organization that owns the recovered aggregate.
    edition_id : UUID
        Exact edition containing the caller-supplied aggregate identifier.
    decision : PolicyDecision
        Complete break-glass policy decision and audit obligations.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    decision: PolicyDecision


ProgrammeProposalRelationship = Literal["lead", "invited", "collaborator"]


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeProposalScope:
    """Retain one current proposal relationship and complete policy decision.

    Attributes
    ----------
    actor_id : UUID
        Exact active verified account authorized for the proposal.
    organization_id : UUID
        Organization that owns the proposal.
    edition_id : UUID
        Exact private-planning edition identifier.
    department_id : UUID
        Department that owns the proposal's call.
    proposal_id : UUID
        Exact Applications-owned Programme proposal identifier.
    submission_id : UUID
        Underlying typed Applications submission identifier.
    call_id : UUID
        Exact call that owns the proposal.
    state : str
        Current closed proposal lifecycle state.
    aggregate_version : int
        Current optimistic proposal aggregate version.
    relationship : ProgrammeProposalRelationship
        Proven lead, live invitee, or accepted-collaborator relationship.
    accepts_private_planning_writes : bool
        Whether the edition currently accepts protected planning writes.
    decision : PolicyDecision
        Complete self-policy decision and disclosure obligations.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    proposal_id: UUID
    submission_id: UUID
    call_id: UUID
    state: str
    aggregate_version: int
    relationship: ProgrammeProposalRelationship
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def _require_test_authorizer(
    authorizer: ApplicationsProgrammeAuthorizer,
) -> None:
    if authorizer is DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER:
        return
    database_name = connection.settings_dict.get("NAME")
    if (
        not getattr(
            settings,
            "MARU_ALLOW_APPLICATIONS_PROGRAMME_TEST_AUTHORIZER",
            False,
        )
        or not isinstance(database_name, str)
        or not database_name.startswith("test_")
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError


def _require_complete_decision(
    decision: object,
    *,
    requested_fields: frozenset[str] | None,
) -> PolicyDecision:
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or (
            requested_fields is not None
            and not requested_fields.issubset(decision.fields)
        )
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return decision


def authorize_programme_call_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    requested_fields: frozenset[str] | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
    lock: bool = False,
) -> AuthorizedProgrammeCallScope:
    """Authorize one exact current Department for Programme call management.

    Parameters
    ----------
    actor_id : UUID
        The exact current person-account identifier.
    organization_id : UUID
        The organization expected to own the edition and Department.
    edition_id : UUID
        The exact event edition identifier.
    department_id : UUID
        The exact current owner Department identifier.
    requested_fields : frozenset[str] | None, default=None
        Optional code-owned fields covered by the decision.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        The sealed complete-decision adapter.
    lock : bool, default=False
        Whether owner reference queries acquire row locks.

    Returns
    -------
    AuthorizedProgrammeCallScope
        The minimized exact scope and complete policy decision.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If any identity, tenant, Department, profile, or policy check fails.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    department = resolve_current_department_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
        lock=lock,
    )
    if actor is None or edition is None or department is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = _require_complete_decision(
        authorizer.authorize_department(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            department_id=department.department_id,
            capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
            requested_fields=requested_fields,
        ),
        requested_fields=requested_fields,
    )
    return AuthorizedProgrammeCallScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=department.department_id,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_self_entry_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str] | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
    lock: bool = False,
) -> AuthorizedProgrammeSelfEntryScope:
    """Authorize exact self-service before a proposal relationship exists.

    Proposal start and available-call discovery cannot prove a relationship to
    a proposal row that does not exist yet. This seam therefore proves only the
    active verified person, exact private-planning edition, adopted self
    purpose, complete policy decision, and optional field ceiling. Commands
    and queries must still scope and validate the call after this check.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the edition.
    edition_id : UUID
        Exact event edition identifier.
    capability_code : str
        Entry-safe Programme proposal self capability.
    requested_fields : frozenset[str] | None, default=None
        Optional code-owned view field ceiling.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.
    lock : bool, default=False
        Whether identity and edition references acquire row locks.

    Returns
    -------
    AuthorizedProgrammeSelfEntryScope
        Minimized exact entry scope and complete policy decision.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If capability, identity, tenant, profile, or policy checks fail.
    """
    if capability_code not in {
        APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    }:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = _require_complete_decision(
        authorizer.authorize_self(
            principal_id=actor.account_id,
            owner_account_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        ),
        requested_fields=requested_fields,
    )
    return AuthorizedProgrammeSelfEntryScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_retry_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
    lock: bool = False,
) -> AuthorizedProgrammeRetryScope:
    """Prove a minimal non-disclosing scope before receipt replay lookup.

    A successful command can legitimately remove the actor's old Department or
    proposal relationship. Replay therefore proves only the still-active,
    verified person, exact private-planning edition, and adopted dormant
    Programme target contract. The retained receipt then proves the exact
    actor, edition, and request digest; fresh mutations still perform their full
    capability and relationship checks after the replay lookup.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the receipt scope.
    edition_id : UUID
        Exact event edition identifier.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.
    lock : bool, default=False
        Whether identity and edition references acquire row locks.

    Returns
    -------
    AuthorizedProgrammeRetryScope
        Minimized replay scope and complete adoption decision.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, tenant, profile, or policy checks fail.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = _require_complete_decision(
        authorizer.authorize_retry(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
        ),
        requested_fields=frozenset(),
    )
    return AuthorizedProgrammeRetryScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_recovery_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
    lock: bool = False,
) -> AuthorizedProgrammeRecoveryScope:
    """Authorize exact-ID orphan recovery at lifecycle-neutral Edition scope.

    This seam deliberately resolves no Department and accepts no target
    content. The command must already have a caller-supplied opaque aggregate
    identifier, and it receives no list, search, preview, or general Programme
    read authority from this proof.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the edition.
    edition_id : UUID
        Exact edition containing the opaque recovery target.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.
    lock : bool, default=False
        Whether identity and edition references acquire row locks.

    Returns
    -------
    AuthorizedProgrammeRecoveryScope
        Minimized lifecycle-neutral break-glass authority.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, tenant, adoption, capability, or test seams fail.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = _require_complete_decision(
        authorizer.authorize_recovery(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            requested_fields=None,
        ),
        requested_fields=None,
    )
    return AuthorizedProgrammeRecoveryScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        decision=decision,
    )


def authorize_programme_recovery_retry_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> AuthorizedProgrammeRecoveryScope:
    """Re-prove break-glass authority before recovery-receipt lookup.

    Successful recovery can change the current Department relationship, so a
    replay cannot depend on that relationship. It must nevertheless prove the
    recovery capability again, unlike ordinary Programme receipt replay.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the retained receipt.
    edition_id : UUID
        Exact edition containing the retained recovery receipt.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    AuthorizedProgrammeRecoveryScope
        Minimized exact-Edition recovery replay authority.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, tenant, adoption, capability, or test seams fail.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = _require_complete_decision(
        authorizer.authorize_recovery_retry(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
        ),
        requested_fields=None,
    )
    return AuthorizedProgrammeRecoveryScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        decision=decision,
    )


def _proposal_row(
    *,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    lock: bool,
) -> dict[str, object] | None:
    query = ProgrammeProposal.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return cast(
            "dict[str, object] | None",
            query.filter(
                id=proposal_id,
                organization_id=organization_id,
                edition_id=edition_id,
                submission__organization_id=organization_id,
                submission__edition_id=edition_id,
                call__organization_id=organization_id,
                call__edition_id=edition_id,
                call__definition__target_adapter_kind=(
                    APPLICATION_PROGRAMME_ITEM_TARGET_KIND
                ),
            )
            .values(
                "id",
                "state",
                "submission_id",
                "submission__account_id",
                "submission__aggregate_version",
                "call_id",
                "call__owner_department_id",
            )
            .first(),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def _collaborator_row(
    *,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    account_id: UUID,
    lock: bool,
) -> dict[str, object] | None:
    query = ProgrammeProposalCollaborator.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return cast(
            "dict[str, object] | None",
            query.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                proposal_id=proposal_id,
                account_id=account_id,
            )
            .values("state", "invite_expires_at")
            .first(),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def _proposal_relationship(  # noqa: PLR0911
    *,
    actor_id: UUID,
    proposal: dict[str, object],
    collaborator: dict[str, object] | None,
    capability_code: str,
    effective_now: datetime,
) -> ProgrammeProposalRelationship | None:
    is_lead = proposal["submission__account_id"] == actor_id
    if is_lead:
        if capability_code == APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF:
            return None
        return "lead"
    if collaborator is None:
        return None
    state = collaborator["state"]
    proposal_state = proposal["state"]
    if state == ProgrammeCollaboratorState.INVITED:
        expires_at = cast("datetime | None", collaborator["invite_expires_at"])
        invitation_current = expires_at is not None and expires_at > effective_now
        if not invitation_current or proposal_state != ProgrammeProposalState.DRAFT:
            return None
        if capability_code in {
            APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
        }:
            return "invited"
        return None
    if state != ProgrammeCollaboratorState.ACCEPTED:
        return None
    if capability_code in {
        APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    }:
        return "collaborator"
    return None


def authorize_programme_proposal_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str] | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
    lock: bool = False,
    now: datetime | None = None,
) -> AuthorizedProgrammeProposalScope:
    """Authorize a current lead, invitation, or accepted collaborator.

    Applications proves the relationship from its own exact current rows
    immediately before invoking the domain-neutral self-policy seam. Caller
    booleans, cached membership, account objects, and proposal content are not
    accepted across this boundary.

    Parameters
    ----------
    actor_id : UUID
        The exact current person-account identifier.
    organization_id : UUID
        The organization expected to own the proposal.
    edition_id : UUID
        The exact event edition identifier.
    proposal_id : UUID
        The exact Applications-owned Programme proposal identifier.
    capability_code : str
        One registered relationship-derived proposal capability.
    requested_fields : frozenset[str] | None, default=None
        Optional view fields requested by the caller.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        The sealed complete-decision adapter.
    lock : bool, default=False
        Whether current owner and relationship rows are locked.
    now : datetime | None, default=None
        Optional aware instant used for deterministic invitation expiry.

    Returns
    -------
    AuthorizedProgrammeProposalScope
        Minimized current relationship and complete policy evidence.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If any identity, tenant, relationship, profile, or policy check fails.
    """
    if capability_code not in APPLICATIONS_PROGRAMME_PROPOSAL_CAPABILITY_CODES:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _require_test_authorizer(authorizer)
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError
    actor = resolve_active_verified_person_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    proposal = _proposal_row(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        lock=lock,
    )
    if actor is None or edition is None or proposal is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    collaborator = None
    if proposal["submission__account_id"] != actor.account_id:
        collaborator = _collaborator_row(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            account_id=actor.account_id,
            lock=lock,
        )
    relationship = _proposal_relationship(
        actor_id=actor.account_id,
        proposal=proposal,
        collaborator=collaborator,
        capability_code=capability_code,
        effective_now=effective_now,
    )
    if relationship is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    policy_requested_fields = requested_fields
    if capability_code == APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF:
        relationship_fields = (
            _INVITEE_PROPOSAL_VIEW_FIELDS
            if relationship == "invited"
            else _FULL_PROPOSAL_VIEW_FIELDS
        )
        if requested_fields is not None and not requested_fields.issubset(
            relationship_fields
        ):
            raise ApplicationsProgrammeAuthorizationDeniedError
        policy_requested_fields = requested_fields or relationship_fields
    decision = _require_complete_decision(
        authorizer.authorize_self(
            principal_id=actor.account_id,
            owner_account_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            capability_code=capability_code,
            requested_fields=policy_requested_fields,
        ),
        requested_fields=policy_requested_fields,
    )
    return AuthorizedProgrammeProposalScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=cast("UUID", proposal["call__owner_department_id"]),
        proposal_id=cast("UUID", proposal["id"]),
        submission_id=cast("UUID", proposal["submission_id"]),
        call_id=cast("UUID", proposal["call_id"]),
        state=cast("str", proposal["state"]),
        aggregate_version=cast("int", proposal["submission__aggregate_version"]),
        relationship=relationship,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


__all__ = [
    "APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF",
    "APPLICATIONS_MANAGE_PROGRAMME_CALLS",
    "APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF",
    "APPLICATIONS_PROGRAMME_CAPABILITY_CODES",
    "APPLICATIONS_PROGRAMME_PROPOSAL_CAPABILITY_CODES",
    "APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP",
    "APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF",
    "APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF",
    "APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF",
    "DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER",
    "ApplicationsProgrammeAuthorizationDeniedError",
    "ApplicationsProgrammeAuthorizer",
    "AuthorizedProgrammeCallScope",
    "AuthorizedProgrammeProposalScope",
    "AuthorizedProgrammeRecoveryScope",
    "AuthorizedProgrammeRetryScope",
    "AuthorizedProgrammeSelfEntryScope",
    "ExactPolicyApplicationsProgrammeAuthorizer",
    "ProgrammeProposalRelationship",
    "authorize_programme_call_scope",
    "authorize_programme_proposal_scope",
    "authorize_programme_recovery_retry_scope",
    "authorize_programme_recovery_scope",
    "authorize_programme_retry_scope",
    "authorize_programme_self_entry_scope",
]
