"""Explicit required host times composed with independently authorized rosters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import F

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.host_queries import (
    ProgrammeHostReadRequest,
    load_programme_host_roster,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
)
from .candidate_commands import _load_manifest
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .inputs import require_identifier, require_version
from .models import (
    SchedulingCandidateRevision,
    SchedulingOccurrence,
    SchedulingPlacementHostPresence,
    SchedulingPlacementRevision,
)
from .planning_queries import PLANNING_FIELDS, _ownership, _read
from .time_rules import MAX_HOSTS_PER_OCCURRENCE, SchedulingHostPresence

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.host_queries import ProgrammeHostRosterSnapshot

    from .authorization import AuthorizedSchedulingScope, SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class PlanningHostRequirements:
    """One occurrence's explicit requirements and current authorized host choices.

    Attributes
    ----------
    candidate_version
        Exact observed version, never a silently rebased stale form.
    occurrence_id
        Stable owned occurrence, whether currently placed or unplaced.
    item_id
        The immutable Programme item owning the returned roster.
    placement_id
        Exact current placement, or none for an unplaced occurrence.
    presences
        Retained required time windows, not shared or personal availability.
    roster
        Complete independently authorized current host labels and states.
        Current identity labels are not historical identity evidence.
    """

    candidate_version: int
    occurrence_id: UUID
    item_id: UUID
    placement_id: UUID | None
    presences: tuple[SchedulingHostPresence, ...]
    roster: ProgrammeHostRosterSnapshot


def _presences(
    request: SchedulingReadRequest, placement_id: UUID | None, occurrence_id: UUID
) -> tuple[SchedulingHostPresence, ...]:
    if placement_id is None:
        return ()
    count = (
        SchedulingPlacementRevision.objects.filter(
            **_ownership(request),
            id=placement_id,
            occurrence_revision__occurrence_id=occurrence_id,
        )
        .values_list("host_presence_count", flat=True)
        .first()
    )
    rows = tuple(
        SchedulingPlacementHostPresence.objects.filter(
            **_ownership(request), placement_id=placement_id
        )
        .order_by("host_relationship_id")
        .values_list("host_relationship_id", "starts_at", "ends_at")[
            : MAX_HOSTS_PER_OCCURRENCE + 1
        ]
    )
    if count is None or len(rows) != count or len(rows) > MAX_HOSTS_PER_OCCURRENCE:
        raise SchedulingUnavailableError
    return tuple(SchedulingHostPresence(*row) for row in rows)


def load_scheduling_host_requirements(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    expected_version: int,
    occurrence_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> PlanningHostRequirements:
    """Inspect explicit required host times without loading anyone's availability.

    Scheduling authorizes the exact current candidate and occurrence before
    Programme independently authorizes its roster. Programme locks the complete
    canonical person set and resolves only already-related current display labels.
    Unavailable or unauthorized roster data withholds the entire host inspector.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-edition actor and read-audit attribution.
    candidate_id : UUID
        Explicit scoped candidate, including retained archived alternatives.
    expected_version : int
        Observed current candidate version, not a historical revision selector.
    occurrence_id : UUID
        Exact occurrence whose placement requirements are requested.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary Scheduling policy or the existing sealed test-only substitute.

    Returns
    -------
    PlanningHostRequirements
        Complete current roster and retained required times, audited by both owners.
    """
    require_identifier(candidate_id)
    require_identifier(occurrence_id)
    require_version(expected_version)

    def load(_scope: AuthorizedSchedulingScope) -> PlanningHostRequirements:
        revision = SchedulingCandidateRevision.objects.filter(
            **_ownership(request),
            candidate_id=candidate_id,
            sequence=F("candidate__aggregate_version"),
        ).first()
        if revision is None:
            raise SchedulingUnavailableError
        if revision.sequence != expected_version:
            raise SchedulingVersionConflictError
        item_id = (
            SchedulingOccurrence.objects.filter(**_ownership(request), id=occurrence_id)
            .values_list("programme_item_id", flat=True)
            .first()
        )
        if item_id is None:
            raise SchedulingUnavailableError
        placement_id = dict(_load_manifest(revision)).get(occurrence_id)
        presences = _presences(request, placement_id, occurrence_id)
        try:
            roster = load_programme_host_roster(
                ProgrammeHostReadRequest(
                    request.actor_id,
                    request.organization_id,
                    request.edition_id,
                    item_id,
                    request.correlation_id,
                    "scheduling-planning",
                )
            )
        except ProgrammeAuthorizationDeniedError as error:
            # The outer read transaction rolls back owner success/denial work;
            # release a non-disclosing denial and audit it after that rollback.
            raise SchedulingAuthorizationDeniedError from error
        if not {presence.host_id for presence in presences} <= {
            entry.relationship.host_id for entry in roster.entries
        }:
            raise SchedulingUnavailableError
        return PlanningHostRequirements(
            revision.sequence, occurrence_id, item_id, placement_id, presences, roster
        )

    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=PLANNING_FIELDS,
        purpose="host_requirements",
        authorizer=authorizer,
        loader=load,
    )
