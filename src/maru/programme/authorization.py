"""Fail-closed authorization seam for dormant Programme operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from django.conf import settings
from django.db import connection

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.queries import (
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import resolve_active_verified_account_reference

if TYPE_CHECKING:
    from uuid import UUID

PROGRAMME_VIEW_PRIVATE: Final = "programme.view_private"
PROGRAMME_MANAGE_ITEMS: Final = "programme.manage_items"
PROGRAMME_VIEW_READINESS: Final = "programme.view_readiness"
PROGRAMME_MANAGE_READINESS: Final = "programme.manage_readiness"
PROGRAMME_VIEW_DELIVERY: Final = "programme.view_delivery"
PROGRAMME_MANAGE_DELIVERY: Final = "programme.manage_delivery"
PROGRAMME_VIEW_DISCUSSION: Final = "programme.view_discussion"
PROGRAMME_VIEW_PUBLIC_COPY: Final = "programme.view_public_copy"
PROGRAMME_APPROVE_PUBLIC_COPY: Final = "programme.approve_public_copy"

PROGRAMME_CAPABILITY_CODES: Final = frozenset(
    {
        PROGRAMME_VIEW_PRIVATE,
        PROGRAMME_MANAGE_ITEMS,
        PROGRAMME_VIEW_READINESS,
        PROGRAMME_MANAGE_READINESS,
        PROGRAMME_VIEW_DELIVERY,
        PROGRAMME_MANAGE_DELIVERY,
        PROGRAMME_VIEW_DISCUSSION,
        PROGRAMME_VIEW_PUBLIC_COPY,
        PROGRAMME_APPROVE_PUBLIC_COPY,
    }
)


class ProgrammeAuthorizationDeniedError(RuntimeError):
    """Hide whether an actor, edition, authority, or profile caused denial."""

    reason_code = "programme_authorization_denied"


ProgrammeAuthorizationDenied = ProgrammeAuthorizationDeniedError
"""Compatibility alias retained for the concise domain spelling."""


class ProgrammeAuthorizer(Protocol):
    """Evaluate one Programme capability through a trusted policy adapter."""

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Return a complete policy decision rather than a caller boolean.

        Parameters
        ----------
        principal_id : UUID
            The exact current principal identifier.
        organization_id : UUID
            The organization expected to own the edition.
        edition_id : UUID
            The exact edition identifier.
        capability_code : str
            The closed Programme capability to evaluate.
        requested_fields : frozenset[str] | None
            Optional requested fields that must fit the capability ceiling.

        Returns
        -------
        PolicyDecision
            The complete fail-closed policy decision.
        """
        ...


@dataclass(frozen=True, slots=True)
class ExactPolicyProgrammeAuthorizer:
    """Resolve the persisted edition target and invoke the real policy engine."""

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate exact-edition authority against the current profile pair.

        Parameters
        ----------
        principal_id : UUID
            The exact current principal identifier.
        organization_id : UUID
            The organization expected to own the edition.
        edition_id : UUID
            The exact edition identifier.
        capability_code : str
            The closed Programme capability to evaluate.
        requested_fields : frozenset[str] | None
            Optional requested fields that must fit the capability ceiling.

        Returns
        -------
        PolicyDecision
            The ordinary exact-edition policy decision.
        """
        return decide_verified_principal_exact_edition(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )


DEFAULT_PROGRAMME_AUTHORIZER: Final = ExactPolicyProgrammeAuthorizer()


@dataclass(frozen=True, slots=True)
class AuthorizedProgrammeScope:
    """Retain minimized current scope facts and one complete decision.

    Attributes
    ----------
    actor_id
        The reloaded active, verified account identifier.
    organization_id
        The exact organization that owns the authorized edition.
    edition_id
        The exact event edition covered by the decision.
    accepts_private_planning_writes
        Whether the current edition lifecycle accepts private Programme
        mutations.
    decision
        The complete field-aware platform policy decision.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def authorize_programme_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str] | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedProgrammeScope:
    """Reload and authorize one exact Programme scope without disclosing absence.

    Commands and sensitive queries call this seam before work and again at the
    transaction/disclosure boundary.  The default adapter always delegates to
    the platform policy engine; a test harness may substitute a complete
    ``ProgrammeAuthorizer`` decision, never an allow boolean.

    Parameters
    ----------
    actor_id : UUID
        The exact account identifier to reload through Identity.
    organization_id : UUID
        The organization expected to own the edition and series.
    edition_id : UUID
        The exact event edition identifier.
    capability_code : str
        The closed Programme capability to evaluate.
    requested_fields : frozenset[str] | None, default=None
        Optional requested fields that must all be authorized.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The sealed complete-decision adapter.
    lock : bool, default=False
        Whether the owner reference queries acquire row locks.

    Returns
    -------
    AuthorizedProgrammeScope
        The minimized current identifiers, lifecycle admission, and decision.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If the actor is inactive or unverified, the exact tenant scope is
        absent, the capability is unknown, a current profile excludes
        Programme, or the requested field set is not fully authorized.
    """
    if capability_code not in PROGRAMME_CAPABILITY_CODES:
        raise ProgrammeAuthorizationDeniedError
    if authorizer is not DEFAULT_PROGRAMME_AUTHORIZER:
        database_name = connection.settings_dict.get("NAME")
        if (
            not getattr(settings, "MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER", False)
            or not isinstance(database_name, str)
            or not database_name.startswith("test_")
        ):
            raise ProgrammeAuthorizationDeniedError
    actor_reference = resolve_active_verified_account_reference(
        account_id=actor_id,
        lock=lock,
    )
    edition_reference = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    if actor_reference is None or edition_reference is None:
        raise ProgrammeAuthorizationDeniedError
    decision = authorizer.authorize(
        principal_id=actor_reference.account_id,
        organization_id=edition_reference.organization_id,
        edition_id=edition_reference.edition_id,
        capability_code=capability_code,
        requested_fields=requested_fields,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or (
            requested_fields is not None
            and not requested_fields.issubset(decision.fields)
        )
    ):
        raise ProgrammeAuthorizationDeniedError
    return AuthorizedProgrammeScope(
        actor_id=actor_reference.account_id,
        organization_id=edition_reference.organization_id,
        edition_id=edition_reference.edition_id,
        accepts_private_planning_writes=(
            edition_reference.accepts_private_planning_writes
        ),
        decision=decision,
    )


__all__ = [
    "DEFAULT_PROGRAMME_AUTHORIZER",
    "PROGRAMME_APPROVE_PUBLIC_COPY",
    "PROGRAMME_CAPABILITY_CODES",
    "PROGRAMME_MANAGE_DELIVERY",
    "PROGRAMME_MANAGE_ITEMS",
    "PROGRAMME_MANAGE_READINESS",
    "PROGRAMME_VIEW_DELIVERY",
    "PROGRAMME_VIEW_DISCUSSION",
    "PROGRAMME_VIEW_PRIVATE",
    "PROGRAMME_VIEW_PUBLIC_COPY",
    "PROGRAMME_VIEW_READINESS",
    "AuthorizedProgrammeScope",
    "ExactPolicyProgrammeAuthorizer",
    "ProgrammeAuthorizationDenied",
    "ProgrammeAuthorizationDeniedError",
    "ProgrammeAuthorizer",
    "authorize_programme_scope",
]
