"""Policy-narrow organizer relationship and platform inventory queries."""

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from django.db.models import Count, QuerySet

from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation_catalog import representation_definition

OrganizationGovernanceState = Literal[
    "absent",
    "provisioning",
    "active",
    "suspended",
]


@dataclass(frozen=True, slots=True)
class OrganizationGovernanceAnchor:
    """The minimized, identity-free governance anchor used by structure views.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    label
        The human-readable label shown to authorized readers.
    state
        The lifecycle state to evaluate or expose.
    purpose
        The truthful responsibility boundary for the representation.
    """

    kind: Literal["governance"]
    label: str
    state: OrganizationGovernanceState
    purpose: str


ExecutiveBoardState = OrganizationGovernanceState
ExecutiveBoardAnchor = OrganizationGovernanceAnchor


def organization_governance_anchor(
    *,
    organization_id: UUID,
) -> OrganizationGovernanceAnchor:
    """Return minimized accountable-representation state for one organization.

    This public module query deliberately exposes no appointment, controller,
    membership, reason, account, or authority information. Callers must
    authorize the exact organization or edition before invoking it.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.

    Returns
    -------
    OrganizationGovernanceAnchor
        The truthful identity-free organization governance anchor.
    """
    representation = (
        OrganizationRepresentation.objects.filter(organization_id=organization_id)
        .values("code", "name", "state")
        .first()
    )
    state = representation["state"] if representation is not None else None
    if state not in {
        OrganizationRepresentation.State.PROVISIONING,
        OrganizationRepresentation.State.ACTIVE,
        OrganizationRepresentation.State.SUSPENDED,
    }:
        anchor_state: OrganizationGovernanceState = "absent"
    else:
        anchor_state = cast("OrganizationGovernanceState", state)
    definition = (
        representation_definition(str(representation["code"]))
        if representation is not None
        else None
    )
    return OrganizationGovernanceAnchor(
        kind="governance",
        label=(
            str(representation["name"])
            if representation is not None
            else "Accountable representation"
        ),
        state=anchor_state,
        purpose=(
            definition.purpose
            if definition is not None
            else "No accountable Maru representation has been established yet."
        ),
    )


def executive_board_governance_anchor(
    *,
    organization_id: UUID,
) -> ExecutiveBoardAnchor:
    """Return the compatible minimized organization-governance projection.

    This public module query deliberately exposes no appointment, controller,
    membership, reason, account, or authority information. Callers must
    authorize the exact organization/edition before invoking it.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.

    Returns
    -------
    ExecutiveBoardAnchor
        The resolved ExecutiveBoardAnchor for executive board governance anchor.
    """
    return organization_governance_anchor(organization_id=organization_id)


def platform_organization_inventory() -> QuerySet[Organization]:
    """Return the C1 organizer inventory for the platform administration page.

    Returns
    -------
    QuerySet[Organization]
        The matching platform organization inventory records in deterministic
        order.
    """
    return Organization.objects.annotate(
        series_count=Count("convention_series", distinct=True),
        edition_count=Count("event_editions", distinct=True),
    ).order_by("name", "id")


def memberships_for_account(
    account: Account,
) -> QuerySet[OrganizationMembership]:
    """Return memberships for account visible to the caller.

    Parameters
    ----------
    account : Account
        The account used to constrain the tenant-scoped query.

    Returns
    -------
    QuerySet[OrganizationMembership]
        The authorized memberships for account records in deterministic order.
    """
    return (
        OrganizationMembership.objects.filter(account=account)
        .select_related("organization")
        .order_by("organization__name", "organization_id")
    )


def known_organization_person_account_ids(
    *,
    organization_id: UUID,
    limit: int,
) -> tuple[UUID, ...]:
    """Return a bounded set of accounts with a current organization relation.

    Workforce and other owning modules may use this identifier-only query only
    after authorizing their own restricted workflow.  It deliberately returns
    no identity label or contact field; Identity remains responsible for the
    final active-person projection.

    Parameters
    ----------
    organization_id : UUID
        Organization whose current memberships or Board appointments are known.
    limit : int
        Hard upper bound for the complete result.

    Returns
    -------
    tuple[UUID, ...]
        Stable account identifiers from current organization relationships.

    Raises
    ------
    RuntimeError
        If the complete relationship set exceeds the caller's safe bound.
    """
    membership_ids = OrganizationMembership.objects.filter(
        organization_id=organization_id,
        state__in=(
            OrganizationMembership.State.INVITED,
            OrganizationMembership.State.ACTIVE,
        ),
    ).values_list("account_id", flat=True)
    appointment_ids = RepresentationAppointment.objects.filter(
        representation__organization_id=organization_id,
        state__in=(
            RepresentationAppointment.State.INVITED,
            RepresentationAppointment.State.ACCEPTED,
            RepresentationAppointment.State.ACTIVE,
        ),
    ).values_list("account_id", flat=True)
    account_ids = tuple(
        sorted(
            set(membership_ids).union(appointment_ids),
            key=str,
        )
    )
    if len(account_ids) > limit:
        raise RuntimeError("The organization person relationship limit was exceeded.")
    return account_ids
