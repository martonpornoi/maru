"""Closed vocabulary and field ceilings for explicit Programme hosting."""

from enum import StrEnum
from typing import Final

MAX_HOSTS_PER_ITEM: Final = 100
MAX_HOST_REVISIONS: Final = 1_000
MAX_HOST_AVAILABILITY_PERIODS: Final = 128
MAX_HOST_INVITATION_TITLE: Final = 240
MAX_HOST_BRIEFING: Final = 2_000


class ProgrammeHostRole(StrEnum):
    """Purpose roles that never imply organizer or attendee authority."""

    HOST = "host"
    CO_HOST = "co_host"


class ProgrammeHostState(StrEnum):
    """Current relationship states with retained independent person decisions."""

    INVITED = "invited"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"


class ProgrammeHostResponse(StrEnum):
    """Person-owned actions on an exact invitation or confirmed relationship."""

    CONFIRM = "confirm"
    DECLINE = "decline"
    WITHDRAW = "withdraw"


class ProgrammeHostAvailabilityState(StrEnum):
    """Sharing states; a shared empty set explicitly means unavailable."""

    UNKNOWN = "unknown"
    DRAFT = "draft"
    SHARED = "shared"
    WITHDRAWN = "withdrawn"


class ProgrammeHostAvailabilityKind(StrEnum):
    """Positive availability intervals, distinct from retained commitments."""

    AVAILABLE = "available"
    PREFERRED = "preferred"


HOST_SELF_FIELDS: Final = frozenset(
    {"own_host_relationship", "own_host_invitation", "own_host_availability"}
)
HOST_ROSTER_FIELDS: Final = frozenset({"host_roster", "host_history"})
HOST_AVAILABILITY_FIELDS: Final = frozenset({"shared_host_availability"})
HOST_TERMINAL_STATES: Final = frozenset(
    {
        ProgrammeHostState.DECLINED.value,
        ProgrammeHostState.WITHDRAWN.value,
        ProgrammeHostState.REMOVED.value,
    }
)
