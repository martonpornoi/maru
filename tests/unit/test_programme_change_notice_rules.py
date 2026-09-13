"""Exact notice selections and independent facts cannot masquerade as delivery."""

from dataclasses import FrozenInstanceError, fields, replace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.change_inputs import (
    ChangeNoticeDecisionIntent,
    ChangeRecipientPurpose,
    ChangeRecipientSelection,
    PrepareChangeNoticeIntent,
)
from maru.scheduling.change_lifecycle import (
    ChangeNoticeAction,
    ChangeNoticeReview,
    ChangeNoticeState,
    advance_change_notice,
)
from maru.scheduling.command_support import (
    SchedulingLifecycleConflictError,
    SchedulingVersionConflictError,
)
from maru.scheduling.inputs import scheduling_digest


def preparation():
    return PrepareChangeNoticeIntent(
        uuid4(),
        uuid4(),
        4,
        ChangeRecipientSelection(ChangeRecipientPurpose.HOST, uuid4()),
        "a" * 64,
    )


def decision():
    return ChangeNoticeDecisionIntent(uuid4(), 1, "a" * 64)


def prepared():
    return ChangeNoticeState(uuid4(), uuid4())


def advance(state, action, actor=None):
    return advance_change_notice(
        state,
        actor_id=actor or uuid4(),
        action=action,
        expected_version=state.version,
    )


@pytest.mark.parametrize("purpose", list(ChangeRecipientPurpose))
def test_each_purpose_has_one_exact_non_interchangeable_selector(purpose):
    operator = (
        uuid4()
        if purpose not in {ChangeRecipientPurpose.HOST, ChangeRecipientPurpose.WORK}
        else None
    )
    selected = ChangeRecipientSelection(purpose, uuid4(), operator)
    assert selected.validated() is selected
    assert selected.payload() == {
        "purpose": purpose.value,
        "target_id": str(selected.target_id),
        "operator_account_id": str(operator) if operator is not None else None,
    }
    with pytest.raises(ValidationError):
        replace(selected, operator_account_id=None if operator else uuid4()).validated()


@pytest.mark.parametrize("value", [None, "private-marker", 1, UUID(int=0)])
def test_bad_identifiers_fail_before_serialization_without_echoing_input(value):
    for intent in (
        replace(preparation(), release_id=value),
        replace(preparation(), occurrence_id=value),
        replace(decision(), notice_id=value),
        ChangeRecipientSelection(ChangeRecipientPurpose.HOST, value),
        ChangeRecipientSelection(ChangeRecipientPurpose.ROOM, uuid4(), value),
    ):
        with pytest.raises(ValidationError) as caught:
            intent.payload()
        assert "private-marker" not in str(caught.value)


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5, 2**63 - 1])
def test_notice_and_pointer_versions_are_exact_positive_advanceable_integers(value):
    with pytest.raises(ValidationError):
        replace(preparation(), expected_pointer_version=value).validated()
    with pytest.raises(ValidationError):
        replace(decision(), expected_version=value).validated()


@pytest.mark.parametrize("value", [None, "", "A" * 64, "a" * 63, "a" * 64 + "\n"])
def test_preview_and_notice_digest_require_exact_lowercase_sha256(value):
    with pytest.raises(ValidationError):
        replace(preparation(), snapshot_digest=value).payload()
    with pytest.raises(ValidationError):
        replace(decision(), snapshot_digest=value).payload()


@pytest.mark.parametrize("value", [None, {}, "host", "private-marker"])
def test_closed_recipient_and_purpose_types_are_not_coerced(value):
    with pytest.raises(ValidationError):
        replace(preparation(), recipient=value).validated()
    with pytest.raises(ValidationError):
        ChangeRecipientSelection(value, uuid4()).validated()


def test_intents_are_immutable_minimized_and_every_exact_field_changes_retry_digest():
    intent = preparation()
    notice = decision()
    for value in (intent, intent.recipient, notice):
        assert value.validated() is value
        assert not {
            "actor_id",
            "recipient_id",
            "approved",
            "eligible",
            "delivered",
            "acknowledged",
            "contact",
            "message",
            "reason",
        } & {field.name for field in fields(value)}
        with pytest.raises(FrozenInstanceError):
            setattr(value, fields(value)[0].name, None)
    original = scheduling_digest(intent.payload())
    for changed in (
        replace(intent, release_id=uuid4()),
        replace(intent, occurrence_id=uuid4()),
        replace(intent, expected_pointer_version=5),
        replace(intent, snapshot_digest="b" * 64),
        replace(intent, recipient=replace(intent.recipient, target_id=uuid4())),
        replace(
            intent,
            recipient=replace(intent.recipient, purpose=ChangeRecipientPurpose.WORK),
        ),
    ):
        assert scheduling_digest(changed.payload()) != original
    for changed in (
        replace(notice, notice_id=uuid4()),
        replace(notice, expected_version=2),
        replace(notice, snapshot_digest="b" * 64),
    ):
        assert scheduling_digest(changed.payload()) != scheduling_digest(
            notice.payload()
        )


