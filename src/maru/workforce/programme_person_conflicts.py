"""Minimized pure combined-presence checks with retained Workforce rest semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.scheduling.catalogs import MAX_CONFLICT_COMPARISONS, MAX_CONFLICTS


@dataclass(frozen=True, slots=True)
class ProgrammePersonObligation:
    """Ephemeral current presence or retained commitment; no display labels.

    Attributes
    ----------
    person_key
        Existing edition-bounded Identity conflict key.
    occurrence_id
        Selected Programme consequence, or None for an undisclosed external duty.
    obligation_id
        Opaque deduplication identity; not returned in findings.
    kind
        Host presence or retained Workforce commitment.
    starts_at
        Inclusive current presence/work start.
    ends_at
        Exclusive current presence/work end.
    rest_ends_at
        Retained Workforce rest endpoint; hosts add no invented rest duration.
    """

    person_key: UUID
    occurrence_id: UUID | None
    obligation_id: UUID
    kind: str
    starts_at: datetime
    ends_at: datetime
    rest_ends_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammePersonConsequence:
    """Only a selected Programme consequence, never another edition's duty details.

    Attributes
    ----------
    occurrence_id
        Selected candidate occurrence affected by this conflict.
    person_key
        Edition-bounded identity already represented in the selected obligations.
    code
        Closed overlap or retained-rest conflict, without foreign duty provenance.
    """

    occurrence_id: UUID
    person_key: UUID
    code: str


def evaluate_programme_person_conflicts(
    obligations: tuple[ProgrammePersonObligation, ...],
) -> tuple[ProgrammePersonConsequence, ...]:
    """Compare complete trusted obligations without disclosing unrelated calendars.

    Parameters
    ----------
    obligations : tuple[ProgrammePersonObligation, ...]
        Complete bounded owner-resolved selected and relevant global obligations.

    Returns
    -------
    tuple[ProgrammePersonConsequence, ...]
        Deduplicated selected-occurrence overlap and retained-rest consequences.

    Raises
    ------
    ValidationError
        If closed shapes, positive aware intervals or comparison/output bounds fail.

    Notes
    -----
    This pure helper authenticates no input. The owner query must resolve every
    source and independently authorize its disclosure before calling. Same-host
    roles within one occurrence do not duplicate attendance; a volunteer commitment
    is not silently equated with hosting. A commitment is not compared with itself.
    Intervals are half-open, and host presence does not invent post-host rest.
    """
    if type(obligations) is not tuple or len(obligations) > MAX_CONFLICTS:
        raise ValidationError("Complete bounded person obligations are required.")
    people: dict[UUID, list[ProgrammePersonObligation]] = {}
    for row in obligations:
        if (
            type(row) is not ProgrammePersonObligation
            or not isinstance(row.person_key, UUID)
            or not isinstance(row.obligation_id, UUID)
            or (
                row.occurrence_id is not None
                and not isinstance(row.occurrence_id, UUID)
            )
            or type(row.kind) is not str
            or row.kind not in {"host", "work"}
            or any(
                not isinstance(value, datetime)
                for value in (row.starts_at, row.ends_at, row.rest_ends_at)
            )
            or any(
                value.utcoffset() is None
                for value in (row.starts_at, row.ends_at, row.rest_ends_at)
            )
            or not row.starts_at < row.ends_at <= row.rest_ends_at
            or (row.kind == "host" and row.rest_ends_at != row.ends_at)
        ):
            raise ValidationError("Use exact positive aware work and rest intervals.")
        people.setdefault(row.person_key, []).append(row)
    consequences: set[tuple[UUID, UUID, str]] = set()
    comparisons = 0
    for rows in people.values():
        for left, right in combinations(rows, 2):
            comparisons += 1
            if comparisons > MAX_CONFLICT_COMPARISONS:
                raise ValidationError("Complete person comparison is unavailable.")
            if (
                (left.occurrence_id is None and right.occurrence_id is None)
                or (
                    left.kind == right.kind == "work"
                    and left.obligation_id == right.obligation_id
                )
                or (
                    left.kind == right.kind == "host"
                    and left.occurrence_id == right.occurrence_id
                )
            ):
                continue
            overlap = left.starts_at < right.ends_at and right.starts_at < left.ends_at
            rest = (
                left.ends_at <= right.starts_at < left.rest_ends_at
                or right.ends_at <= left.starts_at < right.rest_ends_at
            )
            for row in (left, right):
                if row.occurrence_id is not None:
                    if overlap:
                        consequences.add((row.occurrence_id, row.person_key, "overlap"))
                    if rest:
                        consequences.add((row.occurrence_id, row.person_key, "rest"))
            if len(consequences) > MAX_CONFLICTS:
                raise ValidationError("Complete person consequences are unavailable.")
    return tuple(
        ProgrammePersonConsequence(*values)
        for values in sorted(
            consequences, key=lambda values: (str(values[0]), str(values[1]), values[2])
        )
    )
