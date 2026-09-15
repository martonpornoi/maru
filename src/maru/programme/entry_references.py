"""Minimized Programme item-entry policy without inventory or mutation authority."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import (
    ActiveVerifiedAccountReference,
    resolve_active_verified_account_reference,
)

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_ITEMS,
    ProgrammeAuthorizationDeniedError,
)
from .scope_references import resolve_private_planning_edition_reference


@dataclass(frozen=True, slots=True)
class ProgrammeItemEntryReference:
    """Carry exact owner facts and a complete item-task policy decision.

    Attributes
    ----------
    actor_id
        Exact current active verified account.
    organization_id
        Expected organization owning the edition.
    edition_id
        Exact private-planning edition, not a discovered edition.
    accepts_private_planning_writes
        Current lifecycle hint, not command admission.
    decision
        Complete no-content-field policy, including ordinary absent permission.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    accepts_private_planning_writes: bool
    decision: PolicyDecision


def resolve_programme_item_entry_reference(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> ProgrammeItemEntryReference:
    """Inspect current item-entry policy without hiding dependency failures.

    Parameters
    ----------
    actor_id : UUID
        Authenticated account to reload, not an impersonation selector.
    organization_id : UUID
        Exact expected organization, not a directory filter.
    edition_id : UUID
        Exact edition whose independent item-management policy is requested.

    Returns
    -------
    ProgrammeItemEntryReference
        Identifier-only owner proof and complete allowed/ordinary-absent decision.
        The caller audits any protected labelled projection before disclosure.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If identifiers, current owner facts or complete policy are incoherent.

    Notes
    -----
    Uses only the real default Programme policy adapter; there is no substitute
    authorizer parameter. This reference grants no private item read or mutation.
    Callers repeat it at disclosure and destinations authorize independently.
    """
    if not all(
        isinstance(value, UUID) and value.int
        for value in (actor_id, organization_id, edition_id)
    ):
        raise ProgrammeAuthorizationDeniedError
    actor = resolve_active_verified_account_reference(account_id=actor_id)
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if (
        not isinstance(actor, ActiveVerifiedAccountReference)
        or actor.account_id != actor_id
        or not isinstance(edition, PrivatePlanningEditionReference)
        or edition.organization_id != organization_id
        or edition.edition_id != edition_id
        or type(edition.accepts_private_planning_writes) is not bool
    ):
        raise ProgrammeAuthorizationDeniedError
    decision = DEFAULT_PROGRAMME_AUTHORIZER.authorize(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset(),
    )
    if (
        not isinstance(decision, PolicyDecision)
        or type(decision.allowed) is not bool
        or decision.policy_version != POLICY_VERSION
        or type(decision.fields) is not frozenset
        or decision.fields
        or type(decision.obligations) is not frozenset
        or type(decision.reason_code) is not str
        or not (
            (
                decision.allowed
                and decision.reason_code
                in {"direct_grant", "role_assignment", "platform_administration"}
                and decision.obligations == frozenset({"reason", "audit"})
            )
            or (
                not decision.allowed
                and decision.reason_code == "permission_absent"
                and not decision.obligations
            )
        )
    ):
        raise ProgrammeAuthorizationDeniedError
    return ProgrammeItemEntryReference(
        actor_id,
        organization_id,
        edition_id,
        edition.accepts_private_planning_writes,
        decision,
    )


__all__ = ["ProgrammeItemEntryReference", "resolve_programme_item_entry_reference"]
