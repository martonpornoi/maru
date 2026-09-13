"""Pure notice evidence rules, separate from authority, storage and delivery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from .change_catalogs import ChangeNoticeAction, ChangeNoticeReview
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingVersionConflictError,
)


@dataclass(frozen=True, slots=True)
class ChangeNoticeState:
    """Minimal projection of retained facts for one exact immutable package.

    Attributes
    ----------
    preparer_id
        Real person who prepared this exact notice, not a supplied display name.
    recipient_id
        Exact owner-resolved person; only this person can acknowledge.
    version
        One preparation plus the number of distinct retained subsequent facts.
    review
        One independent approval or rejection, never an implicit default.
    reviewer_id
        Actual independent reviewer, present exactly when review is present.
    handed_off_by_id
        Person recording one manual handoff claim, not delivery-provider proof.
    acknowledged_by_id
        Exact recipient's acknowledgement of this package, independent of handoff.
    """

    preparer_id: UUID
    recipient_id: UUID
    version: int = 1
    review: ChangeNoticeReview | None = None
    reviewer_id: UUID | None = None
    handed_off_by_id: UUID | None = None
    acknowledged_by_id: UUID | None = None


def _validate_state(state: ChangeNoticeState) -> None:
    if type(state) is not ChangeNoticeState:
        raise SchedulingLifecycleConflictError
    for value in (state.preparer_id, state.recipient_id):
        if type(value) is not UUID or value.int == 0:
            raise SchedulingLifecycleConflictError
    for optional_actor in (
        state.reviewer_id,
        state.handed_off_by_id,
        state.acknowledged_by_id,
    ):
        if optional_actor is not None and (
            type(optional_actor) is not UUID or optional_actor.int == 0
        ):
            raise SchedulingLifecycleConflictError
    if (
        (state.review is None) != (state.reviewer_id is None)
        or (state.review is not None and type(state.review) is not ChangeNoticeReview)
        or state.reviewer_id == state.preparer_id
        or (
            state.acknowledged_by_id is not None
            and state.acknowledged_by_id != state.recipient_id
        )
        or (
            state.review is not ChangeNoticeReview.APPROVED
            and (
                state.handed_off_by_id is not None
                or state.acknowledged_by_id is not None
            )
        )
    ):
        raise SchedulingLifecycleConflictError
    facts = sum(
        value is not None
        for value in (
            state.review,
            state.handed_off_by_id,
            state.acknowledged_by_id,
        )
    )
    if type(state.version) is not int or state.version != 1 + facts:
        raise SchedulingLifecycleConflictError


def advance_change_notice(
    state: ChangeNoticeState,
    *,
    actor_id: UUID,
    action: ChangeNoticeAction,
    expected_version: int,
) -> ChangeNoticeState:
    """Check one fact transition without granting authority or writing evidence.

    Parameters
    ----------
    state : ChangeNoticeState
        Owner-collected current evidence for one exact immutable notice package.
    actor_id : UUID
        Actual authenticated person, never a delegated acknowledgement subject.
    action : ChangeNoticeAction
        Closed independent review, manual handoff or exact-recipient action.
    expected_version : int
        Caller-observed evidence version, not permission to overwrite stale state.

    Returns
    -------
    ChangeNoticeState
        Immutable resulting projection. The command must atomically persist the
        corresponding evidence, receipt, audit and registered event.

    Raises
    ------
    SchedulingLifecycleConflictError
        If state is inconsistent, review is not independent, acknowledgement is
        not by the exact recipient, or the requested fact already exists.
    SchedulingVersionConflictError
        If the observed evidence version differs or has an invalid type.

    Notes
    -----
    This pure rule never authenticates state, source freshness, recipient purpose,
    tenant scope or capability. Commands must independently enforce all of them,
    including on an exact receipt replay. A repeated fact is not idempotency;
    only the matching command receipt can prove that the original intent ran.
    An approved notice can be acknowledged before a manual handoff. Rejection
    closes this package; it cannot be edited or later silently approved.
    """
    _validate_state(state)
    if type(actor_id) is not UUID or actor_id.int == 0:
        raise SchedulingLifecycleConflictError
    if type(action) is not ChangeNoticeAction:
        raise SchedulingLifecycleConflictError
    if type(expected_version) is not int or expected_version != state.version:
        raise SchedulingVersionConflictError
    if action in {ChangeNoticeAction.APPROVE, ChangeNoticeAction.REJECT}:
        if state.review is not None or actor_id == state.preparer_id:
            raise SchedulingLifecycleConflictError
        result = replace(
            state,
            review=(
                ChangeNoticeReview.APPROVED
                if action is ChangeNoticeAction.APPROVE
                else ChangeNoticeReview.REJECTED
            ),
            reviewer_id=actor_id,
            version=state.version + 1,
        )
    else:
        if state.review is not ChangeNoticeReview.APPROVED:
            raise SchedulingLifecycleConflictError
        if action is ChangeNoticeAction.HANDOFF:
            if state.handed_off_by_id is not None:
                raise SchedulingLifecycleConflictError
            result = replace(
                state, handed_off_by_id=actor_id, version=state.version + 1
            )
        else:
            if actor_id != state.recipient_id or state.acknowledged_by_id is not None:
                raise SchedulingLifecycleConflictError
            result = replace(
                state, acknowledged_by_id=actor_id, version=state.version + 1
            )
    _validate_state(result)
    return result
