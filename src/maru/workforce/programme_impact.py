"""Pure, closed impact rules for explicit Programme-to-Workforce demand changes."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from uuid import UUID

from maru.programme.staffing_inputs import ProgrammeStaffingExpectation

from .programme_coverage import MAX_RETAINED_COVERAGE_COMMITMENTS


class ProgrammeStaffingImpactError(ValueError):
    """Reject incomplete evidence or an operation that could rewrite accepted work."""


class ProgrammeStaffingAction(StrEnum):
    """Explicit adapter actions, never inferred from the last edited alternative."""

    CREATE = "create"
    LINK = "link"
    RECONCILE = "reconcile"
    SUCCESSOR = "successor"


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingDemandState:
    """Freeze exact owner facts for an authorized impact comparison.

    Attributes
    ----------
    demand_id
        Exact scoped Workforce demand identity.
    version
        Current command version, including ordinary lifecycle transitions.
    status
        Closed Workforce lifecycle state.
    expectation
        Current person-facing work terms, without private organizer rationale.
    retained_commitments
        All retained decisions, including removed or completed commitments.
    claimed
        Active personal claims, not independent confirmations.
    confirmed
        Active independent confirmations, not a promise of current suitability.
    """

    demand_id: UUID
    version: int
    status: str
    expectation: ProgrammeStaffingExpectation
    retained_commitments: int
    claimed: int
    confirmed: int


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingImpact:
    """Describe bounded consequences without granting mutation authority.

    Attributes
    ----------
    action
        Explicit operation whose preconditions were evaluated.
    changed_fields
        Deterministically ordered names of changed person-facing work terms.
    cancel_predecessor
        Whether successor creation must explicitly cancel nonterminal old demand.
    retained_commitments
        Historical decisions preserved, never copied to new demand.
    claims_affected
        Active claims cancelled by the explicit successor operation.
    confirmations_affected
        Active confirmations cancelled by the explicit successor operation.
    """

    action: ProgrammeStaffingAction
    changed_fields: tuple[str, ...]
    cancel_predecessor: bool
    retained_commitments: int
    claims_affected: int
    confirmations_affected: int


def _validated_demand(demand: ProgrammeStaffingDemandState) -> None:
    if (
        not isinstance(demand, ProgrammeStaffingDemandState)
        or not isinstance(demand.demand_id, UUID)
        or type(demand.version) is not int
        or not 1 <= demand.version < 2**63 - 1
        or not isinstance(demand.status, str)
        or demand.status not in {"draft", "open", "locked", "cancelled", "completed"}
        or not isinstance(demand.expectation, ProgrammeStaffingExpectation)
        or demand.expectation != demand.expectation.normalized()
    ):
        raise ProgrammeStaffingImpactError(
            "Complete current demand evidence is required."
        )
    counts = (demand.retained_commitments, demand.claimed, demand.confirmed)
    if (
        any(type(value) is not int or value < 0 for value in counts)
        or demand.retained_commitments > MAX_RETAINED_COVERAGE_COMMITMENTS
        or demand.claimed + demand.confirmed > demand.retained_commitments
        or demand.claimed + demand.confirmed > demand.expectation.required_headcount
        or (demand.status != "open" and demand.claimed)
        or (demand.status not in {"open", "locked"} and demand.confirmed)
    ):
        raise ProgrammeStaffingImpactError(
            "Complete consistent commitment counts are required."
        )


def evaluate_programme_staffing_impact(
    *,
    action: ProgrammeStaffingAction,
    expectation: ProgrammeStaffingExpectation,
    demand: ProgrammeStaffingDemandState | None,
) -> ProgrammeStaffingImpact:
    """Evaluate exact work changes without selecting sources or mutating decisions.

    Parameters
    ----------
    action : ProgrammeStaffingAction
        Deliberately chosen operation, not a browser-provided permission flag.
    expectation : ProgrammeStaffingExpectation
        Current independently resolved Programme requirement work terms.
    demand : ProgrammeStaffingDemandState | None
        Authorized exact demand evidence; absent only for creation.

    Returns
    -------
    ProgrammeStaffingImpact
        Consequences to show before the independently authorized command runs.

    Raises
    ------
    ProgrammeStaffingImpactError
        If evidence is incomplete, the action is untyped or its preconditions fail.

    Notes
    -----
    Scope, existing binding identity and source freshness belong to the owner
    query/command. This pure reducer establishes none of them. The command must
    resolve all evidence again under canonical locks, compare its preview token,
    and invoke existing Workforce lifecycle commands. No operation transfers a
    commitment, independently confirms a person or relocks coverage.
    """
    if (
        not isinstance(action, ProgrammeStaffingAction)
        or not isinstance(expectation, ProgrammeStaffingExpectation)
        or expectation != expectation.normalized()
    ):
        raise ProgrammeStaffingImpactError(
            "Use an explicit action and normalized work terms."
        )
    if action == ProgrammeStaffingAction.CREATE:
        if demand is not None:
            raise ProgrammeStaffingImpactError(
                "Creation requires an unbound requirement."
            )
        return ProgrammeStaffingImpact(
            action=action,
            changed_fields=(),
            cancel_predecessor=False,
            retained_commitments=0,
            claims_affected=0,
            confirmations_affected=0,
        )
    if demand is None:
        raise ProgrammeStaffingImpactError("Select the exact existing demand.")
    _validated_demand(demand)
    changed = tuple(
        field.name
        for field in fields(ProgrammeStaffingExpectation)
        if getattr(demand.expectation, field.name) != getattr(expectation, field.name)
    )
    if action in {ProgrammeStaffingAction.LINK, ProgrammeStaffingAction.RECONCILE}:
        if demand.status != "draft" or demand.retained_commitments:
            raise ProgrammeStaffingImpactError(
                "Only a draft without retained commitments is editable."
            )
        if action == ProgrammeStaffingAction.LINK and changed:
            raise ProgrammeStaffingImpactError(
                "Linking requires identical explicit work terms."
            )
        if "position_id" in changed:
            raise ProgrammeStaffingImpactError(
                "A changed Position requires a separate successor."
            )
    cancel = action == ProgrammeStaffingAction.SUCCESSOR and demand.status not in {
        "cancelled",
        "completed",
    }
    return ProgrammeStaffingImpact(
        action,
        changed,
        cancel,
        demand.retained_commitments,
        demand.claimed if cancel else 0,
        demand.confirmed if cancel else 0,
    )
