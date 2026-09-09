"""Closed Programme staffing expectations and exact timetable source references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from .inputs import normalized_text, require_positive_version, require_uuid

if TYPE_CHECKING:
    from uuid import UUID

MAX_STAFFING_HEADCOUNT = 1_024
MAX_STAFFING_BREAK_MINUTES = 1_440
MAX_STAFFING_REST_MINUTES = 2_880


def _staffing_number(value: int, *, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(
            {
                field: ValidationError(
                    "Use a whole number within the staffing limit.",
                    code="programme_staffing_number_invalid",
                )
            }
        )
    return value


def _staffing_instant(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValidationError(
            {
                field: ValidationError(
                    "Use an offset-aware staffing time.",
                    code="programme_staffing_instant_invalid",
                )
            }
        )
    try:
        instant = value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValidationError(
            "The staffing time is outside the supported range.",
            code="programme_staffing_instant_invalid",
        ) from error
    if instant.second or instant.microsecond:
        raise ValidationError(
            {
                field: ValidationError(
                    "Use a whole UTC minute for staffing.",
                    code="programme_staffing_instant_invalid",
                )
            }
        )
    return instant


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingExpectation:
    """Explicit work terms, independent of audience-facing Programme timing.

    Attributes
    ----------
    position_id
        Exact Workforce Position requested; this identity grants no authority.
    title
        Person-facing work name, never inferred from private Programme content.
    location_label
        Explicit reporting place, not an assertion of Venue approval.
    briefing
        Operational work instructions deliberately shared with workers.
    supervision_note
        Optional bounded supervision or handover instructions.
    starts_at
        Inclusive offset-aware work start, including any preparation.
    ends_at
        Exclusive offset-aware work end, including any teardown.
    required_headcount
        Requested accountable coverage; zero is not a staffing requirement.
    break_minutes
        Planned break strictly shorter than the work interval.
    minimum_rest_minutes
        Blocked rest after the work interval, not extra work.
    """

    position_id: UUID
    title: str
    location_label: str
    briefing: str
    supervision_note: str
    starts_at: datetime
    ends_at: datetime
    required_headcount: int
    break_minutes: int = 0
    minimum_rest_minutes: int = 0

    def normalized(self) -> ProgrammeStaffingExpectation:
        """Validate bounded work terms without resolving private owner records.

        Returns
        -------
        ProgrammeStaffingExpectation
            A fresh immutable expectation with canonical text and UTC minutes.

        Raises
        ------
        ValidationError
            If work duration is nonpositive or its break consumes all work.

        Notes
        -----
        The owning command must independently authorize the exact Position and
        validate current edition bounds, lifecycle and source versions. Pure
        normalization is neither source resolution nor Workforce acceptance.
        """
        position = require_uuid(self.position_id, field="position_id")
        start = _staffing_instant(self.starts_at, field="starts_at")
        end = _staffing_instant(self.ends_at, field="ends_at")
        headcount = _staffing_number(
            self.required_headcount,
            field="required_headcount",
            minimum=1,
            maximum=MAX_STAFFING_HEADCOUNT,
        )
        rest = _staffing_number(
            self.minimum_rest_minutes,
            field="minimum_rest_minutes",
            minimum=0,
            maximum=MAX_STAFFING_REST_MINUTES,
        )
        pause = _staffing_number(
            self.break_minutes,
            field="break_minutes",
            minimum=0,
            maximum=MAX_STAFFING_BREAK_MINUTES,
        )
        if end <= start or pause * 60 >= (end - start).total_seconds():
            raise ValidationError(
                "Staffing must include positive working time outside the break.",
                code="programme_staffing_interval_invalid",
            )
        text = {
            field: normalized_text(
                getattr(self, field),
                field=field,
                maximum=maximum,
                required=field != "supervision_note",
                collapse=True,
            )
            for field, maximum in (
                ("title", 160),
                ("location_label", 160),
                ("briefing", 1_000),
                ("supervision_note", 500),
            )
        }
        return ProgrammeStaffingExpectation(
            position,
            text["title"],
            text["location_label"],
            text["briefing"],
            text["supervision_note"],
            start,
            end,
            headcount,
            pause,
            rest,
        )


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingSource:
    """One explicit immutable source selection, never the latest candidate.

    Attributes
    ----------
    requirement_id
        Stable Programme staffing requirement.
    requirement_revision_id
        Exact immutable requirement revision selected by the planner.
    requirement_version
        Optimistic requirement sequence represented by the revision.
    occurrence_id
        Stable Scheduling occurrence, shared by timetable alternatives.
    occurrence_version
        Exact occurrence version used by the selected placement.
    candidate_id
        Explicit alternative selected for this demand.
    candidate_revision_id
        Exact immutable alternative revision, not a mutable latest pointer.
    placement_id
        Exact retained placement within the candidate revision.
    """

    requirement_id: UUID
    requirement_revision_id: UUID
    requirement_version: int
    occurrence_id: UUID
    occurrence_version: int
    candidate_id: UUID
    candidate_revision_id: UUID
    placement_id: UUID

    def validated(self) -> ProgrammeStaffingSource:
        """Require explicit typed source identities without proving their scope.

        Returns
        -------
        ProgrammeStaffingSource
            The unchanged frozen source after shape validation.

        Raises
        ------
        ValidationError
            If an optimistic source version cannot be represented safely.

        Notes
        -----
        The command must resolve every identity through its owner under the
        canonical lock order. Client-supplied versions are not trusted facts.
        """
        for field in (
            "requirement_id",
            "requirement_revision_id",
            "occurrence_id",
            "candidate_id",
            "candidate_revision_id",
            "placement_id",
        ):
            require_uuid(getattr(self, field), field=field)
        for field in ("requirement_version", "occurrence_version"):
            version = require_positive_version(getattr(self, field), field=field)
            if version >= 2**63 - 1:
                raise ValidationError(
                    "The staffing source version cannot advance.",
                    code="programme_staffing_version_invalid",
                )
        return self
