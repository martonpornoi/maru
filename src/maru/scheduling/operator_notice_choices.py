"""Current owner-labelled operator targets before any known-person discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import connection

from maru.venues.timetable_queries import (
    VenueTimetableSpace,
    list_venue_timetable_spaces,
)
from maru.workforce.operator_target_choices import (
    list_programme_operator_department_choices,
)

from .authorization import (
    VIEW_CHANGE_RECIPIENTS,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .change_notice_selection import (
    NoticeSourceSelection,
    _selected,
    load_notice_source_selection,
)
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .operator_scope import OperatorScopeKind

if TYPE_CHECKING:
    from maru.workforce.queries import CurrentDepartmentChoiceReference

    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class NoticeOperatorTarget:
    """One independently admitted target and its exact owner observation.

    Attributes
    ----------
    id
        Exact current room, Department or edition identity.
    label
        Current authorized human label, never portable scope authority.
    reference
        Full minimized owner observation retained for final disclosure comparison.
    """

    id: UUID
    label: str
    reference: VenueTimetableSpace | CurrentDepartmentChoiceReference | UUID


@dataclass(frozen=True, slots=True)
class NoticeOperatorChoices:
    """Complete source and target observations without a recipient directory.

    Attributes
    ----------
    source
        Independently admitted current occurrence labels and publication pointer.
    occurrence_id
        Deliberate source, absent before the first choice.
    kind
        Closed operator purpose, absent before deliberate selection.
    target_id
        Deliberate member of the complete current labelled target set.
    targets
        Complete current owner-admitted labels, never a partial overflow result.
    """

    source: NoticeSourceSelection
    occurrence_id: UUID | None
    kind: OperatorScopeKind | None
    target_id: UUID | None
    targets: tuple[NoticeOperatorTarget, ...]


def admit_notice_operator_selection(request: SchedulingReadRequest) -> None:
    """Require the actual sender's independent recipient field before discovery.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted authenticated actor and exact owner scope.

    Notes
    -----
    This check grants neither labels nor selected-person eligibility. Each owner
    independently authorizes and audits its own disclosure. It takes no person
    lock, so complete multi-person ordering remains possible in the later read.
    """
    authorize_scheduling_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=VIEW_CHANGE_RECIPIENTS,
        requested_fields=frozenset({"operator_recipients"}),
    )


def _targets(
    request: SchedulingReadRequest, kind: OperatorScopeKind
) -> tuple[NoticeOperatorTarget, ...]:
    scope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "correlation_id": request.correlation_id,
    }
    if kind is OperatorScopeKind.ROOM:
        return tuple(
            NoticeOperatorTarget(
                row.id,
                f"{row.venue_label} / {row.label} · {row.configuration_label}",
                row,
            )
            for row in list_venue_timetable_spaces(**scope)
            if row.lifecycle == "active" and row.venue_lifecycle == "active"
        )
    if kind is OperatorScopeKind.DEPARTMENT:
        return tuple(
            NoticeOperatorTarget(row.department_id, f"{row.code} · {row.label}", row)
            for row in list_programme_operator_department_choices(**scope)
        )
    return (
        NoticeOperatorTarget(request.edition_id, "Current edition", request.edition_id),
    )


def load_notice_operator_choices(
    request: SchedulingReadRequest,
    *,
    occurrence_id: UUID | None = None,
    kind: OperatorScopeKind | None = None,
    target_id: UUID | None = None,
) -> NoticeOperatorChoices:
    """Compose independently admitted labels before multi-person recipient reads.

    Parameters
    ----------
    request : SchedulingReadRequest
        Notice-admitted sender; recipient and all label owners authorize again.
    occurrence_id : UUID | None, default=None
        Deliberate current occurrence, required before target discovery.
    kind : OperatorScopeKind | None, default=None
        Closed room, Department or edition purpose.
    target_id : UUID | None, default=None
        Deliberate exact target, required to belong to current labelled choices.

    Returns
    -------
    NoticeOperatorChoices
        Complete current observations, requiring a fresh comparison after rendering.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If selection shape is invalid or independent sender admission is denied.
    SchedulingVersionConflictError
        If a deliberately selected source or target is no longer available.
    SchedulingUnavailableError
        If called inside an outer transaction that could retain actor-first locks.

    Notes
    -----
    Owner overflow, audit and dependency failures propagate without partial labels.
    No email, recipient account or historical released geometry is discovered here.
    """
    if connection.in_atomic_block:
        raise SchedulingUnavailableError
    if (
        (kind is not None and not isinstance(kind, OperatorScopeKind))
        or any(
            value is not None and (type(value) is not UUID or not value.int)
            for value in (occurrence_id, target_id)
        )
        or (kind is not None and occurrence_id is None)
        or (target_id is not None and kind is None)
    ):
        raise SchedulingAuthorizationDeniedError
    admit_notice_operator_selection(request)
    source = load_notice_source_selection(request)
    if occurrence_id is not None:
        _selected(source, occurrence_id)
    targets = _targets(request, kind) if kind is not None else ()
    if target_id is not None and target_id not in {row.id for row in targets}:
        raise SchedulingVersionConflictError
    admit_notice_operator_selection(request)
    return NoticeOperatorChoices(source, occurrence_id, kind, target_id, targets)
