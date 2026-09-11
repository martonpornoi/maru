"""Closed category reduction for trusted release sources, never approval authority."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adoption import SCHEDULING_TIME_CONFLICT_SOURCE
from .catalogs import SchedulingConflictCode as Code
from .release_eligibility import (
    ReleaseCheck,
    ReleaseCheckState,
    ReleaseEvidenceInvalidError,
)

if TYPE_CHECKING:
    from .conflicts import SchedulingFinding


def combine_release_source_states(
    states: tuple[ReleaseCheckState, ...],
) -> ReleaseCheckState:
    """Reduce a complete source set without treating missing members as success.

    Parameters
    ----------
    states : tuple[ReleaseCheckState, ...]
        Complete closed owner consequences, not request-body flags.

    Returns
    -------
    ReleaseCheckState
        Unavailable, stale or blocked precedes success; all explicit inapplicable
        rows remain inapplicable, while an empty set is unavailable.

    Raises
    ------
    ReleaseEvidenceInvalidError
        If the immutable closed-state input contract is violated.
    """
    if type(states) is not tuple or any(
        type(state) is not ReleaseCheckState for state in states
    ):
        raise ReleaseEvidenceInvalidError
    if not states:
        return ReleaseCheckState.UNAVAILABLE
    for state in (
        ReleaseCheckState.UNAVAILABLE,
        ReleaseCheckState.STALE,
        ReleaseCheckState.BLOCKED,
    ):
        if state in states:
            return state
    return (
        ReleaseCheckState.SATISFIED
        if ReleaseCheckState.SATISFIED in states
        else ReleaseCheckState.NOT_APPLICABLE
    )


def release_category_for_planning_finding(finding: SchedulingFinding) -> ReleaseCheck:
    """Assign an existing exact time/host/physical finding to its release category.

    Parameters
    ----------
    finding : SchedulingFinding
        Trusted owner-evaluated planning consequence, not a complete release check.

    Returns
    -------
    ReleaseCheck
        Closed owning release category; limits remain a candidate-level failure.

    Notes
    -----
    The existing planning evaluator does not provide release staffing, independent
    copy approval, physical approval, exact accessibility fit or global rest. Those
    categories must be supplied independently; this mapping cannot invent them.
    """
    if finding.code in {Code.PROGRAMME_UNAVAILABLE, Code.ITEM_RETIRED}:
        return ReleaseCheck.PROGRAMME_READINESS
    if finding.code == Code.HOST_OVERLAP:
        return ReleaseCheck.PERSON_CONFLICTS
    if finding.code in {
        Code.HOST_REQUIRED,
        Code.HOST_NOT_CURRENT,
        Code.HOST_SOURCE_UNAVAILABLE,
        Code.HOST_UNAVAILABLE,
        Code.HOST_OUTSIDE_AVAILABILITY,
        Code.HOST_OUTSIDE_PREFERENCE,
    }:
        return ReleaseCheck.HOSTS
    if (
        finding.source_code == SCHEDULING_TIME_CONFLICT_SOURCE
        or finding.code == Code.EVALUATION_LIMIT
    ):
        return ReleaseCheck.CANDIDATE
    return ReleaseCheck.PHYSICAL_CONSTRAINTS


def release_state_from_readiness(state: str) -> ReleaseCheckState:
    """Preserve missing, stale and explicit readiness applicability distinctions.

    Parameters
    ----------
    state : str
        Current closed Programme concern, copy or assessment consequence.

    Returns
    -------
    ReleaseCheckState
        Exact release state; required but unevidenced and withdrawn are blocked,
        while absent, withheld, malformed and unavailable remain unavailable.
    """
    if state in {"satisfied", "not_applicable", "blocked", "stale", "unavailable"}:
        return ReleaseCheckState(state)
    if state in {"required", "withdrawn"}:
        return ReleaseCheckState.BLOCKED
    return ReleaseCheckState.UNAVAILABLE
