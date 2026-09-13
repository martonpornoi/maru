"""Exact-edition, independently ceilinged Scheduling authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from django.conf import settings
from django.db import connection

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
    decide_verified_principal_exact_self,
)
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.identity.queries import resolve_active_verified_person_reference

if TYPE_CHECKING:
    from uuid import UUID

VIEW_PLANNING: Final = "scheduling.view_planning"
VIEW_HOST_SELF: Final = "scheduling.view_host_self"
VIEW_HISTORY: Final = "scheduling.view_history"
VIEW_CONFLICTS: Final = "scheduling.view_conflicts"
MANAGE_DAYS: Final = "scheduling.manage_service_days"
MANAGE_OCCURRENCES: Final = "scheduling.manage_occurrences"
MANAGE_CANDIDATES: Final = "scheduling.manage_candidates"
EVALUATE_CANDIDATES: Final = "scheduling.evaluate_candidates"
ACKNOWLEDGE_WARNINGS: Final = "scheduling.acknowledge_warnings"
MANAGE_RESERVATIONS: Final = "scheduling.manage_reservations"
ACKNOWLEDGE_RELEASE_WARNINGS: Final = "scheduling.acknowledge_release_warnings"
APPROVE_RELEASE: Final = "scheduling.approve_release"
PUBLISH_RELEASE: Final = "scheduling.publish_release"
WITHDRAW_RELEASE: Final = "scheduling.withdraw_release"
SCHEDULING_CAPABILITIES: Final = frozenset(
    {
        VIEW_PLANNING,
        VIEW_HOST_SELF,
        VIEW_HISTORY,
        VIEW_CONFLICTS,
        MANAGE_DAYS,
        MANAGE_OCCURRENCES,
        MANAGE_CANDIDATES,
        EVALUATE_CANDIDATES,
        ACKNOWLEDGE_WARNINGS,
        MANAGE_RESERVATIONS,
        ACKNOWLEDGE_RELEASE_WARNINGS,
        APPROVE_RELEASE,
        PUBLISH_RELEASE,
        WITHDRAW_RELEASE,
    }
)


class SchedulingAuthorizationDeniedError(RuntimeError):
    """Hide which person, scope, field or exact profile caused denial."""

    reason_code = "scheduling_authorization_denied"


class SchedulingAuthorizer(Protocol):
    """Return a complete policy decision rather than a caller approval boolean."""

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Evaluate one closed exact-edition capability and field ceiling.

        Parameters
        ----------
        principal_id : UUID
            Exact current person.
        organization_id : UUID
            Exact owning organization.
        edition_id : UUID
            Exact owning edition.
        capability_code : str
            Closed Scheduling capability.
        requested_fields : frozenset[str] | None
            Independently required code-owned fields.

        Returns
        -------
        PolicyDecision
            The complete ordinary policy result.
        """
        ...


@dataclass(frozen=True, slots=True)
class ExactSchedulingAuthorizer:
    """Delegate to ordinary verified-principal exact-profile policy."""

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Recheck normal policy against the current exact edition target.

        Parameters
        ----------
        principal_id : UUID
            Exact current person.
        organization_id : UUID
            Exact owning organization.
        edition_id : UUID
            Exact owning edition.
        capability_code : str
            Closed Scheduling capability.
        requested_fields : frozenset[str] | None
            Independently required code-owned fields.

        Returns
        -------
        PolicyDecision
            Current exact-profile decision without a foreign model.
        """
        if capability_code == VIEW_HOST_SELF:
            return decide_verified_principal_exact_self(
                principal_id=principal_id,
                owner_account_id=principal_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=capability_code,
                requested_fields=requested_fields,
            )
        return decide_verified_principal_exact_edition(
            principal_id=principal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
        )


DEFAULT_SCHEDULING_AUTHORIZER: Final = ExactSchedulingAuthorizer()


@dataclass(frozen=True, slots=True)
class AuthorizedSchedulingScope:
    """Retain only validated scope, current edition version and ordinary decision.

    Attributes
    ----------
    actor_id
        Current verified person identifier.
    organization_id
        Exact organization owning edition and series.
    edition_id
        Exact edition authorized by normal policy.
    edition_version
        Current Events dependency version.
    accepts_writes
        Events-owned scheduling lifecycle consequence.
    decision
        Complete independently ceilinged policy decision.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    edition_version: int
    accepts_writes: bool
    decision: PolicyDecision


def authorize_scheduling_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str] | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedSchedulingScope:
    """Resolve trusted owner facts before releasing private input or state.

    Parameters
    ----------
    actor_id : UUID
        Current person to authorize.
    organization_id : UUID
        Expected exact organization.
    edition_id : UUID
        Expected exact edition.
    capability_code : str
        Closed Scheduling capability.
    requested_fields : frozenset[str] | None, default=None
        Independent protected-read field requirements.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy or doubly gated isolated-test admission substitute.
    lock : bool, default=False
        Whether to acquire edition then actor locks. Multi-person callers must
        first acquire their complete canonical person set through its owner.

    Returns
    -------
    AuthorizedSchedulingScope
        Exact current scope and complete decision.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        For every absent, inactive, foreign, unadopted or insufficient scope.
    """
    if capability_code not in SCHEDULING_CAPABILITIES:
        raise SchedulingAuthorizationDeniedError
    if authorizer is not DEFAULT_SCHEDULING_AUTHORIZER:
        database_name = connection.settings_dict.get("NAME")
        if (
            not getattr(settings, "MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER", False)
            or not isinstance(database_name, str)
            or not database_name.startswith("test_")
        ):
            raise SchedulingAuthorizationDeniedError
    edition = resolve_scheduling_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=lock,
    )
    actor = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
    if edition is None or actor is None:
        raise SchedulingAuthorizationDeniedError
    decision = authorizer.authorize(
        principal_id=actor.account_id,
        organization_id=edition.organization_id,
        edition_id=edition.edition_id,
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
        raise SchedulingAuthorizationDeniedError
    return AuthorizedSchedulingScope(
        actor.account_id,
        edition.organization_id,
        edition.edition_id,
        edition.version,
        edition.accepts_scheduling_writes,
        decision,
    )
