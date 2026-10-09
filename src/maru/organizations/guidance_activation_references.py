"""Organization-owned accountable foundation facts for the Guidance ceremony."""

from dataclasses import dataclass
from uuid import UUID

from maru.organizations.models import (
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation_catalog import (
    ANNOUNCEMENTS_OPERATORS,
    EXECUTIVE_BOARD,
    WORKSPACE_OPERATORS,
    representation_definition,
)

_MAX_ROOT_REFERENCES = 256


@dataclass(frozen=True, slots=True)
class GuidanceRootReference:
    """Resolve the original accepted responsibility evidence.

    Identify one actual linked root; Authorization independently checks its lineage.

    Attributes
    ----------
    account_id : UUID
        Person linked to one accepted accountable-representation appointment.
    assignment_id : UUID
        Linked root assignment; Authorization must independently check its
        lineage.
    """

    account_id: UUID
    assignment_id: UUID


@dataclass(frozen=True, slots=True)
class GuidanceAccountableFoundation:
    """Minimized owner state, including an inactive foundation's honest next step.

    Attributes
    ----------
    organization_id : UUID
        Exact organization owning this event and its evidence.
    organization_slug : str
        Canonical organization slug for scoped navigation.
    organization_name : str
        Admitted organization display name.
    representation_id : UUID
        Identity of the organization accountable representation.
    representation_code : str
        Exact purpose code of the accountable representation.
    representation_version : int
        Current aggregate version of the accountable representation.
    representation_state : str
        Current lifecycle state of the accountable representation.
    organization_active : bool
        Whether the owning organization has an active lifecycle.
    roots : tuple[GuidanceRootReference, ...]
        Accepted linked organization roots, without asserting their current
        lineage.
    """

    organization_id: UUID
    organization_slug: str
    organization_name: str
    representation_id: UUID
    representation_code: str
    representation_version: int
    representation_state: str
    organization_active: bool
    roots: tuple[GuidanceRootReference, ...]


def guidance_accountable_foundation(
    *, organization_id: UUID, for_update: bool = False
) -> GuidanceAccountableFoundation | None:
    """Resolve an exact foundation after caller admission; this grants no authority.

    Parameters
    ----------
    organization_id : UUID
        Exact organization owning the requested scope.
    for_update : bool, default=False
        Acquire owner locks inside the caller's active transaction.

    Returns
    -------
    GuidanceAccountableFoundation | None
        The admitted immutable result; it grants no additional authority.
    """
    query = OrganizationRepresentation.objects.select_related("organization").filter(
        organization_id=organization_id
    )
    if for_update:
        query = query.select_for_update(of=("self",))
    row = query.first()
    if (
        row is None
        or row.code
        not in {
            EXECUTIVE_BOARD.code,
            ANNOUNCEMENTS_OPERATORS.code,
            WORKSPACE_OPERATORS.code,
        }
        or representation_definition(row.code) is None
    ):
        return None
    appointments = RepresentationAppointment.objects.filter(
        representation_id=row.id,
        state="active",
        role="controller",
        role_assignment_id__isnull=False,
    ).order_by("account_id")
    if for_update:
        appointments = appointments.select_for_update()
    roots = tuple(
        GuidanceRootReference(account_id=account_id, assignment_id=assignment_id)
        for account_id, assignment_id in appointments.values_list(
            "account_id", "role_assignment_id"
        )[:257]
    )
    if len(roots) > _MAX_ROOT_REFERENCES:
        return None
    return GuidanceAccountableFoundation(
        organization_id=organization_id,
        organization_slug=row.organization.slug,
        organization_name=row.organization.name,
        representation_id=row.id,
        representation_code=row.code,
        representation_version=row.aggregate_version,
        representation_state=row.state,
        organization_active=row.organization.lifecycle == "active",
        roots=roots,
    )
