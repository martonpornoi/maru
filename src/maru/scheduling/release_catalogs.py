"""Closed native dependency identities; source owners still authenticate references."""

from enum import StrEnum
from typing import Final


class ReleaseDependencyKind(StrEnum):
    """Native ongoing-safety or disclosure dependency, never an arbitrary source key."""

    EDITION_OPERATIONAL = "edition_operational"
    PROGRAMME_ITEM = "programme_item"
    PROGRAMME_HOST_OPERATIONAL = "programme_host_operational"
    PROGRAMME_HOST_DISCLOSURE = "programme_host_disclosure"
    PROGRAMME_PUBLIC_COPY = "programme_public_copy"
    WORKFORCE_DEMAND = "workforce_demand"
    WORKFORCE_ASSIGNMENT = "workforce_assignment"
    WORKFORCE_AVAILABILITY = "workforce_availability"
    WORKFORCE_PERSON_OBLIGATIONS = "workforce_person_obligations"
    VENUE_PROPERTY = "venue_property"
    VENUE_MEMBER = "venue_member"
    VENUE_SELECTION = "venue_selection"
    VENUE_BOOKING = "venue_booking"
    IDENTITY_ACCOUNT = "identity_account"


GLOBAL_RELEASE_DEPENDENCIES: Final = frozenset(
    {
        ReleaseDependencyKind.IDENTITY_ACCOUNT,
        ReleaseDependencyKind.WORKFORCE_PERSON_OBLIGATIONS,
    }
)
ORGANIZATION_RELEASE_DEPENDENCIES: Final = frozenset(
    {ReleaseDependencyKind.VENUE_PROPERTY, ReleaseDependencyKind.VENUE_MEMBER}
)
EDITION_RELEASE_DEPENDENCIES: Final = (
    frozenset(ReleaseDependencyKind)
    - GLOBAL_RELEASE_DEPENDENCIES
    - ORGANIZATION_RELEASE_DEPENDENCIES
)
