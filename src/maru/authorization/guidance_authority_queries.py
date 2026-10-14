"""Purpose-specific Guidance team and current-root references, without a directory."""

from dataclasses import dataclass
from uuid import UUID

from django.utils import timezone

from maru.authorization.guidance_catalog import (
    GUIDANCE_BOOTSTRAP_CAPABILITY,
    GUIDANCE_CONTROL_CAPABILITY,
    GUIDANCE_TEAM_LABEL,
)
from maru.authorization.models import (
    AuthorityIssuance,
    GuidanceAuthoritySetupReceipt,
    GuidanceTeam,
)
from maru.authorization.policy import (
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.provenance import authority_issuance_is_current
from maru.events.knowledge_scope import resolve_knowledge_edition_scope
from maru.identity.queries import resolve_active_verified_person_reference
from maru.organizations.guidance_activation_references import (
    guidance_accountable_foundation,
)

_INDEPENDENT_PAIR_SIZE = 2


@dataclass(frozen=True, slots=True)
class GuidanceRootSource:
    """Resolve stable Guidance ownership and current responsibility.

    Exact current organization-root issuance selected from its accepted appointment.

    Attributes
    ----------
    account_id : UUID
        Current verified person holding the accepted organization root.
    assignment_id : UUID
        Exact accepted organization-root role assignment.
    issuance_ordinal : int
        Original root issuance ordinal pinned by downstream qualification.
    """

    account_id: UUID
    assignment_id: UUID
    issuance_ordinal: int


@dataclass(frozen=True, slots=True)
class GuidanceTeamReference:
    """Stable historical ownership and separately computed current team readiness.

    Attributes
    ----------
    team_id : UUID
        Stable edition team identity retained across later recovery ceremonies.
    team_label : str
        Canonical retained team label for ownership evidence.
    activation_receipt_id : UUID
        Original activation receipt establishing historical team ownership.
    ready : bool
        Whether the team currently has the required qualified controller pair.
    """

    team_id: UUID
    team_label: str
    activation_receipt_id: UUID
    ready: bool


def guidance_root_sources(
    *, organization_id: UUID, lock: bool = False
) -> tuple[GuidanceRootSource, ...]:
    """Return only active accepted root identities with exact current lineage.

    Parameters
    ----------
    organization_id : UUID
        Exact organization owning the requested scope.
    lock : bool, default=False
        Lock the exact current lineage while validating its authority.

    Returns
    -------
    tuple[GuidanceRootSource, ...]
        The admitted immutable result; it grants no additional authority.
    """
    foundation = guidance_accountable_foundation(
        organization_id=organization_id, for_update=lock
    )
    target = resolve_organization_target(organization_id=organization_id)
    if (
        foundation is None
        or target is None
        or not foundation.organization_active
        or foundation.representation_state != "active"
    ):
        return ()
    now = timezone.now()
    result = []
    for root in foundation.roots:
        if (
            resolve_active_verified_person_reference(
                account_id=root.account_id, lock=lock
            )
            is None
        ):
            continue
        query = AuthorityIssuance.objects.filter(role_assignment_id=root.assignment_id)
        if lock:
            query = query.select_for_update()
        issuance = query.first()
        if issuance is not None and authority_issuance_is_current(
            issuance_ordinal=issuance.ordinal,
            principal_id=root.account_id,
            capability_code=GUIDANCE_BOOTSTRAP_CAPABILITY,
            target=target,
            requested_effective_from=now,
            requested_expires_at=None,
            evaluated_at=now,
            lock=lock,
        ):
            result.append(
                GuidanceRootSource(
                    root.account_id, root.assignment_id, issuance.ordinal
                )
            )
    return tuple(result)


def guidance_team_reference(
    *, organization_id: UUID, edition_id: UUID
) -> GuidanceTeamReference | None:
    """Resolve purpose-qualified Guidance access.

    Expose no people or content; current qualification never rebinds old
    descendants.

    Parameters
    ----------
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.

    Returns
    -------
    GuidanceTeamReference | None
        The admitted immutable result; it grants no additional authority.
    """
    from maru.authorization.guidance_readiness import (  # noqa: PLC0415
        guidance_authority_database_integrity_is_ready,
    )

    if not guidance_authority_database_integrity_is_ready():
        return None
    if (
        resolve_knowledge_edition_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        is None
    ):
        return None
    team = GuidanceTeam.objects.filter(
        organization_id=organization_id, edition_id=edition_id
    ).first()
    if team is None:
        return None
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    ready = False
    now = timezone.now()
    if target is not None:
        for setup in GuidanceAuthoritySetupReceipt.objects.filter(
            team_id=team.id
        ).order_by("-created_at", "-id"):
            assignments = (setup.controller_a_id, setup.controller_b_id)
            issuances = tuple(
                AuthorityIssuance.objects.filter(
                    role_assignment_id__in=assignments
                ).select_related("role_assignment")
            )
            if len(issuances) == _INDEPENDENT_PAIR_SIZE and all(
                issuance.role_assignment is not None
                and resolve_active_verified_person_reference(
                    account_id=issuance.role_assignment.principal_id
                )
                is not None
                and authority_issuance_is_current(
                    issuance_ordinal=issuance.ordinal,
                    principal_id=issuance.role_assignment.principal_id,
                    capability_code=GUIDANCE_CONTROL_CAPABILITY,
                    target=target,
                    requested_effective_from=now,
                    requested_expires_at=None,
                    evaluated_at=now,
                )
                for issuance in issuances
            ):
                ready = True
                break
    return GuidanceTeamReference(
        team.id, GUIDANCE_TEAM_LABEL, team.original_activation_id, ready
    )