@pytest.mark.parametrize(
    "action", [ChangeNoticeAction.APPROVE, ChangeNoticeAction.REJECT]
)
def test_review_is_independent_and_one_shot(action):
    state = prepared()
    with pytest.raises(SchedulingLifecycleConflictError):
        advance(state, action, state.preparer_id)
    reviewer = uuid4()
    reviewed = advance(state, action, reviewer)
    assert reviewed.reviewer_id == reviewer
    assert reviewed.version == 2
    assert reviewed.review is (
        ChangeNoticeReview.APPROVED
        if action is ChangeNoticeAction.APPROVE
        else ChangeNoticeReview.REJECTED
    )
    assert state.review is None
    for another_action in (ChangeNoticeAction.APPROVE, ChangeNoticeAction.REJECT):
        with pytest.raises(SchedulingLifecycleConflictError):
            advance(reviewed, another_action)


@pytest.mark.parametrize("reviewed", [False, True])
@pytest.mark.parametrize(
    "action", [ChangeNoticeAction.HANDOFF, ChangeNoticeAction.ACKNOWLEDGE]
)
def test_unreviewed_and_rejected_packages_cannot_be_handed_off_or_acknowledged(
    reviewed, action
):
    state = prepared()
    if reviewed:
        state = advance(state, ChangeNoticeAction.REJECT)
    with pytest.raises(SchedulingLifecycleConflictError):
        advance(state, action, state.recipient_id)


@pytest.mark.parametrize("acknowledge_first", [False, True])
def test_handoff_and_exact_recipient_acknowledgement_are_independent_facts(
    acknowledge_first,
):
    state = advance(prepared(), ChangeNoticeAction.APPROVE)
    sender = uuid4()
    first, second = (
        (ChangeNoticeAction.ACKNOWLEDGE, ChangeNoticeAction.HANDOFF)
        if acknowledge_first
        else (ChangeNoticeAction.HANDOFF, ChangeNoticeAction.ACKNOWLEDGE)
    )
    for action in (first, second):
        before = state
        state = advance(
            state,
            action,
            state.recipient_id if action is ChangeNoticeAction.ACKNOWLEDGE else sender,
        )
        assert state.version == before.version + 1
        if action is first:
            assert (state.handed_off_by_id is None) is acknowledge_first
            assert (state.acknowledged_by_id is not None) is acknowledge_first
        with pytest.raises(SchedulingLifecycleConflictError):
            advance(state, action, state.recipient_id)
    assert state.version == 4
    assert state.handed_off_by_id == sender
    assert state.acknowledged_by_id == state.recipient_id


def test_no_sender_or_reviewer_can_acknowledge_for_the_recipient():
    state = advance(prepared(), ChangeNoticeAction.APPROVE)
    for actor in (state.preparer_id, state.reviewer_id, uuid4()):
        with pytest.raises(SchedulingLifecycleConflictError):
            advance(state, ChangeNoticeAction.ACKNOWLEDGE, actor)


def test_recipient_may_prepare_but_new_notice_starts_unacknowledged():
    state = prepared()
    state = replace(state, preparer_id=state.recipient_id)
    approved = advance(state, ChangeNoticeAction.APPROVE)
    acknowledged = advance(approved, ChangeNoticeAction.ACKNOWLEDGE, state.recipient_id)
    assert acknowledged.acknowledged_by_id == state.recipient_id
    assert ChangeNoticeState(state.preparer_id, state.recipient_id).version == 1
    assert state.acknowledged_by_id is None
    assert not {"delivered", "exported", "attendance", "work_accepted"} & {
        field.name for field in fields(state)
    }


@pytest.mark.parametrize("value", [True, None, 0, 2, "1", 1.0])
def test_stale_or_coerced_versions_cannot_advance(value):
    with pytest.raises(SchedulingVersionConflictError):
        advance_change_notice(
            prepared(),
            actor_id=uuid4(),
            action=ChangeNoticeAction.APPROVE,
            expected_version=value,
        )


@pytest.mark.parametrize("value", [None, "approve", "export", "delivered", {}])
def test_unknown_and_raw_string_actions_are_not_delivery_facts(value):
    with pytest.raises(SchedulingLifecycleConflictError):
        advance(prepared(), value)


@pytest.mark.parametrize("value", [None, "private-marker", UUID(int=0), 1])
def test_invalid_actual_actor_is_not_accepted(value):
    with pytest.raises(SchedulingLifecycleConflictError):
        advance_change_notice(
            prepared(),
            actor_id=value,
            action=ChangeNoticeAction.APPROVE,
            expected_version=1,
        )


def test_inconsistent_retained_facts_fail_closed_before_any_transition():
    state = prepared()
    approved = advance(state, ChangeNoticeAction.APPROVE)
    invalid = (
        None,
        {},
        replace(state, preparer_id=UUID(int=0)),
        replace(state, recipient_id="private-marker"),
        replace(state, reviewer_id=uuid4()),
        replace(state, review=ChangeNoticeReview.APPROVED),
        replace(state, handed_off_by_id=uuid4()),
        replace(state, acknowledged_by_id=state.recipient_id),
        replace(state, version=True),
        replace(state, version=2),
        replace(approved, reviewer_id=state.preparer_id),
        replace(approved, reviewer_id=UUID(int=0)),
        replace(approved, review="approved"),
        replace(approved, acknowledged_by_id=uuid4(), version=3),
        replace(approved, handed_off_by_id="private-marker", version=3),
        replace(
            approved,
            review=ChangeNoticeReview.REJECTED,
            acknowledged_by_id=state.recipient_id,
            version=3,
        ),
    )
    for value in invalid:
        with pytest.raises(SchedulingLifecycleConflictError):
            advance_change_notice(
                value,
                actor_id=uuid4(),
                action=ChangeNoticeAction.HANDOFF,
                expected_version=2,
            )
