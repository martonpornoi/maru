"""Closed Scheduling vocabularies and bounded candidate-history limits."""

from enum import StrEnum
from typing import Final

MAX_SERVICE_DAYS: Final = 32
MAX_RETAINED_SERVICE_DAYS: Final = 128
MAX_OCCURRENCES: Final = 2_000
MAX_CANDIDATES: Final = 100
MAX_REVISIONS: Final = 1_000
MAX_CANDIDATE_REVISIONS: Final = 10_000
MAX_CONFLICTS: Final = 10_000
MAX_CONFLICT_COMPARISONS: Final = 1_000_000
MAX_TITLE_LENGTH: Final = 240
MAX_REASON_LENGTH: Final = 1_000
MAX_SOURCE_CHANNEL_LENGTH: Final = 32
DEFERRED_SCHEDULING_CHECKS: Final = (
    "staffing",
    "rest",
    "accessibility_fit",
    "release_readiness",
)


class SchedulingLifecycle(StrEnum):
    """Planning records remain retained after ordinary work ends."""

    ACTIVE = "active"
    RETIRED = "retired"


class CandidateLifecycle(StrEnum):
    """A private candidate is never approved or published by this vocabulary."""

    DRAFT = "draft"
    ARCHIVED = "archived"


class SchedulingOperation(StrEnum):
    """Closed mutations represented by one immutable command receipt."""

    DAY_CREATE = "day_create"
    DAY_REVISE = "day_revise"
    DAY_RETIRE = "day_retire"
    OCCURRENCE_CREATE = "occurrence_create"
    OCCURRENCE_REVISE = "occurrence_revise"
    OCCURRENCE_RETIRE = "occurrence_retire"
    CANDIDATE_CREATE = "candidate_create"
    CANDIDATE_COPY = "candidate_copy"
    PLACEMENT_SET = "placement_set"
    PLACEMENT_REMOVE = "placement_remove"
    CANDIDATE_RESTORE = "candidate_restore"
    CANDIDATE_ARCHIVE = "candidate_archive"
    EVALUATION_RECORD = "evaluation_record"
    WARNING_ACKNOWLEDGE = "warning_acknowledge"
    RESERVATION_REPLACE = "reservation_replace"
    RESERVATION_CANCEL = "reservation_cancel"


class SchedulingConflictSeverity(StrEnum):
    """Warnings, hard blockers and unavailable checks have different meanings."""

    BLOCKER = "blocker"
    WARNING = "warning"
    UNAVAILABLE = "unavailable"


class SchedulingCapacityMode(StrEnum):
    """The configured Venue ceiling requested for an exact placement."""

    SEATED = "seated"
    STANDING = "standing"
    TABLE = "table"


class SchedulingConflictCode(StrEnum):
    """Explainable closed findings; none is a release or safety approval."""

    EDITION_UNAVAILABLE = "edition_unavailable"
    DAY_CHANGED = "day_changed"
    DAY_RETIRED = "day_retired"
    EDITION_BOUNDS = "edition_bounds"
    DAY_BOUNDS = "day_bounds"
    MINUTE_GRID = "minute_grid"
    OCCURRENCE_CHANGED = "occurrence_changed"
    OCCURRENCE_RETIRED = "occurrence_retired"
    PROGRAMME_UNAVAILABLE = "programme_unavailable"
    ITEM_RETIRED = "item_retired"
    HOST_REQUIRED = "host_required"
    HOST_NOT_CURRENT = "host_not_current"
    HOST_SOURCE_UNAVAILABLE = "host_source_unavailable"
    HOST_UNAVAILABLE = "host_unavailable"
    HOST_OUTSIDE_AVAILABILITY = "host_outside_availability"
    HOST_OUTSIDE_PREFERENCE = "host_outside_preference"
    HOST_OVERLAP = "host_overlap"
    VENUE_UNAVAILABLE = "venue_unavailable"
    VENUE_INACTIVE = "venue_inactive"
    VENUE_CAPACITY = "venue_capacity"
    VENUE_AVAILABILITY_MISSING = "venue_availability_missing"
    VENUE_HARD_AVAILABILITY = "venue_hard_availability"
    CANDIDATE_ROOM_OVERLAP = "candidate_room_overlap"
    RESERVED_ROOM_OVERLAP = "reserved_room_overlap"
    TURNOVER_OVERLAP = "turnover_overlap"
    EVALUATION_LIMIT = "evaluation_limit"


def scheduling_choices(enum_type: type[StrEnum]) -> tuple[tuple[str, str], ...]:
    """Render immutable choices from one closed Scheduling vocabulary.

    Parameters
    ----------
    enum_type : type[StrEnum]
        The owning closed string enum.

    Returns
    -------
    tuple[tuple[str, str], ...]
        Stable stored values and readable labels in declaration order.
    """
    return tuple(
        (member.value, member.value.replace("_", " ").title()) for member in enum_type
    )


def scheduling_values(enum_type: type[StrEnum]) -> tuple[str, ...]:
    """Freeze plain values so migrations never import a mutable current enum.

    Parameters
    ----------
    enum_type : type[StrEnum]
        The owning closed string enum.

    Returns
    -------
    tuple[str, ...]
        Literal strings suitable for historical database constraints.
    """
    return tuple(member.value for member in enum_type)
