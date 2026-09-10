"""Exact-source, independently authorized staffing coverage for a private candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.staffing_queries import (
    ProgrammeStaffingOverview,
    ProgrammeStaffingReadRequest,
    load_programme_staffing_requirements,
)
from maru.programme.staffing_sources import (
    ProgrammeStaffingSourceConflictError,
    resolve_programme_staffing_selection,
)
from maru.workforce.programme_binding_queries import (
    ProgrammeBindingView,
    load_programme_bindings,
)
from maru.workforce.programme_coverage import (
    StaffingCoverage,
    StaffingCoverageIntegrityError,
    StaffingSourceState,
    evaluate_staffing_coverage,
)
from maru.workforce.programme_queries import (
    ProgrammeBoundDemandCoverage,
    ProgrammeCoverageDeniedError,
    authorize_programme_coverage,
    load_programme_bound_demand_coverage,
)
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    SchedulingAuthorizer,
)
from .inputs import require_identifier
from .planning_queries import (
    PLANNING_FIELDS,
    SchedulingPlanningSnapshot,
    SchedulingReadRequest,
    _audit,
    _authorize,
    load_scheduling_planning,
)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlanningStaffingRow:
    """Minimized coverage consequence without work copy, private reasons or people.

    Attributes
    ----------
    requirement_id
        Programme-owned need already disclosed by its independent owner policy.
    occurrence_id
        Exact occurrence owning the requirement.
    source_state
        Current, unbound, stale, withheld or unavailable; never an implied count.
    coverage
        Current minimized counts, or null counts for a non-current source.
    """

    requirement_id: UUID
    occurrence_id: UUID
    source_state: StaffingSourceState
    coverage: StaffingCoverage


def _rows(
    overview: ProgrammeStaffingOverview,
    planning: SchedulingPlanningSnapshot,
    bindings: tuple[ProgrammeBindingView, ...],
    demands: tuple[ProgrammeBoundDemandCoverage, ...],
) -> tuple[PlanningStaffingRow, ...]:
    by_requirement = {binding.source.requirement_id: binding for binding in bindings}
    by_demand = {row.demand.demand_id: row for row in demands}
    if (
        len(by_requirement) != len(bindings)
        or len(by_demand) != len(demands)
        or not set(by_requirement)
        <= {row.requirement_id for row in overview.requirements}
        or set(by_demand) != {binding.demand_id for binding in bindings}
    ):
        raise StaffingCoverageIntegrityError(
            "Complete binding coverage is unavailable."
        )
    result = []
    for requirement in overview.requirements:
        binding = by_requirement.get(requirement.requirement_id)
        source_state = StaffingSourceState.UNBOUND
        coverage = evaluate_staffing_coverage(source_state=source_state, counts=None)
        if binding is not None:
            demand = by_demand[binding.demand_id]
            try:
                selection = resolve_programme_staffing_selection(
                    overview, planning, source=binding.source
                )
            except ProgrammeStaffingSourceConflictError:
                source_state = StaffingSourceState.STALE
            else:
                source_state = (
                    StaffingSourceState.CURRENT
                    if selection.evidence_digest == binding.source_digest
                    and demand.work_terms_digest == binding.work_terms_digest
                    else StaffingSourceState.STALE
                )
            coverage = (
                demand.demand.coverage
                if source_state is StaffingSourceState.CURRENT
                else evaluate_staffing_coverage(source_state=source_state, counts=None)
            )
        result.append(
            PlanningStaffingRow(
                requirement.requirement_id,
                requirement.occurrence_id,
                source_state,
                coverage,
            )
        )
    return tuple(result)


def _unknown(
    overview: ProgrammeStaffingOverview, state: StaffingSourceState
) -> tuple[PlanningStaffingRow, ...]:
    return tuple(
        PlanningStaffingRow(
            row.requirement_id,
            row.occurrence_id,
            state,
            evaluate_staffing_coverage(source_state=state, counts=None),
        )
        for row in overview.requirements
    )


def load_planning_staffing(
    request: SchedulingReadRequest,
    *,
    item_id: UUID,
    candidate_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> tuple[PlanningStaffingRow, ...]:
    """Compose one item's complete staffing needs against an explicit alternative.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted current principal, exact scope and audit attribution.
    item_id : UUID
        Exact Programme item whose requirements are independently authorized.
    candidate_id : UUID
        Deliberately selected private alternative; never implicitly rebound.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme staffing-requirements policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent private-planning field policy.

    Returns
    -------
    tuple[PlanningStaffingRow, ...]
        Complete bounded rows with null counts whenever sources are not current.

    Notes
    -----
    Missing Workforce authority is withheld, not empty demand. A missing or
    incomplete dependency makes the complete layer unavailable. Audit failure
    cannot release coverage. Reads hold the canonical owner lock chain; commands
    still resolve sources afresh. This reader neither changes bindings nor
    publishes private candidates, and stays outside the base planning reader.
    """
    _authorize(request, VIEW_PLANNING, PLANNING_FIELDS, scheduling_authorizer)
    require_identifier(item_id)
    require_identifier(candidate_id)
    owner_request = ProgrammeStaffingReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        item_id,
        request.correlation_id,
        "scheduling-staffing",
    )
    owner_scope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        planning = load_scheduling_planning(
            request, candidate_id=candidate_id, authorizer=scheduling_authorizer
        )
        overview = load_programme_staffing_requirements(
            owner_request, authorizer=programme_authorizer
        )
        try:
            # A savepoint prevents dependency failure from leaving partial read
            # evidence or a broken transaction while reporting an unknown layer.
            with transaction.atomic():
                authorize_programme_coverage(**owner_scope)
                bindings = load_programme_bindings(
                    owner_request, authorizer=programme_authorizer
                )
                demands = (
                    load_programme_bound_demand_coverage(
                        **owner_scope,
                        demand_ids=tuple(binding.demand_id for binding in bindings),
                        correlation_id=request.correlation_id,
                    )
                    if bindings
                    else ()
                )
                result = _rows(overview, planning, bindings, demands)
                authorize_programme_staffing_adapter(**owner_scope, purpose="read")
                authorize_programme_coverage(**owner_scope)
        except (ProgrammeCoverageDeniedError, ProgrammeStaffingDeniedError):
            result = _unknown(overview, StaffingSourceState.WITHHELD)
        except (
            ProgrammeStaffingUnavailableError,
            StaffingCoverageIntegrityError,
            ValidationError,
            DatabaseError,
        ):
            result = _unknown(overview, StaffingSourceState.UNAVAILABLE)
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=PROGRAMME_VIEW_STAFFING,
            requested_fields=frozenset({"staffing_requirements"}),
            authorizer=programme_authorizer,
        )
        scope = _authorize(
            request, VIEW_PLANNING, PLANNING_FIELDS, scheduling_authorizer
        )
        _audit(request, VIEW_PLANNING, "staffing", scope=scope)
        return result
