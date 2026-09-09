"""Minimized staffing coverage semantics without disclosing personnel records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MAX_COVERAGE_HEADCOUNT = 1_024
MAX_RETAINED_COVERAGE_COMMITMENTS = 4_096


class StaffingCoverageIntegrityError(ValueError):
    """Reject incomplete or inconsistent owner evidence before disclosure."""


class StaffingSourceState(StrEnum):
    """Distinguish current authorized owner evidence from missing knowledge."""

    CURRENT = "current"
    UNBOUND = "unbound"
    STALE = "stale"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"


class StaffingCoverageState(StrEnum):
    """Explain operational coverage without conflating claims and acceptance."""

    UNREQUESTED = "unrequested"
    DRAFT = "draft"
    OPEN_GAP = "open_gap"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COVERED = "covered"
    REVIEW_REQUIRED = "review_required"
    LOCKED_UNDERFILLED = "locked_underfilled"
    LOCKED_COVERED = "locked_covered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STALE = "stale"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StaffingCoverageCounts:
    """Aggregate owner facts after independent scope and disclosure checks.

    Attributes
    ----------
    demand_state
        Exact Workforce demand lifecycle, never inferred from counts.
    required
        Published or draft headcount requested by the Workforce owner.
    claimed
        Active personal requests awaiting independent confirmation.
    confirmed
        Active confirmations including any now requiring evidence review.
    current_confirmed
        Confirmations whose qualification and shared availability remain current.
    retained
        All retained commitments, including removed and completed history.
    """

    demand_state: str
    required: int
    claimed: int
    confirmed: int
    current_confirmed: int
    retained: int


@dataclass(frozen=True, slots=True)
class StaffingCoverage:
    """Purpose-bounded result with unknown counts represented by null, not zero.

    Attributes
    ----------
    state
        Explainable coverage or source-availability outcome.
    current_confirmed
        Current independently confirmed people, or null when not established.
    uncovered
        Required places lacking current confirmation, or null when unknown.
    pending_claims
        Active unconfirmed personal claims, or null when unknown.
    draft_reconcilable
        Whether the source is current and the draft has no retained commitment.
        This is an advisory lifecycle fact, never mutation authority.
    """

    state: StaffingCoverageState
    current_confirmed: int | None = None
    uncovered: int | None = None
    pending_claims: int | None = None
    draft_reconcilable: bool = False


def _validate_counts(counts: StaffingCoverageCounts) -> None:
    if not isinstance(counts, StaffingCoverageCounts):
        raise StaffingCoverageIntegrityError(
            "Staffing coverage requires complete owner counts."
        )
    for value in (
        counts.required,
        counts.claimed,
        counts.confirmed,
        counts.current_confirmed,
        counts.retained,
    ):
        if type(value) is not int or value < 0:
            raise StaffingCoverageIntegrityError(
                "Staffing coverage counts must be nonnegative integers."
            )
    if (
        not 1 <= counts.required <= MAX_COVERAGE_HEADCOUNT
        or counts.claimed + counts.confirmed > counts.required
        or counts.current_confirmed > counts.confirmed
        or counts.retained < counts.claimed + counts.confirmed
        or counts.retained > MAX_RETAINED_COVERAGE_COMMITMENTS
    ):
        raise StaffingCoverageIntegrityError(
            "Staffing coverage counts violate the owner contract."
        )
    if counts.demand_state not in {"draft", "open", "locked", "completed", "cancelled"}:
        raise StaffingCoverageIntegrityError(
            "Staffing coverage has an unknown demand lifecycle."
        )
    if counts.demand_state in {"draft", "completed", "cancelled"} and (
        counts.claimed or counts.confirmed
    ):
        raise StaffingCoverageIntegrityError(
            "Inactive work cannot contain active coverage."
        )
    if counts.demand_state == "locked" and counts.claimed:
        raise StaffingCoverageIntegrityError(
            "Locked work cannot contain unconfirmed claims."
        )


def evaluate_staffing_coverage(
    *,
    source_state: StaffingSourceState,
    counts: StaffingCoverageCounts | None,
) -> StaffingCoverage:
    """Classify complete owner facts while withholding unavailable evidence.

    Parameters
    ----------
    source_state : StaffingSourceState
        Owner-resolved authority/freshness outcome, not a browser-supplied flag.
    counts : StaffingCoverageCounts | None
        Complete minimized counts after source binding and audit checks.
        Non-current source states never inspect or release this value.

    Returns
    -------
    StaffingCoverage
        A distinct operational state and only established current counts.

    Raises
    ------
    StaffingCoverageIntegrityError
        If the source state is untyped, or a current source has no complete counts.

    Notes
    -----
    This pure reducer grants no read or write authority. The public owner query
    must authorize, read a consistent snapshot, resolve exact source versions
    and audit before using it. Command preflight must recheck under owner locks.
    """
    if not isinstance(source_state, StaffingSourceState):
        raise StaffingCoverageIntegrityError("Use a typed staffing source state.")
    hidden_states = {
        StaffingSourceState.UNBOUND: StaffingCoverageState.UNREQUESTED,
        StaffingSourceState.STALE: StaffingCoverageState.STALE,
        StaffingSourceState.WITHHELD: StaffingCoverageState.WITHHELD,
        StaffingSourceState.UNAVAILABLE: StaffingCoverageState.UNAVAILABLE,
    }
    if source_state in hidden_states:
        return StaffingCoverage(hidden_states[source_state])
    if counts is None:
        raise StaffingCoverageIntegrityError(
            "A current staffing source needs complete owner counts."
        )
    _validate_counts(counts)
    if counts.demand_state in {"completed", "cancelled"}:
        return StaffingCoverage(StaffingCoverageState(counts.demand_state))
    uncovered = counts.required - counts.current_confirmed
    if counts.demand_state == "draft":
        state = StaffingCoverageState.DRAFT
    elif counts.current_confirmed != counts.confirmed:
        state = StaffingCoverageState.REVIEW_REQUIRED
    elif counts.demand_state == "locked":
        state = (
            StaffingCoverageState.LOCKED_UNDERFILLED
            if uncovered
            else StaffingCoverageState.LOCKED_COVERED
        )
    elif counts.claimed:
        state = StaffingCoverageState.AWAITING_CONFIRMATION
    else:
        state = (
            StaffingCoverageState.OPEN_GAP
            if uncovered
            else StaffingCoverageState.COVERED
        )
    return StaffingCoverage(
        state,
        counts.current_confirmed,
        uncovered,
        counts.claimed,
        counts.demand_state == "draft" and counts.retained == 0,
    )
