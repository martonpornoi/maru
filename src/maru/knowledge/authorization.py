"""Actual-actor, exact-profile and field-ceiling authorization."""

from dataclasses import dataclass

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.knowledge_scope import (
    KnowledgeEditionScope,
    resolve_knowledge_edition_scope,
)

from .catalog import CAPABILITY_FIELDS
from .contracts import GuidanceReadRequest
from .errors import GuidanceDeniedError
from .inputs import identifier


@dataclass(frozen=True, slots=True)
class AuthorizedGuidanceScope:
    """Current owner facts and the independently admitted actor decision.

    Attributes
    ----------
    edition : KnowledgeEditionScope
        Events-owned adoption, lifecycle and locale facts for the exact scope.
    decision : PolicyDecision
        Current capability and field admission for the authenticated actor.
    """

    edition: KnowledgeEditionScope
    decision: PolicyDecision


def authorize_guidance_scope(
    request: GuidanceReadRequest,
    *,
    capability: str,
    fields: frozenset[str] = frozenset(),
) -> AuthorizedGuidanceScope:
    """Admit the exact scope and every required field without disclosing labels.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual authenticated actor and exact organization/edition context.
    capability : str
        Exact edition capability required for this operation.
    fields : frozenset[str], default=frozenset()
        Every public contract field required before loading protected values.

    Returns
    -------
    AuthorizedGuidanceScope
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    GuidanceDeniedError
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
        raise GuidanceDeniedError
    required = fields or CAPABILITY_FIELDS[capability]
    decision = decide_verified_principal_exact_edition(
        principal_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=capability,
        requested_fields=required,
    )
    if not decision.allowed or not required <= decision.fields:
        raise GuidanceDeniedError
    edition = resolve_knowledge_edition_scope(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if edition is None:
        raise GuidanceDeniedError
    return AuthorizedGuidanceScope(edition, decision)


def can_use(
    request: GuidanceReadRequest,
    capability: str,
    *,
    fields: frozenset[str] = frozenset(),
) -> bool:
    """Project current action admission without treating navigation as authority.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual authenticated actor and exact organization/edition context.
    capability : str
        Exact edition capability required for this operation.
    fields : frozenset[str], default=frozenset()
        Specific independently admitted projection fields; empty means all fields.

    Returns
    -------
    bool
        The complete validated result; failures do not return partial evidence.
    """
    try:
        authorize_guidance_scope(request, capability=capability, fields=fields)
    except GuidanceDeniedError:
        return False
    return True
