"""Current owner-admitted host choices, without historical timetable disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import F

from maru.programme.host_queries import (
    ProgrammeHostReadRequest,
    load_programme_host_roster,
)
from maru.programme.queries import list_programme_timetable_items

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_PLANNING
from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .models import (
    SchedulingOccurrence,
    SchedulingOccurrenceRevision,
    SchedulingReleaseWithdrawal,
)
from .planning_queries import PlanningOccurrence, _bounded, _read
from .release_queries import RELEASE_MANIFEST_FIELDS
from .release_workspace_queries import load_release_pointer

if TYPE_CHECKING:
    from uuid import UUID

    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class NoticeOccurrenceChoice:
    """Current private label and exact occurrence, not a released-content claim.

    Attributes
    ----------
    occurrence
        Current complete Scheduling identity and lifecycle evidence.
    label
        Independently admitted current Programme title and occurrence discriminator.
    item_version
        Current item version fencing label and roster composition.
    working_version
        Exact current working-label source version.
    """

    occurrence: PlanningOccurrence
    label: str
    item_version: int
    working_version: int


@dataclass(frozen=True, slots=True)
class NoticeHostChoice:
    """One current confirmed relationship, without contact or invitation copy.

    Attributes
    ----------
    host_id
        Exact owner relationship; never replaceable by a person reference.
    label
        Current related-person display label and role.
    account_id
        Exact resolved person, retained only for final source comparison.
    version
        Current relationship version.
    invitation_sequence
        Exact confirmed invitation source.
    """

    host_id: UUID
    label: str
    account_id: UUID
    version: int
    invitation_sequence: int


@dataclass(frozen=True, slots=True)
class NoticeHostSelection:
    """Complete guided-source observation, never portable command authority.

    Attributes
    ----------
    release_id
        Current publication or latest withdrawn publication, absent before first.
    pointer_version
        Exact current source pointer, zero only before first publication.
    occurrences
        Complete bounded independently labelled current occurrence choices.
    hosts
        Current confirmed hosts for the deliberately selected occurrence only.
    """

    release_id: UUID | None
    pointer_version: int
    occurrences: tuple[NoticeOccurrenceChoice, ...]
    hosts: tuple[NoticeHostChoice, ...]


def _sources(
    request: SchedulingReadRequest,
) -> tuple[UUID | None, int, tuple[PlanningOccurrence, ...]]:
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }

    def load(_scope: object) -> tuple[UUID | None, int, tuple[PlanningOccurrence, ...]]:
        # The outer edition mutex keeps the independently authenticated pointer
        # observation coherent with this metadata-only withdrawal lookup.
        pointer = load_release_pointer(request)
        release_id = pointer.active_release_id
        if release_id is None and pointer.version:
            release_id = (
                SchedulingReleaseWithdrawal.objects.filter(
                    **ownership, pointer_version=pointer.version
                )
                .values_list("release_id", flat=True)
                .first()
            )
            if release_id is None:
                raise SchedulingUnavailableError
        rows = _bounded(
            list(
                SchedulingOccurrenceRevision.objects.filter(
                    **ownership,
                    sequence=F("occurrence__aggregate_version"),
                    occurrence__organization_id=request.organization_id,
                    occurrence__edition_id=request.edition_id,
                )
                .select_related("occurrence")
                .only(
                    "id",
                    "occurrence_id",
                    "sequence",
                    "lifecycle",
                    "group_key",
                    "group_sequence",
                    "occurrence__programme_item_id",
                )
                .order_by("occurrence_id")[: MAX_OCCURRENCES + 1]
            ),
            MAX_OCCURRENCES,
        )
        if SchedulingOccurrence.objects.filter(**ownership).count() != len(rows):
            raise SchedulingUnavailableError
        return (
            release_id,
            pointer.version,
            tuple(
                PlanningOccurrence(
                    row.occurrence_id,
                    row.id,
                    row.sequence,
                    row.occurrence.programme_item_id,
                    row.lifecycle,
                    row.group_key,
                    row.group_sequence,
                )
                for row in rows
            ),
        )

    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=RELEASE_MANIFEST_FIELDS | frozenset({"occurrences"}),
        purpose="notice_source_choices",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=load,
    )


def load_notice_host_selection(
    request: SchedulingReadRequest,
    *,
    occurrence_id: UUID | None = None,
) -> NoticeHostSelection:
    """Compose current owner choices without searching people or old geometry.

    Parameters
    ----------
    request : SchedulingReadRequest
        Already notice-admitted actor and exact scope; each owner admits again.
    occurrence_id : UUID | None, default=None
        Deliberate current occurrence selection, never authority to read a roster.

    Returns
    -------
    NoticeHostSelection
        Complete current source identities and optional exact-item host choices.

    Raises
    ------
    SchedulingUnavailableError
        If a current occurrence has no independently readable current item.
    SchedulingVersionConflictError
        If the deliberate occurrence or its item-to-roster version has moved.

    Notes
    -----
    Owner denial, overflow and audit/dependency failure propagate without partial
    disclosure. The caller must compare a fresh observation after rendering.
    Preview and every command independently prove affected source membership.
    """
    release_id, pointer_version, occurrences = _sources(request)
    items = {
        row.item.id: row
        for row in list_programme_timetable_items(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            correlation_id=request.correlation_id,
        )
    }
    if any(row.item_id not in items for row in occurrences):
        raise SchedulingUnavailableError
    choices = tuple(
        NoticeOccurrenceChoice(
            row,
            f"{items[row.item_id].internal_title} · "
            f"occurrence {index + 1} · {row.lifecycle}",
            items[row.item_id].item.aggregate_version,
            items[row.item_id].working_version,
        )
        for index, row in enumerate(occurrences)
    )
    hosts: tuple[NoticeHostChoice, ...] = ()
    if occurrence_id is not None:
        selected = next(
            (row for row in choices if row.occurrence.id == occurrence_id), None
        )
        if selected is None:
            raise SchedulingVersionConflictError
        roster = load_programme_host_roster(
            ProgrammeHostReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                selected.occurrence.item_id,
                request.correlation_id,
            )
        )
        if roster.item_version != selected.item_version:
            raise SchedulingVersionConflictError
        hosts = tuple(
            NoticeHostChoice(
                row.relationship.host_id,
                f"{row.display_label} · {row.relationship.role}",
                row.account_id,
                row.relationship.version,
                row.relationship.invitation_sequence,
            )
            for row in roster.entries
            if row.person_current and row.relationship.state == "confirmed"
        )
    return NoticeHostSelection(release_id, pointer_version, choices, hosts)
