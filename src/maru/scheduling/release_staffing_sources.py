"""Complete current staffing consequences, including operative predecessor work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.programme.staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_requirements,
)
from maru.workforce.programme_binding_queries import load_programme_bindings
from maru.workforce.programme_coverage import StaffingCoverageState, StaffingSourceState
from maru.workforce.programme_queries import (
    authorize_programme_coverage,
    load_programme_bound_demand_coverage,
)
from maru.workforce.programme_release_queries import load_programme_retained_work_source

from .inputs import scheduling_digest
from .planning_queries import load_scheduling_planning
from .release_eligibility import ReleaseCheckState as State
from .release_source_rules import combine_release_source_states
from .staffing_queries import _rows

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class ReleaseStaffingSource:
    """Owner-qualified coverage and explicit absence opportunity, not a declaration.

    Attributes
    ----------
    occurrence_id
        Exact selected Programme occurrence.
    state
        Complete current coverage; absence still needs a Programme owner decision.
    requires_absence_decision
        True only when no active need or operative retained work exists.
    evidence_digest
        Current complete requirement, binding, coverage and predecessor fingerprint.
    """

    occurrence_id: UUID
    state: State
    requires_absence_decision: bool
    evidence_digest: str


def load_release_staffing_sources(
    request: SchedulingReadRequest,
    *,
    item_id: UUID,
    candidate_id: UUID,
    occurrence_ids: tuple[UUID, ...],
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> tuple[ReleaseStaffingSource, ...]:
    """Compose complete independently authorized exact-source coverage for one item.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact scope and mandatory sensitive-read attribution.
    item_id : UUID
        Exact current Programme item from the admitted candidate.
    candidate_id : UUID
        Explicit current alternative, held under the outer collector transaction.
    occurrence_ids : tuple[UUID, ...]
        Complete selected occurrences of this item, never a caller success flag.
    programme_authorizer : ProgrammeAuthorizer
        Independent Programme requirement authority.
    scheduling_authorizer : SchedulingAuthorizer
        Independent Scheduling planning authority.

    Returns
    -------
    tuple[ReleaseStaffingSource, ...]
        Coverage only for active needs, with all operative retired/predecessor work
        retained as blockers. Missing owner authority propagates without disclosure.

    Notes
    -----
    The release compositor must hold shared parent and complete person locks before
    entering this helper. It supplies only owner-resolved candidate membership.
    Completed or cancelled demands do not count as current confirmed coverage.
    No personnel identities, private work terms or rationale leave this layer.
    """
    owner_request = ProgrammeStaffingReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        item_id,
        request.correlation_id,
    )
    scope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    overview = load_programme_staffing_requirements(
        owner_request, authorizer=programme_authorizer
    )
    planning = load_scheduling_planning(
        request, candidate_id=candidate_id, authorizer=scheduling_authorizer
    )
    bindings = load_programme_bindings(owner_request, authorizer=programme_authorizer)
    authorize_programme_coverage(**scope)
    demands = (
        load_programme_bound_demand_coverage(
            **scope,
            demand_ids=tuple(sorted({row.demand_id for row in bindings}, key=str)),
            correlation_id=request.correlation_id,
        )
        if bindings
        else ()
    )
    coverage = _rows(overview, planning, bindings, demands)
    by_requirement = {row.requirement_id: row for row in coverage}
    result = []
    for occurrence_id in occurrence_ids:
        retained = load_programme_retained_work_source(
            owner_request,
            occurrence_id=occurrence_id,
            authorizer=programme_authorizer,
        )
        active = set(retained.active_requirement_ids)
        expected_demands = {
            row.demand_id for row in bindings if row.source.requirement_id in active
        }
        states = []
        for requirement_id in sorted(active, key=str):
            row = by_requirement.get(requirement_id)
            states.append(
                State.UNAVAILABLE
                if row is None
                else State.STALE
                if row.source_state is StaffingSourceState.STALE
                else State.UNAVAILABLE
                if row.source_state
                in {
                    StaffingSourceState.WITHHELD,
                    StaffingSourceState.UNAVAILABLE,
                }
                else State.SATISFIED
                if row.coverage.state
                in {
                    StaffingCoverageState.COVERED,
                    StaffingCoverageState.LOCKED_COVERED,
                }
                else State.BLOCKED
            )
        if set(retained.operative_demand_ids) - expected_demands:
            states.append(State.BLOCKED)
        absence = not active and not retained.operative_demand_ids
        result.append(
            ReleaseStaffingSource(
                occurrence_id,
                State.NOT_APPLICABLE
                if absence
                else combine_release_source_states(tuple(states)),
                absence,
                scheduling_digest(
                    {
                        "retained": retained.evidence_digest,
                        "bindings": [
                            {
                                "id": str(row.binding_id),
                                "version": row.version,
                                "source": row.source_digest,
                                "work": row.work_terms_digest,
                            }
                            for row in bindings
                        ],
                        "demands": [row.demand.evidence_digest for row in demands],
                        "states": [state.value for state in states],
                        "absence": absence,
                    }
                ),
            )
        )
    authorize_programme_coverage(**scope)
    return tuple(result)
