"""Pure exact-journal temporal rules; never owner authentication or serving proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.core.exceptions import ValidationError


class ReleaseDependencyHorizon(StrEnum):
    """Separate approval attribution, bounded work and ongoing disclosure."""

    APPROVAL_ONLY = "approval_only"
    OPERATIONAL = "operational"
    DISCLOSURE = "disclosure"


class ReleaseDependencyUse(StrEnum):
    """A new approval has stricter freshness than historical normal serving."""

    APPROVAL = "approval"
    SERVING = "serving"


class ReleaseDependencyConsequence(StrEnum):
    """Complete current evidence, stale approval, invalidation or missing proof."""

    CURRENT = "current"
    STALE = "stale"
    INVALIDATED = "invalidated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReleaseDependencyChangeWindow:
    """Minimized complete journal aggregation supplied by its trusted owner.

    Attributes
    ----------
    count
        Number of unique changes strictly after the captured generation through
        the exact current generation. The database must enforce uniqueness.
    first_generation
        Lowest selected generation, or absence for an empty range.
    last_generation
        Highest selected generation, or absence for an empty range.
    earliest_changed_at
        Earliest authoritative recorded time in that complete range, not the
        caller's desired effective date or the time of the latest change.
    """

    count: int
    first_generation: int | None
    last_generation: int | None
    earliest_changed_at: datetime | None


class ReleaseDependencyEvidenceInvalidError(ValidationError):
    """Reject malformed dependency evidence without private source details."""

    def __init__(self) -> None:
        """Use one stable content-free validation reason."""
        super().__init__(
            "Exact complete release dependency evidence is required.",
            code="scheduling_release_dependency_invalid",
        )


def _aware(value: object) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def evaluate_release_dependency(
    *,
    captured_generation: int,
    current_generation: int,
    horizon: ReleaseDependencyHorizon,
    use: ReleaseDependencyUse,
    operational_ends_at: datetime | None,
    changes: ReleaseDependencyChangeWindow,
) -> ReleaseDependencyConsequence:
    """Interpret exact source changes without retroactively rewriting completed work.

    Parameters
    ----------
    captured_generation : int
        Positive generation retained with the exact approval or release dependency.
    current_generation : int
        Current owner-locked generation, never a caller freshness assertion.
    horizon : ReleaseDependencyHorizon
        Code-owned purpose of this exact dependency.
    use : ReleaseDependencyUse
        New approval or checked normal serving, selected by the owning consumer.
    operational_ends_at : datetime | None
        Immutable aware half-open obligation end, required only for operational
        dependencies. It must not be moved to make an invalidation disappear.
    changes : ReleaseDependencyChangeWindow
        Owner-authenticated complete unique journal aggregation for the range.

    Returns
    -------
    ReleaseDependencyConsequence
        Missing/inconsistent ranges are unavailable. Any complete change stales
        approval; serving uses purpose and the earliest recorded change time.

    Raises
    ------
    ReleaseDependencyEvidenceInvalidError
        If trusted evidence has malformed types, bounds, purpose or time shape.

    Notes
    -----
    This function authenticates no owner, source, unique sequence or timestamp.
    It cannot be exposed as a caller-controlled permission or artifact check.
    """
    if (
        any(
            type(value) is not int or not 1 <= value < 2**63 - 1
            for value in (captured_generation, current_generation)
        )
        or type(horizon) is not ReleaseDependencyHorizon
        or type(use) is not ReleaseDependencyUse
        or type(changes) is not ReleaseDependencyChangeWindow
    ):
        raise ReleaseDependencyEvidenceInvalidError
    if horizon is ReleaseDependencyHorizon.OPERATIONAL:
        if not _aware(operational_ends_at):
            raise ReleaseDependencyEvidenceInvalidError
    elif operational_ends_at is not None:
        raise ReleaseDependencyEvidenceInvalidError
    if type(changes.count) is not int or not 0 <= changes.count < 2**63 - 1:
        raise ReleaseDependencyEvidenceInvalidError
    if any(
        value is not None and (type(value) is not int or not 1 <= value < 2**63 - 1)
        for value in (changes.first_generation, changes.last_generation)
    ):
        raise ReleaseDependencyEvidenceInvalidError
    if changes.earliest_changed_at is not None and not _aware(
        changes.earliest_changed_at
    ):
        raise ReleaseDependencyEvidenceInvalidError
    gap = current_generation - captured_generation
    if gap < 0 or changes.count != gap:
        return ReleaseDependencyConsequence.UNAVAILABLE
    if gap == 0:
        return (
            ReleaseDependencyConsequence.CURRENT
            if changes.first_generation is None
            and changes.last_generation is None
            and changes.earliest_changed_at is None
            else ReleaseDependencyConsequence.UNAVAILABLE
        )
    if (
        changes.first_generation != captured_generation + 1
        or changes.last_generation != current_generation
        or changes.earliest_changed_at is None
    ):
        return ReleaseDependencyConsequence.UNAVAILABLE
    if use is ReleaseDependencyUse.APPROVAL:
        return ReleaseDependencyConsequence.STALE
    invalidated = horizon is ReleaseDependencyHorizon.DISCLOSURE or (
        horizon is ReleaseDependencyHorizon.OPERATIONAL
        and operational_ends_at is not None
        and changes.earliest_changed_at < operational_ends_at
    )
    return (
        ReleaseDependencyConsequence.INVALIDATED
        if invalidated
        else ReleaseDependencyConsequence.CURRENT
    )
