"""Minimized operator work instructions and retained interval/state counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Count

from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_release_references import load_operator_release_reference
from maru.scheduling.operator_scope import OperatorReadRequest, operator_read

from .models import MAX_SHIFT_HEADCOUNT, ShiftCommitment, ShiftDemand
from .operator_links import OperatorWorkLink, _load_links, operator_staffing_adopted
from .shift_queries import MAX_SHIFT_COMMITMENTS, MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class OperatorRetainedWork:
    """Count equal retained work terms without returning a person or commitment ID.

    Attributes
    ----------
    starts_at
        Retained commitment start, never replaced with current demand terms.
    ends_at
        Retained commitment end.
    rest_ends_at
        Retained minimum-rest end; no personal availability periods are selected.
    state
        Claimed, confirmed, removed or completed; not attendance or current fitness.
    count
        Number of commitments with these exact retained terms and state.
    """

    starts_at: datetime
    ends_at: datetime
    rest_ends_at: datetime
    state: str
    count: int


@dataclass(frozen=True, slots=True)
class OperatorStaffingDemand:
    """Current demand instructions alongside separately retained accepted work.

    Attributes
    ----------
    demand_id
        Exact linked current or retained demand identity.
    version
        Current instruction/lifecycle version, not an acceptance snapshot version.
    state
        Current demand lifecycle; a predecessor is not implicitly cancelled.
    title
        Current short work title.
    location
        Current plain-language work location, not an inferred relocation.
    briefing
        Current operational instructions under independent work field authority.
    supervision
        Current operational supervision note, without a personnel directory.
    starts_at
        Current requested demand start, distinct from retained work terms.
    ends_at
        Current requested demand end.
    required_headcount
        Requested coverage target, not confirmed capacity or attendance.
    retained_work
        Complete bounded interval/state counts without identifying people.
    """

    demand_id: UUID
    version: int
    state: str
    title: str
    location: str
    briefing: str
    supervision: str
    starts_at: datetime
    ends_at: datetime
    required_headcount: int
    retained_work: tuple[OperatorRetainedWork, ...]


@dataclass(frozen=True, slots=True)
class OperatorStaffingSnapshot:
    """Complete requested Workforce layer, or explicitly unadopted, never partial.

    Attributes
    ----------
    adopted
        Whether the deliberate staffing adapter is currently admitted.
    links
        Complete authorized in-purpose current and predecessor demand lineage.
    demands
        Complete distinct instructions and retained work for those exact links.
    """

    adopted: bool
    links: tuple[OperatorWorkLink, ...]
    demands: tuple[OperatorStaffingDemand, ...]


def _demands(
    request: OperatorReadRequest, links: tuple[OperatorWorkLink, ...]
) -> tuple[OperatorStaffingDemand, ...]:
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    identifiers = {link.demand_id for link in links}
    if len(identifiers) > MAX_SHIFT_DEMANDS:
        raise SchedulingUnavailableError
    rows = tuple(
        ShiftDemand.objects.filter(**ownership, id__in=identifiers)
        .order_by("id")
        .values_list(
            "id",
            "command_version",
            "status",
            "title",
            "location_label",
            "briefing",
            "supervision_note",
            "starts_at",
            "ends_at",
            "required_headcount",
        )[: MAX_SHIFT_DEMANDS + 1]
    )
    versions = {row[0]: row[1] for row in rows}
    if set(versions) != identifiers or any(
        versions[link.demand_id] != link.demand_version for link in links
    ):
        raise SchedulingUnavailableError
    retained = tuple(
        ShiftCommitment.objects.filter(**ownership, demand_id__in=identifiers)
        .values("demand_id", "starts_at", "ends_at", "rest_ends_at", "status")
        .annotate(count=Count("id"))
        .order_by("demand_id", "starts_at", "ends_at", "rest_ends_at", "status")[
            : MAX_SHIFT_COMMITMENTS + 1
        ]
    )
    if sum(row["count"] for row in retained) > MAX_SHIFT_COMMITMENTS:
        raise SchedulingUnavailableError
    grouped: dict[UUID, list[OperatorRetainedWork]] = {
        identifier: [] for identifier in identifiers
    }
    for row in retained:
        if (
            not row["starts_at"] < row["ends_at"] <= row["rest_ends_at"]
            or row["status"] not in ShiftCommitment.Status.values
        ):
            raise SchedulingUnavailableError
        grouped[row["demand_id"]].append(
            OperatorRetainedWork(
                row["starts_at"],
                row["ends_at"],
                row["rest_ends_at"],
                row["status"],
                row["count"],
            )
        )
    if any(
        row[2] not in ShiftDemand.Status.values
        or not row[7] < row[8]
        or not 1 <= row[9] <= MAX_SHIFT_HEADCOUNT
        for row in rows
    ):
        raise SchedulingUnavailableError
    return tuple(OperatorStaffingDemand(*row, tuple(grouped[row[0]])) for row in rows)


def load_operator_staffing(
    request: OperatorReadRequest, *, expected_release_id: UUID | None
) -> OperatorStaffingSnapshot:
    """Read exact linked operational work without discovering people or rewriting it.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact operator purpose; Workforce independently evaluates all needed fields.
    expected_release_id : UUID | None
        Optimistic current release identity, never an arbitrary occurrence list.

    Returns
    -------
    OperatorStaffingSnapshot
        Complete versioned requested work layer, including retained predecessors.

    Raises
    ------
    SchedulingUnavailableError
        If release, adoption, bounded work lineage, instructions or terms change.

    Notes
    -----
    Owner admission failures propagate SchedulingAuthorizationDeniedError even
    for an empty approved purpose. No personnel, qualification, availability,
    private rationale or attendance is selected. Counts describe retained work
    states only; claimed work is not confirmed work and confirmed is not proof of
    current suitability or actual attendance. Reading performs no work mutation.
    """
    with operator_read(
        request,
        capability="workforce.view_operator_staffing",
        fields=frozenset({"scope_links", "work_instructions", "coverage"}),
    ):
        reference = load_operator_release_reference(request)
        if reference.release_id != expected_release_id:
            raise SchedulingUnavailableError
        adopted = operator_staffing_adopted(request)
        selected = {row.occurrence_id for row in reference.occurrences}
        links = _load_links(request, occurrence_ids=selected) if adopted else ()
        demands = _demands(request, links) if adopted else ()
        if (
            operator_staffing_adopted(request) != adopted
            or (adopted and _load_links(request, occurrence_ids=selected) != links)
            or (adopted and _demands(request, links) != demands)
            or load_operator_release_reference(request) != reference
        ):
            raise SchedulingUnavailableError
        return OperatorStaffingSnapshot(adopted, links, demands)
