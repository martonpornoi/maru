"""Actual-actor, exact-profile and field-ceiling authorization."""

from dataclasses import dataclass

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.announcements_scope import (
    AnnouncementsEditionScope,
    resolve_announcements_edition_scope,
)

from .catalog import CAPABILITY_FIELDS
from .contracts import AnnouncementReadRequest
from .errors import AnnouncementDeniedError
from .inputs import identifier


@dataclass(frozen=True, slots=True)
class AuthorizedAnnouncementScope:
    """Current owner facts and the independently admitted actor decision.

    Attributes
    ----------
    edition : AnnouncementsEditionScope
        Events-owned adoption, lifecycle and locale facts for the exact scope.
    decision : PolicyDecision
        Current capability and field admission for the authenticated actor.
    """

    edition: AnnouncementsEditionScope
    decision: PolicyDecision


def authorize_announcements_scope(
    request: AnnouncementReadRequest,
    *,
    capability: str,
    fields: frozenset[str] = frozenset(),
) -> AuthorizedAnnouncementScope:
    """Admit the exact scope and every required field without disclosing labels.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    capability : str
        Exact edition capability required for this operation.
    fields : frozenset[str], default=frozenset()
        Every public contract field required before loading protected values.

    Returns
    -------
    AuthorizedAnnouncementScope
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    AnnouncementDeniedError
        If scope, input, state or retained evidence fails the owning contract.
    """
    for value in (
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    ):
        identifier(value)
    if capability not in CAPABILITY_FIELDS:
        raise AnnouncementDeniedError
    required = fields or CAPABILITY_FIELDS[capability]
    decision = decide_verified_principal_exact_edition(
        principal_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=capability,
        requested_fields=required,
    )
    if not decision.allowed or not required <= decision.fields:
        raise AnnouncementDeniedError
    edition = resolve_announcements_edition_scope(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if edition is None:
        raise AnnouncementDeniedError
    return AuthorizedAnnouncementScope(edition, decision)


def can_use(request: AnnouncementReadRequest, capability: str) -> bool:
    """Project current action admission without treating navigation as authority.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    capability : str
        Exact edition capability required for this operation.

    Returns
    -------
    bool
        The complete validated result; failures do not return partial evidence.
    """
    try:
        authorize_announcements_scope(request, capability=capability)
    except AnnouncementDeniedError:
        return False
    return True
