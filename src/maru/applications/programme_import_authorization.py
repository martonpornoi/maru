"""Fail-closed authority seams for dormant Programme import staging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from django.conf import settings
from django.db import connection

from maru.applications.programme_adoption import (
    profile_allows_application_programme_import,
    profile_allows_application_programme_self,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
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
    from uuid import UUID


APPLICATIONS_IMPORT_PROGRAMME: Final = "applications.import_programme"
APPLICATIONS_DISPOSE_PROGRAMME_IMPORT: Final = "applications.dispose_programme_import"


class ApplicationsProgrammeImportAuthorizationDeniedError(RuntimeError):
    """Hide which identity, scope, adoption, or capability caused denial."""

    reason_code = "applications_programme_import_authorization_denied"


class ApplicationsProgrammeImportAuthorizer(Protocol):
    """Evaluate exact Department, Edition, self, and retry authority."""

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
        """Return one complete exact-Department import decision.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting the operation.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact edition containing the Department.
        department_id : UUID
            Current Department that owns the staged import.
        capability_code : str
            Capability required for the requested operation.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

        Returns
        -------
        PolicyDecision
            Complete allow-or-deny policy decision.
        """
        ...

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Return one complete exact-Edition disposal decision.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting disposal.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact edition containing the retained import.
        capability_code : str
            Edition-scoped capability required for disposal.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

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
        """Return one complete exact-self import decision.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting proposal access.
        owner_account_id : UUID
            Exact proposal lead account resolved for self authority.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact edition containing the imported proposal.
        capability_code : str
            Supported self-view or self-edit capability.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

        Returns
        -------
        PolicyDecision
            Complete allow-or-deny policy decision.
        """
        ...

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Return an adoption-scoped retained-receipt decision.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting replay.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact edition containing the retained receipt.

        Returns
        -------
        PolicyDecision
            Complete allow-or-deny replay decision.
        """
        ...


def _denial() -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="module_not_adopted",
    )


def _profile_allows_import(*, organization_id: UUID, edition_id: UUID) -> bool:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    return bool(
        profile is not None
        and profile_allows_application_programme_import(profile.code, profile.version)
    )


@dataclass(frozen=True, slots=True)
class ExactPolicyApplicationsProgrammeImportAuthorizer:
    """Apply ordinary scoped policy only after the exact import adapter is pinned."""

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
        """Evaluate exact-Department authority after import adoption.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting the operation.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact adopted edition containing the Department.
        department_id : UUID
            Current Department that owns the staged import.
        capability_code : str
            Capability required for the requested operation.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

        Returns
        -------
        PolicyDecision
            Exact policy decision, denied when import is not adopted.
        """
        if not _profile_allows_import(
            organization_id=organization_id,
            edition_id=edition_id,
        ):
            return _denial()
        return decide_verified_principal_exact_department(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate exact-Edition disposal authority after import adoption.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting disposal.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact adopted edition containing the retained import.
        capability_code : str
            Edition-scoped capability required for disposal.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

        Returns
        -------
        PolicyDecision
            Exact policy decision, denied when import is not adopted.
        """
        if not _profile_allows_import(
            organization_id=organization_id,
            edition_id=edition_id,
        ):
            return _denial()
        return decide_verified_principal_exact_edition(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
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
        """Evaluate exact-self authority after all required adapters.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting proposal access.
        owner_account_id : UUID
            Exact proposal lead account resolved for self authority.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact adopted edition containing the imported proposal.
        capability_code : str
            Supported self-view or self-edit capability.
        requested_fields : frozenset[str] | None
            Optional complete field set required by the caller.

        Returns
        -------
        PolicyDecision
            Exact policy decision, denied unless both adapters are adopted.
        """
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if (
            profile is None
            or not _profile_allows_import(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            or not profile_allows_application_programme_self(
                profile.code,
                profile.version,
            )
        ):
            return _denial()
        return decide_verified_principal_exact_self(
            principal_id=principal_id,
            owner_account_id=owner_account_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Gate import receipt replay by the exact adopted adapter.

        Parameters
        ----------
        principal_id : UUID
            Active verified principal requesting replay. Relationship authority
            is deliberately not persisted or re-evaluated for a receipt replay.
        organization_id : UUID
            Exact organization that owns the edition.
        edition_id : UUID
            Exact edition containing the retained receipt.

        Returns
        -------
        PolicyDecision
            Adoption-scoped replay decision.
        """
        del principal_id
        if not _profile_allows_import(
            organization_id=organization_id,
            edition_id=edition_id,
        ):
            return _denial()
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="applications_programme_import_retry_scope",
        )


DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER: Final = (
    ExactPolicyApplicationsProgrammeImportAuthorizer()
)
_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeImportScope:
    """Retain only current facts needed by one import operation.

    Attributes
    ----------
    actor_id : UUID
        Active verified account authorized for the operation.
    organization_id : UUID
        Exact organization that owns the import scope.
    edition_id : UUID
        Exact event edition that owns the import scope.
    department_id : UUID | None
        Current owning Department, when the operation is Department-scoped.
    accepts_private_planning_writes : bool
        Whether the current edition lifecycle accepts private planning writes.
    decision : PolicyDecision
        Complete allow decision and its authorized fields and obligations.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID | None
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def _require_test_authorizer(
    authorizer: ApplicationsProgrammeImportAuthorizer,
) -> None:
    if authorizer is DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER:
        return
    database_name = connection.settings_dict.get("NAME")
    if (
        not getattr(
            settings,
            "MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_AUTHORIZER",
            False,
        )
        or not isinstance(database_name, str)
        or not database_name.startswith("test_")
    ):
        raise ApplicationsProgrammeImportAuthorizationDeniedError


def _require_decision(
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
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    return decision


def authorize_programme_import_department_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    requested_fields: frozenset[str] | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _DEFAULT_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedProgrammeImportScope:
    """Authorize one exact current Department for staging or organizer preview.

    Parameters
    ----------
    actor_id : UUID
        Account expected to resolve to an active verified person.
    organization_id : UUID
        Exact organization that owns the requested edition.
    edition_id : UUID
        Exact private-planning edition in scope.
    department_id : UUID
        Current Department that will own the staged import.
    requested_fields : frozenset[str] | None, default=None
        Optional complete field set required from the decision.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_DEFAULT_AUTHORIZER
        Policy adapter using the exact policy implementation by default.
        Non-default adapters are accepted only in isolated tests.
    lock : bool, default=False
        Whether scope references should be locked for a surrounding command.

    Returns
    -------
    AuthorizedProgrammeImportScope
        Current normalized actor, organization, edition, Department, and policy.

    Raises
    ------
    ApplicationsProgrammeImportAuthorizationDeniedError
        If identity, scope, adoption, capability, fields, or test seams fail.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
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
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    decision = _require_decision(
        authorizer.authorize_department(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            department_id=department.department_id,
            capability_code=APPLICATIONS_IMPORT_PROGRAMME,
            requested_fields=requested_fields,
        ),
        requested_fields=requested_fields,
    )
    return AuthorizedProgrammeImportScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=department.department_id,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_import_self_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str] | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _DEFAULT_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedProgrammeImportScope:
    """Authorize exact self after transient lead-email resolution.

    Parameters
    ----------
    actor_id : UUID
        Account expected to resolve to the imported proposal lead.
    organization_id : UUID
        Exact organization that owns the requested edition.
    edition_id : UUID
        Exact private-planning edition in scope.
    capability_code : str
        Supported Programme proposal self-view or self-edit capability.
    requested_fields : frozenset[str] | None, default=None
        Optional complete field set required from the decision.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_DEFAULT_AUTHORIZER
        Policy adapter using the exact policy implementation by default.
        Non-default adapters are accepted only in isolated tests.
    lock : bool, default=False
        Whether identity and edition references should be transactionally locked.

    Returns
    -------
    AuthorizedProgrammeImportScope
        Current normalized actor and exact edition self-authority.

    Raises
    ------
    ApplicationsProgrammeImportAuthorizationDeniedError
        If the capability, identity, scope, adoption, fields, or test seam fails.
    """
    if capability_code not in {
        APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    }:
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    decision = _require_decision(
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
    return AuthorizedProgrammeImportScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=None,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_import_disposal_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeImportAuthorizer = _DEFAULT_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedProgrammeImportScope:
    """Authorize exact-Edition disposal without a current Department requirement.

    Parameters
    ----------
    actor_id : UUID
        Account expected to resolve to an active verified person.
    organization_id : UUID
        Exact organization that owns the requested edition.
    edition_id : UUID
        Exact edition containing the staged or historical import.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_DEFAULT_AUTHORIZER
        Policy adapter using the exact policy implementation by default.
        Non-default adapters are accepted only in isolated tests.
    lock : bool, default=False
        Whether identity and edition references should be transactionally locked.

    Returns
    -------
    AuthorizedProgrammeImportScope
        Current normalized actor and exact edition disposal authority.

    Raises
    ------
    ApplicationsProgrammeImportAuthorizationDeniedError
        If identity, edition, adoption, capability, or the test seam fails.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    decision = _require_decision(
        authorizer.authorize_edition(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
            capability_code=APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
            requested_fields=None,
        ),
        requested_fields=None,
    )
    return AuthorizedProgrammeImportScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=None,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


def authorize_programme_import_retry_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeImportAuthorizer = _DEFAULT_AUTHORIZER,
) -> AuthorizedProgrammeImportScope:
    """Authorize a retained import-receipt replay without an old relationship.

    Parameters
    ----------
    actor_id : UUID
        Account expected to resolve to an active verified person.
    organization_id : UUID
        Exact organization that owns the requested edition.
    edition_id : UUID
        Exact edition containing the retained command receipt.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_DEFAULT_AUTHORIZER
        Policy adapter using the exact policy implementation by default.
        Non-default adapters are accepted only in isolated tests.

    Returns
    -------
    AuthorizedProgrammeImportScope
        Current normalized actor and adoption-scoped replay authority.

    Raises
    ------
    ApplicationsProgrammeImportAuthorizationDeniedError
        If identity, edition, adoption, or the isolated test seam fails.
    """
    _require_test_authorizer(authorizer)
    actor = resolve_active_verified_person_reference(account_id=actor_id)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if actor is None or edition is None:
        raise ApplicationsProgrammeImportAuthorizationDeniedError
    decision = _require_decision(
        authorizer.authorize_retry(
            principal_id=actor.account_id,
            organization_id=edition.organization_id,
            edition_id=edition.edition_id,
        ),
        requested_fields=frozenset(),
    )
    return AuthorizedProgrammeImportScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=None,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=decision,
    )


__all__ = [
    "APPLICATIONS_DISPOSE_PROGRAMME_IMPORT",
    "APPLICATIONS_IMPORT_PROGRAMME",
    "DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER",
    "ApplicationsProgrammeImportAuthorizationDeniedError",
    "ApplicationsProgrammeImportAuthorizer",
    "AuthorizedProgrammeImportScope",
    "ExactPolicyApplicationsProgrammeImportAuthorizer",
    "authorize_programme_import_department_scope",
    "authorize_programme_import_disposal_scope",
    "authorize_programme_import_retry_scope",
    "authorize_programme_import_self_scope",
]
