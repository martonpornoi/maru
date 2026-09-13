"""Notice orchestration, exact retries, source locks and disclosure boundaries."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.scheduling import change_notice_commands as commands
from maru.scheduling import change_notice_queries as queries
from maru.scheduling import change_notice_records as records
from maru.scheduling import command_support
from maru.scheduling.authorization import DEFAULT_SCHEDULING_AUTHORIZER
from maru.scheduling.catalogs import SchedulingOperation
from maru.scheduling.change_catalogs import (
    ChangeNoticeAction,
    ChangeNoticeReview,
    ChangeNoticeSourceState,
    ChangeRecipientPurpose,
)
from maru.scheduling.change_inputs import (
    ChangeNoticeDecisionIntent,
    ChangeRecipientSelection,
    PrepareChangeNoticeIntent,
)
from maru.scheduling.change_lifecycle import ChangeNoticeState
from maru.scheduling.change_notice_sources import ProgrammeChangeNoticePreview
from maru.scheduling.command_support import (
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.inputs import SchedulingCommandRequest


@pytest.fixture
def world(monkeypatch):
    request = SchedulingCommandRequest(
        *(UUID(int=n) for n in range(10, 15)),
        reason="Synthetic operator reason",
    )
    recipient = UUID(int=20)
    selection = ChangeRecipientSelection(
        ChangeRecipientPurpose.ROOM, UUID(int=21), recipient
    )
    preview = ProgrammeChangeNoticePreview(
        UUID(int=22),
        UUID(int=23),
        2,
        ChangeNoticeSourceState.INVALIDATED,
        recipient,
        "Synthetic recipient",
        selection,
        "a" * 64,
        "b" * 64,
        None,
    )
    notice = SimpleNamespace(
        id=UUID(int=24),
        actor_id=UUID(int=25),
        recipient_id=recipient,
        release_id=preview.release_id,
        occurrence_id=preview.occurrence_id,
        recipient_purpose=selection.purpose.value,
        recipient_target_id=selection.target_id,
        snapshot_digest=preview.snapshot_digest,
        pointer_version=preview.pointer_version,
        source_state=preview.source_state.value,
        reason="Restricted organizer reason",
    )
    state = ChangeNoticeState(notice.actor_id, recipient)
    captured = {}

    def execute(actual, **kwargs):
        captured.update(kwargs)
        captured["request"] = actual
        return "synthetic result"

    monkeypatch.setattr(commands, "_execute", execute)
    source = Mock(return_value=preview)
    sender = Mock(return_value=SimpleNamespace(preview=preview))
    personal = Mock(return_value=SimpleNamespace(preview=preview))
    freeze = Mock()
    record = SimpleNamespace(notice=notice, state=state, facts=())
    loader = Mock(return_value=record)
    monkeypatch.setattr(commands, "preview_programme_change_notice", source)
    monkeypatch.setattr(commands, "load_programme_change_notice", sender)
    monkeypatch.setattr(commands, "load_personal_programme_change_notice", personal)
    monkeypatch.setattr(commands, "_freeze_sources", freeze)
    monkeypatch.setattr(commands, "_record", loader)
    return SimpleNamespace(
        request=request,
        read=commands._read_request(request),
        preview=preview,
        notice=notice,
        state=state,
        source=source,
        sender=sender,
        personal=personal,
        freeze=freeze,
        loader=loader,
        record=record,
        captured=captured,
        prepare=PrepareChangeNoticeIntent(
            preview.release_id,
            preview.occurrence_id,
            preview.pointer_version,
            selection,
            preview.snapshot_digest,
        ),
        decision=ChangeNoticeDecisionIntent(notice.id, 1, preview.snapshot_digest),
    )


def test_preparation_has_independent_capability_and_exact_replay_hook(world):
    assert (
        commands.prepare_programme_change_notice(world.request, world.prepare)
        == "synthetic result"
    )
    call = world.captured
    assert call["capability"] == "scheduling.prepare_change_notices"
    assert call["operation"] is SchedulingOperation.CHANGE_PREPARE
    assert call["authorizer"] is DEFAULT_SCHEDULING_AUTHORIZER
    assert call["normalize"]() == world.prepare
    assert call["payload"](world.prepare) == world.prepare.payload()
    assert call["prepare"](world.prepare) == world.preview
    world.source.assert_called_once_with(
        world.read,
        release_id=world.prepare.release_id,
        occurrence_id=world.prepare.occurrence_id,
        recipient=world.prepare.recipient,
    )
    world.freeze.assert_called_once_with(world.read, world.preview)
    assert callable(call["revalidate_replay"])


def test_preparation_replay_requires_the_notices_own_exact_receipt(world):
    commands.prepare_programme_change_notice(world.request, world.prepare)
    receipt = SimpleNamespace(
        id=UUID(int=60),
        operation=SchedulingOperation.CHANGE_PREPARE,
        resulting_version=1,
        result_object_id=world.notice.id,
    )
    world.notice.command_receipt_id = receipt.id
    world.notice.actor_id = world.request.actor_id
    world.captured["revalidate_replay"](world.prepare, receipt)
    world.freeze.assert_called_once()
    world.notice.command_receipt_id = UUID(int=61)
    with pytest.raises(SchedulingUnavailableError):
        world.captured["revalidate_replay"](world.prepare, receipt)
    assert world.freeze.call_count == 1


@pytest.mark.parametrize(
    ("field", "value"), [("snapshot_digest", "c" * 64), ("expected_pointer_version", 3)]
)
def test_preparation_never_freezes_or_writes_stale_preview(world, field, value):
    with pytest.raises(SchedulingVersionConflictError):
        commands._prepare(world.request, replace(world.prepare, **{field: value}))
    world.freeze.assert_not_called()


@pytest.mark.parametrize("action", list(ChangeNoticeAction))
def test_decision_routes_actual_self_separately_and_freezes_after_rules(world, action):
    request = world.request
    if action in {ChangeNoticeAction.HANDOFF, ChangeNoticeAction.ACKNOWLEDGE}:
        world.record.state = replace(
            world.state,
            version=2,
            review=ChangeNoticeReview.APPROVED,
            reviewer_id=UUID(int=30),
        )
        world.decision = replace(world.decision, expected_version=2)
    if action is ChangeNoticeAction.ACKNOWLEDGE:
        request = replace(request, actor_id=world.notice.recipient_id)
        commands.acknowledge_programme_change_notice(
            commands._read_request(request),
            world.decision,
            idempotency_key=request.idempotency_key,
        )
        assert world.captured["request"].reason == commands._ACKNOWLEDGEMENT_REASON
        assert world.captured["request"].source_channel == "programme-change-self"
    elif action is ChangeNoticeAction.HANDOFF:
        commands.handoff_programme_change_notice(request, world.decision)
    else:
        commands.review_programme_change_notice(request, world.decision, action=action)
    prepared = world.captured["prepare"](world.decision)
    assert prepared.action is action
    assert prepared.sequence == world.decision.expected_version + 1
    assert world.captured["operation"].value == f"change_{action.value}"
    if action is ChangeNoticeAction.ACKNOWLEDGE:
        world.personal.assert_called_once()
        world.sender.assert_not_called()
        assert world.loader.call_args.kwargs == {"personal": True}
    else:
        world.sender.assert_called_once()
        world.personal.assert_not_called()
    world.freeze.assert_called_once()


def test_preparer_cannot_review_their_own_notice(world):
    world.record.state = replace(world.state, preparer_id=world.request.actor_id)
    commands.review_programme_change_notice(
        world.request,
        world.decision,
        action=ChangeNoticeAction.APPROVE,
    )
    with pytest.raises(SchedulingLifecycleConflictError):
        world.captured["prepare"](world.decision)
    world.freeze.assert_not_called()


def test_review_replay_checks_retained_fact_without_repeating_transition(world):
    commands.review_programme_change_notice(
        world.request,
        world.decision,
        action=ChangeNoticeAction.APPROVE,
    )
    fact = SimpleNamespace(
        id=UUID(int=40),
        command_receipt_id=UUID(int=41),
        actor_id=world.request.actor_id,
        action="approve",
        sequence=2,
    )
    world.record.facts = (fact,)
    world.record.state = replace(
        world.state,
        version=2,
        review=ChangeNoticeReview.APPROVED,
        reviewer_id=world.request.actor_id,
    )
    receipt = SimpleNamespace(
        id=fact.command_receipt_id,
        result_object_id=fact.id,
        operation=SchedulingOperation.CHANGE_APPROVE,
        resulting_version=2,
    )
    world.captured["revalidate_replay"](world.decision, receipt)
    world.freeze.assert_called_once()
    fact.actor_id = UUID(int=99)
    with pytest.raises(SchedulingUnavailableError):
        world.captured["revalidate_replay"](world.decision, receipt)
    assert world.freeze.call_count == 1


@pytest.mark.parametrize("replay", [False, True])
def test_revoked_or_stale_source_stops_first_action_and_exact_retry(world, replay):
    commands.review_programme_change_notice(
        world.request,
        world.decision,
        action=ChangeNoticeAction.APPROVE,
    )
    world.sender.side_effect = SchedulingVersionConflictError
    callback = (
        world.captured["revalidate_replay"] if replay else world.captured["prepare"]
    )
    arguments = (world.decision, object()) if replay else (world.decision,)
    with pytest.raises(SchedulingVersionConflictError):
        callback(*arguments)
    world.freeze.assert_not_called()


def test_new_fact_uses_own_receipt_and_no_copied_message(world, monkeypatch):
    commands.review_programme_change_notice(
        world.request,
        world.decision,
        action=ChangeNoticeAction.APPROVE,
    )
    prepared = world.captured["prepare"](world.decision)
    create = Mock(return_value=SimpleNamespace(id=UUID(int=50), sequence=2))
    monkeypatch.setattr(
        commands.SchedulingChangeNoticeEvidence.objects, "create", create
    )
    context = SimpleNamespace(
        receipt_id=UUID(int=51), evidence=lambda: {"reason": "Reviewed"}
    )
    assert world.captured["write"](context, world.decision, prepared) == (
        UUID(int=50),
        2,
    )
    assert set(create.call_args.kwargs) == {
        "id",
        "reason",
        "command_receipt_id",
        "notice_id",
        "action",
        "sequence",
    }
    assert create.call_args.kwargs["command_receipt_id"] == context.receipt_id


def test_personal_detail_excludes_reviewer_preparer_and_rationale(world, monkeypatch):
    detail = queries.ProgrammeChangeNotice(
        world.notice.id,
        world.preview,
        replace(
            world.state,
            version=2,
            review=ChangeNoticeReview.APPROVED,
            reviewer_id=UUID(int=30),
        ),
        "Never disclose this organizer rationale",
    )
    load = Mock(return_value=detail)
    admission = Mock(side_effect=lambda _request, **kwargs: kwargs["loader"](object()))
    monkeypatch.setattr(queries, "_detail", load)
    monkeypatch.setattr(queries, "_read", admission)
    result = queries.load_personal_programme_change_notice(
        world.read, notice_id=world.notice.id
    )
    assert set(asdict(result)) == {
        "notice_id",
        "preview",
        "version",
        "handed_off",
        "acknowledged",
    }
    assert "rationale" not in repr(result)
    assert admission.call_args.kwargs["capability"] == "scheduling.view_change_self"
    assert admission.call_args.kwargs["fields"] == frozenset({"own_change_notices"})
    load.assert_called_once_with(world.read, world.notice.id, personal=True)


@pytest.mark.parametrize("personal", [False, True])
def test_detail_does_not_restore_old_content_when_source_changes(
    world, monkeypatch, personal
):
    world.record.state = replace(
        world.state,
        version=2,
        review=ChangeNoticeReview.APPROVED,
        reviewer_id=UUID(int=30),
    )
    monkeypatch.setattr(queries, "_record", world.loader)
    preview = Mock(return_value=replace(world.preview, snapshot_digest="c" * 64))
    monkeypatch.setattr(queries, "_fresh_preview", preview)
    with pytest.raises(SchedulingVersionConflictError):
        queries._detail(world.read, world.notice.id, personal=personal)
    assert preview.call_args.kwargs["personal"] is personal


def test_personal_unapproved_notice_does_not_load_any_source(world, monkeypatch):
    monkeypatch.setattr(queries, "_record", world.loader)
    preview = Mock()
    monkeypatch.setattr(queries, "_fresh_preview", preview)
    with pytest.raises(SchedulingUnavailableError):
        queries._detail(world.read, world.notice.id, personal=True)
    preview.assert_not_called()


def test_personal_composer_never_materializes_organizer_rationale(world, monkeypatch):
    original = world.notice

    class WithoutRationale:
        def __getattr__(self, name):
            if name == "reason":
                raise AssertionError("Personal query fetched organizer rationale")
            return getattr(original, name)

    world.record.notice = WithoutRationale()
    world.record.state = replace(
        world.state,
        version=2,
        review=ChangeNoticeReview.APPROVED,
        reviewer_id=UUID(int=30),
    )
    monkeypatch.setattr(queries, "_record", world.loader)
    monkeypatch.setattr(queries, "_fresh_preview", Mock(return_value=world.preview))
    assert queries._detail(world.read, world.notice.id, personal=True).reason == ""


@pytest.mark.parametrize(
    "model", [records.SchedulingChangeNotice, records.SchedulingChangeNoticeEvidence]
)
@pytest.mark.parametrize("matches", [True, False])
def test_receipt_equality_is_a_scoped_boolean_query_not_private_field_projection(
    monkeypatch,
    model,
    matches,
):
    row = model(id=UUID(int=1), organization_id=UUID(int=2), edition_id=UUID(int=3))
    found = Mock()
    found.exists.return_value = matches
    selected = Mock(return_value=found)
    monkeypatch.setattr(model.objects, "filter", selected)
    if matches:
        records._check_receipt(row, "change_prepare", 1)
    else:
        with pytest.raises(SchedulingUnavailableError):
            records._check_receipt(row, "change_prepare", 1)
    arguments = selected.call_args.kwargs
    assert arguments["organization_id"] == row.organization_id
    assert arguments["edition_id"] == row.edition_id
    assert arguments["command_receipt__reason"].name == "reason"
    assert arguments["command_receipt__actor_id"].name == "actor_id"
    assert arguments["command_receipt__result_object_id"].name == "id"


@pytest.fixture
def replay_world(monkeypatch):
    request = SchedulingCommandRequest(
        *(UUID(int=n) for n in range(1, 6)),
        reason="Synthetic reason",
    )
    order = []
    receipt = SimpleNamespace(
        id=UUID(int=10),
        result_object_id=UUID(int=11),
        resulting_version=2,
        control_version=5,
        request_digest="exact",
    )
    monkeypatch.setattr(
        command_support, "scheduling_digest", Mock(return_value="exact")
    )
    monkeypatch.setattr(command_support, "scheduling_writer", nullcontext)
    monkeypatch.setattr(command_support.transaction, "atomic", nullcontext)
    monkeypatch.setattr(command_support, "lock_programme_staffing_scope", Mock())
    monkeypatch.setattr(
        command_support,
        "resolve_scheduling_edition_reference",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(command_support, "_audit", Mock())
    monkeypatch.setattr(
        command_support,
        "authorize_scheduling_scope",
        Mock(
            side_effect=lambda **kwargs: (
                order.append("final" if kwargs.get("lock") else "initial") or object()
            )
        ),
    )
    queryset = Mock()
    queryset.first.return_value = receipt
    monkeypatch.setattr(
        command_support.SchedulingCommandReceipt.objects,
        "filter",
        Mock(return_value=queryset),
    )
    return SimpleNamespace(request=request, receipt=receipt, order=order)


def _execute_replay(world, hook):
    return command_support._execute(
        world.request,
        operation=SchedulingOperation.CHANGE_APPROVE,
        capability="scheduling.review_change_notices",
        normalize=lambda: "intent",
        payload=lambda _intent: {},
        prepare=Mock(side_effect=AssertionError),
        write=Mock(side_effect=AssertionError),
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        revalidate_replay=hook,
    )


def test_generic_replay_requires_notice_proof_before_final_actor_lock(replay_world):
    def proof(intent, receipt):
        assert intent == "intent"
        assert receipt is replay_world.receipt
        replay_world.order.append("proof")

    result = _execute_replay(replay_world, proof)
    assert result.replayed
    assert replay_world.order[-2:] == ["proof", "final"]
    assert result.object_id == replay_world.receipt.result_object_id


def test_missing_notice_replay_hook_fails_closed(replay_world):
    with pytest.raises(SchedulingUnavailableError):
        _execute_replay(replay_world, None)


def test_conflicting_retry_never_discovers_notice_sources(replay_world):
    replay_world.receipt.request_digest = "different"
    hook = Mock()
    with pytest.raises(SchedulingIdempotencyConflictError):
        _execute_replay(replay_world, hook)
    hook.assert_not_called()


def test_failed_replay_proof_never_returns_retained_result(replay_world):
    with pytest.raises(SchedulingUnavailableError):
        _execute_replay(replay_world, Mock(side_effect=SchedulingUnavailableError))
    assert "final" not in replay_world.order


@pytest.mark.parametrize(
    "variant", ["valid", "moved", "missing", "isolation", "outside_transaction"]
)
def test_generation_freeze_uses_complete_keys_then_checks_exact_snapshot(
    monkeypatch, variant
):
    order = []
    key, second = UUID(int=1), UUID(int=2)
    request = SimpleNamespace(organization_id=UUID(int=3), edition_id=UUID(int=4))
    preview = SimpleNamespace(release_id=UUID(int=5), dependency_digest="expected")
    cursor = Mock()
    cursor.fetchone.return_value = (
        "repeatable read" if variant == "isolation" else "read committed",
    )
    monkeypatch.setattr(
        commands,
        "connection",
        SimpleNamespace(
            in_atomic_block=variant != "outside_transaction",
            cursor=lambda: nullcontext(cursor),
        ),
    )
    monkeypatch.setattr(commands, "require_scheduling_writer", Mock())
    monkeypatch.setattr(commands, "_approval_ids", Mock(return_value=(UUID(int=6),)))
    releases = Mock()
    releases.first.return_value = SimpleNamespace()
    monkeypatch.setattr(
        commands.SchedulingRelease.objects, "filter", Mock(return_value=releases)
    )
    uses = Mock()
    # One dependency legitimately has two placement uses; lock it only once.
    uses.order_by.return_value.values_list.return_value = (key, key, second)
    monkeypatch.setattr(
        commands.SchedulingReleaseApprovalDependency.objects,
        "filter",
        Mock(return_value=uses),
    )
    keys = Mock()
    keys.filter.return_value.order_by.return_value.values_list.side_effect = (
        lambda *_args, **_kwargs: (
            order.append("locked")
            or ((key,) if variant == "missing" else (key, second))
        )
    )
    acquire = Mock(return_value=keys)
    monkeypatch.setattr(
        commands.SchedulingReleaseDependencyKey.objects, "select_for_update", acquire
    )
    generation = Mock(
        side_effect=lambda *_args: (
            order.append("checked") or ("moved" if variant == "moved" else "expected")
        )
    )
    monkeypatch.setattr(commands, "_generation_digest", generation)
    if variant == "valid":
        commands._freeze_sources(request, preview)
        assert order == ["locked", "checked"]
        keys.filter.assert_called_once_with(id__in={key, second})
        keys.filter.return_value.order_by.assert_called_once_with("kind", "source_id")
    else:
        error = (
            SchedulingUnavailableError
            if variant in {"isolation", "outside_transaction"}
            else SchedulingVersionConflictError
        )
        with pytest.raises(error):
            commands._freeze_sources(request, preview)
        if variant in {"isolation", "outside_transaction"}:
            acquire.assert_not_called()
        if variant == "missing":
            generation.assert_not_called()


def test_record_requires_exact_recipient_scope_and_contiguous_receipted_facts(
    monkeypatch,
):
    request = SimpleNamespace(
        organization_id=UUID(int=1), edition_id=UUID(int=2), actor_id=UUID(int=3)
    )
    now = datetime(2026, 9, 13, tzinfo=UTC)
    notice = SimpleNamespace(
        id=UUID(int=4),
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        actor_id=UUID(int=5),
        recipient_id=request.actor_id,
        occurred_at=now,
        reason="Restricted",
    )
    receipt = SimpleNamespace(
        operation="change_prepare",
        result_object_id=notice.id,
        resulting_version=1,
        organization_id=notice.organization_id,
        edition_id=notice.edition_id,
        actor_id=notice.actor_id,
        occurred_at=now,
        reason=notice.reason,
    )
    notice.command_receipt = receipt
    notices = Mock()
    notices.defer.return_value = notices
    notices.filter.return_value.first.return_value = notice
    scoped = Mock(return_value=notices)
    monkeypatch.setattr(records.SchedulingChangeNotice.objects, "filter", scoped)
    facts = Mock()
    facts.defer.return_value.order_by.return_value = ()
    monkeypatch.setattr(
        records.SchedulingChangeNoticeEvidence.objects,
        "filter",
        Mock(return_value=facts),
    )
    receipt_check = Mock()
    monkeypatch.setattr(records, "_check_receipt", receipt_check)
    result = records._record(request, notice.id, personal=True)
    assert result.state.version == 1
    notices.filter.assert_called_once_with(recipient_id=request.actor_id)
    scoped.assert_called_once_with(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        id=notice.id,
    )
    notices.defer.assert_called_with("reason")
    facts.defer.assert_called_with("reason")
    receipt_check.assert_called_once_with(notice, "change_prepare", 1)
    receipt_check.side_effect = SchedulingUnavailableError
    with pytest.raises(SchedulingUnavailableError):
        records._record(request, notice.id, personal=True)
