"""Pure editor time and comparison contracts, never permission or persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError

from .time_rules import normalize_scheduling_instant

if TYPE_CHECKING:
    from uuid import UUID

    from .planning_queries import PlanningPlacement

_MINUTE_INPUT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?\Z"
)


def parse_planning_minute(value: str, *, zone_name: str) -> datetime:
    """Resolve an explicit offset or one unambiguous minute in the edition zone.

    Parameters
    ----------
    value : str
        Exact ISO minute, optionally carrying a UTC offset or Z suffix.
    zone_name : str
        Events-owned IANA zone; never inferred from the browser or machine.

    Returns
    -------
    datetime
        Whole-minute UTC instant without rounding, guessing a fold or gap repair.

    Raises
    ------
    ValidationError
        For malformed input, an invalid zone, an impossible local minute, an
        ambiguous local minute without offset, or an unrepresentable UTC instant.
    """
    if not isinstance(value, str) or _MINUTE_INPUT.fullmatch(value) is None:
        raise ValidationError(
            "Enter YYYY-MM-DDTHH:MM, optionally followed by Z or an explicit offset.",
            code="scheduling_minute_invalid",
        )
    try:
        zone = ZoneInfo(zone_name)
        local = datetime.fromisoformat(value)
        if local.tzinfo is not None:
            return normalize_scheduling_instant(local, field="time")
        candidates = {
            aware.astimezone(UTC)
            for fold in (0, 1)
            if (aware := local.replace(tzinfo=zone, fold=fold))
            .astimezone(UTC)
            .astimezone(zone)
            .replace(tzinfo=None)
            == local
        }
    except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError) as error:
        raise ValidationError(
            "Enter a valid minute in the edition time zone.",
            code="scheduling_minute_invalid",
        ) from error
    if not candidates:
        raise ValidationError(
            "This local minute does not exist because the clock moves forward.",
            code="scheduling_minute_nonexistent",
        )
    if len(candidates) != 1:
        raise ValidationError(
            "This local minute occurs twice. Supply an explicit UTC offset.",
            code="scheduling_minute_ambiguous",
        )
    return normalize_scheduling_instant(candidates.pop(), field="time")


@dataclass(frozen=True, slots=True)
class PlanningPlacementChange:
    """Compare authorized immutable placements by stable occurrence identity.

    Attributes
    ----------
    occurrence_id
        Stable occurrence present in one or both compared manifests.
    status
        Added, removed, changed or unchanged; never inferred from display labels.
    before
        Exact earlier geometry, or none for an addition.
    after
        Exact later geometry, or none for removal.
    changed_fields
        Closed names for visible geometry changes. A changed revision with no
        geometry difference is still changed, without exposing restricted layers.
    """

    occurrence_id: UUID
    status: str
    before: PlanningPlacement | None
    after: PlanningPlacement | None
    changed_fields: tuple[str, ...]


def compare_planning_placements(
    before: tuple[PlanningPlacement, ...], after: tuple[PlanningPlacement, ...]
) -> tuple[PlanningPlacementChange, ...]:
    """Compare complete already-authorized manifests without dereferencing owners.

    Parameters
    ----------
    before : tuple[PlanningPlacement, ...]
        Earlier complete geometry, obtained through an authorized owner query.
    after : tuple[PlanningPlacement, ...]
        Later complete geometry in the same independently authorized scope.

    Returns
    -------
    tuple[PlanningPlacementChange, ...]
        Deterministic occurrence-ordered differences including unchanged entries.

    Raises
    ------
    ValidationError
        If either input repeats an occurrence and cannot represent a manifest.
    """
    old = {placement.occurrence_id: placement for placement in before}
    new = {placement.occurrence_id: placement for placement in after}
    if len(old) != len(before) or len(new) != len(after):
        raise ValidationError("Compare complete manifests with distinct occurrences.")
    changes = []
    for occurrence in sorted(old.keys() | new.keys(), key=str):
        previous, following = old.get(occurrence), new.get(occurrence)
        fields: tuple[str, ...] = ()
        if previous is None:
            status = "added"
        elif following is None:
            status = "removed"
        elif previous == following:
            status = "unchanged"
        else:
            status = "changed"
            fields = tuple(
                field
                for field in (
                    "occurrence_revision_id",
                    "day_revision_id",
                    "space_id",
                    "capacity_mode",
                    "expected_attendance",
                    "envelope",
                )
                if getattr(previous, field) != getattr(following, field)
            )
        changes.append(
            PlanningPlacementChange(occurrence, status, previous, following, fields)
        )
    return tuple(changes)
