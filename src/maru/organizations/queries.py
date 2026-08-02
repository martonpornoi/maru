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
)

ExecutiveBoardState = Literal[
    "absent",
    "provisioning",
    "active",
    "suspended",
]


@dataclass(frozen=True, slots=True)
class ExecutiveBoardAnchor:
    """The fixed, identity-free governance anchor used by structure views."""

    kind: Literal["governance"]
    label: str
    state: ExecutiveBoardState


def executive_board_governance_anchor(
    *,
    organization_id: UUID,
) -> ExecutiveBoardAnchor:
    """Return the minimized Executive Board state for one exact organization.

    This public module query deliberately exposes no appointment, controller,
    membership, reason, account, or authority information. Callers must
    authorize the exact organization/edition before invoking it.
    """

    state = (
        OrganizationRepresentation.objects.filter(
            organization_id=organization_id,
            code=OrganizationRepresentation.EXECUTIVE_BOARD_CODE,
        )
        .values_list("state", flat=True)
        .first()
    )
    if state not in {
        OrganizationRepresentation.State.PROVISIONING,
        OrganizationRepresentation.State.ACTIVE,
        OrganizationRepresentation.State.SUSPENDED,
    }:
        anchor_state: ExecutiveBoardState = "absent"
    else:
        anchor_state = cast(ExecutiveBoardState, state)
    return ExecutiveBoardAnchor(
        kind="governance",
        label=OrganizationRepresentation.EXECUTIVE_BOARD_NAME,
        state=anchor_state,
    )


def platform_organization_inventory() -> QuerySet[Organization]:
    """Return the C1 organizer inventory for the platform administration page."""

    return Organization.objects.annotate(
        series_count=Count("convention_series", distinct=True),
        edition_count=Count("event_editions", distinct=True),
    ).order_by("name", "id")


def memberships_for_account(
    account: Account,
) -> QuerySet[OrganizationMembership]:
    return (
        OrganizationMembership.objects.filter(account=account)
        .select_related("organization")
        .order_by("organization__name", "organization_id")
    )
