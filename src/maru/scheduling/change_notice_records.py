"""Scoped immutable notice facts; callers supply independent admission and locks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import F

from .change_catalogs import (
    MAX_CHANGE_NOTICE_FACTS,
    ChangeNoticeAction,
    ChangeRecipientPurpose,
)
from .change_inputs import ChangeRecipientSelection
from .change_lifecycle import ChangeNoticeState, _validate_state, advance_change_notice
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingUnavailableError,
)
from .models import SchedulingChangeNotice, SchedulingChangeNoticeEvidence

if TYPE_CHECKING:
    from uuid import UUID

    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class _NoticeRecord:
    notice: SchedulingChangeNotice
    state: ChangeNoticeState
    facts: tuple[SchedulingChangeNoticeEvidence, ...]


def _record(
    request: SchedulingReadRequest, notice_id: UUID, *, personal: bool = False
) -> _NoticeRecord:
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    selected = SchedulingChangeNotice.objects.filter(**ownership, id=notice_id).defer(
        "reason"
    )
    if personal:
        selected = selected.filter(recipient_id=request.actor_id)
    notice = selected.first()
    if notice is None:
        raise SchedulingUnavailableError
    facts = tuple(
        SchedulingChangeNoticeEvidence.objects.filter(**ownership, notice_id=notice.id)
        .defer("reason")
        .order_by("sequence")[: MAX_CHANGE_NOTICE_FACTS + 1]
    )
    state = ChangeNoticeState(notice.actor_id, notice.recipient_id)
    prior_time = notice.occurred_at
    try:
        _check_receipt(notice, "change_prepare", 1)
        _validate_state(state)
        if len(facts) > MAX_CHANGE_NOTICE_FACTS:
            raise SchedulingUnavailableError
        for fact in facts:
            if fact.sequence != state.version + 1 or fact.occurred_at < prior_time:
                raise SchedulingUnavailableError
            action = ChangeNoticeAction(fact.action)
            _check_receipt(fact, f"change_{action.value}", fact.sequence)
            state = advance_change_notice(
                state,
                actor_id=fact.actor_id,
                action=action,
                expected_version=state.version,
            )
            prior_time = fact.occurred_at
    except (ValueError, SchedulingLifecycleConflictError) as error:
        raise SchedulingUnavailableError from error
    return _NoticeRecord(notice, state, facts)


def _check_receipt(
    row: SchedulingChangeNotice | SchedulingChangeNoticeEvidence,
    operation: str,
    version: int,
) -> None:
    # Verify equality in SQL, returning only a boolean. Personal reads must not
    # materialize privileged rationale merely to verify immutable attribution.
    model = (
        SchedulingChangeNotice
        if isinstance(row, SchedulingChangeNotice)
        else SchedulingChangeNoticeEvidence
    )
    if not model.objects.filter(
        id=row.id,
        organization_id=row.organization_id,
        edition_id=row.edition_id,
        command_receipt__operation=operation,
        command_receipt__result_object_id=F("id"),
        command_receipt__resulting_version=version,
        command_receipt__organization_id=F("organization_id"),
        command_receipt__edition_id=F("edition_id"),
        command_receipt__actor_id=F("actor_id"),
        command_receipt__reason=F("reason"),
        command_receipt__occurred_at=F("occurred_at"),
    ).exists():
        raise SchedulingUnavailableError


def _selection(notice: SchedulingChangeNotice) -> ChangeRecipientSelection:
    try:
        purpose = ChangeRecipientPurpose(notice.recipient_purpose)
    except ValueError as error:
        raise SchedulingUnavailableError from error
    return ChangeRecipientSelection(
        purpose,
        notice.recipient_target_id,
        notice.recipient_id
        if purpose not in {ChangeRecipientPurpose.HOST, ChangeRecipientPurpose.WORK}
        else None,
    )
