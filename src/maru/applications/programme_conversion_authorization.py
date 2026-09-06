"""Independent exact-adapter and Department proof for accepted conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
)
from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    _require_complete_decision,
    _require_test_authorizer,
    authorize_programme_retry_scope,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import resolve_active_verified_person_reference
from maru.programme.adoption import PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER
from maru.workforce.queries import resolve_current_department_reference

if TYPE_CHECKING:
    from uuid import UUID

    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )
    from maru.authorization.policy import PolicyDecision

CONVERT_PROGRAMME_ACCEPTANCE: Final = "applications.convert_programme_acceptance"
_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeConversionScope:
    """Carry identifier-only current authority before private source lookup.

    Attributes
    ----------
    actor_id
        Exact active verified converting person.
    organization_id
        Exact organization owning the edition.
    edition_id
        Exact private-planning edition.
    department_id
        Current exact owner Department, without hierarchy inheritance.
    accepts_private_planning_writes
        Whether the edition currently accepts fresh conversion.
    decision
        Complete current capability decision, without content read fields.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def authorize_programme_conversion_retry(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> None:
    """Require current identity and both exact adapters before retained replay.

    Parameters
    ----------
    actor_id : UUID
        Exact actor whose retained identifiers may be returned.
    organization_id : UUID
        Expected organization of the receipt and edition.
    edition_id : UUID
        Exact edition whose two adapter pins are independently required.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy adapter or the existing two-factor isolated-test seam.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, scope, adoption, or substitute-policy containment fails.
    """
    _require_test_authorizer(authorizer)
    authorize_programme_retry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not all(
        profile_allows_adapter(profile.code, profile.version, code)
        for code in (
            APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
            PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER,
        )
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError


def authorize_programme_conversion_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> AuthorizedProgrammeConversionScope:
    """Prove exact current conversion authority without granting content access.

    Parameters
    ----------
    actor_id : UUID
        Authenticated converting person.
    organization_id : UUID
        Expected organization owning the complete source and target scope.
    edition_id : UUID
        Exact edition containing the proposed conversion.
    department_id : UUID
        Exact current source-owner Department.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy adapter or the existing two-factor isolated-test seam.

    Returns
    -------
    AuthorizedProgrammeConversionScope
        Minimized current proof; exact object and version checks remain required.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If any current identity, adapter, Department, or capability proof fails.
    """
    authorize_programme_conversion_retry(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    actor = resolve_active_verified_person_reference(account_id=actor_id)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    department = resolve_current_department_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )
    if actor is None or edition is None or department is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    decision = authorizer.authorize_department(
        principal_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=department.department_id,
        capability_code=CONVERT_PROGRAMME_ACCEPTANCE,
        requested_fields=frozenset(),
    )
    return AuthorizedProgrammeConversionScope(
        actor_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
        department_id=department.department_id,
        accepts_private_planning_writes=edition.accepts_private_planning_writes,
        decision=_require_complete_decision(decision, requested_fields=frozenset()),
    )


__all__ = [
    "CONVERT_PROGRAMME_ACCEPTANCE",
    "AuthorizedProgrammeConversionScope",
    "authorize_programme_conversion_retry",
    "authorize_programme_conversion_scope",
]
