"""Exact-source binding and actual-actor composition without database execution."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling import change_notice_queries as queries
from maru.scheduling import change_notice_sources as sources
from maru.scheduling import planning_queries
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_NOTICES,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.change_catalogs import (
    ChangeNoticeSourceState,
    ChangeRecipientPurpose,
)
from maru.scheduling.change_inputs import ChangeRecipientSelection
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.operator_release_impact import (
    OperatorOccurrenceChange,
    OperatorReleaseImpact,
)
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.release_impact import ReleaseSelectionChangeKind
from maru.scheduling.release_queries import ProgrammeReleaseState
from maru.workforce.personal_programme_links import PersonalProgrammeWorkLink


@pytest.fixture
def world(monkeypatch):
    request = planning_queries.SchedulingReadRequest(
        *(UUID(int=n) for n in range(10, 14))
    )
    recipient = ChangeRecipientSelection(
        ChangeRecipientPurpose.ROOM, UUID(int=20), UUID(int=21)
    )
    release = SimpleNamespace(id=UUID(int=22), previous_release_id=None)
    occurrence_id = UUID(int=23)
    change = OperatorOccurrenceChange(
        occurrence_id, ReleaseSelectionChangeKind.ADDED, None, None, ()
    )
    generations = Mock(return_value="a" * 64)
    membership = Mock()
    monkeypatch.setattr(sources, "_generation_digest", generations)
    monkeypatch.setattr(sources, "_suppressed_membership", membership)
    arguments = {
        "release": release,
        "occurrence_id": occurrence_id,
        "pointer_version": 2,
        "state": ProgrammeReleaseState.AVAILABLE,
        "recipient_id": recipient.operator_account_id,
        "recipient_label": "Synthetic operator",
        "recipient": recipient,
        "purpose_proof": {"version": 1},
        "changes": (change,),
    }
    return SimpleNamespace(
        request=request,
        recipient=recipient,
        release=release,
        occurrence_id=occurrence_id,
        change=change,
        generations=generations,
        membership=membership,
        arguments=arguments,
    )


def test_digest_excludes_labels_and_actor_but_not_exact_recipient(world):
    original = sources._finish(world.request, **world.arguments)
    own = sources._finish(
        replace(world.request, actor_id=world.recipient.operator_account_id),
        **{**world.arguments, "recipient_label": "You"},
    )
    assert own.snapshot_digest == original.snapshot_digest
    assert own.recipient_label != original.recipient_label
    assert set(asdict(original)) == {
        "release_id",
        "occurrence_id",
        "pointer_version",
        "source_state",
        "recipient_id",
        "recipient_label",
        "recipient",
        "snapshot_digest",
        "dependency_digest",
        "change",
    }
    other = sources._finish(
        world.request, **{**world.arguments, "recipient_id": UUID(int=99)}
    )
    assert other.snapshot_digest != original.snapshot_digest
    world.membership.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pointer_version", 3),
        ("occurrence_id", UUID(int=55)),
        (
            "recipient",
            ChangeRecipientSelection(
                ChangeRecipientPurpose.DEPARTMENT, UUID(int=20), UUID(int=21)
            ),
        ),
        ("purpose_proof", {"version": 2}),
    ],
)
def test_material_binding_changes_digest(world, field, value):
    original = sources._finish(world.request, **world.arguments)
    arguments = {**world.arguments, field: value}
    if field == "occurrence_id":
        arguments["changes"] = (replace(world.change, occurrence_id=value),)
    assert sources._finish(world.request, **arguments).snapshot_digest != (
        original.snapshot_digest
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ProgrammeReleaseState.WITHDRAWN, ChangeNoticeSourceState.WITHDRAWN),
        (ProgrammeReleaseState.INVALIDATED, ChangeNoticeSourceState.INVALIDATED),
        (
            ProgrammeReleaseState.AVAILABLE,
            ChangeNoticeSourceState.COMPARISON_SUPPRESSED,
        ),
    ],
)
def test_suppression_has_no_old_content_or_fabricated_removal(world, state, expected):
    arguments = {**world.arguments, "state": state, "changes": None}
    result = sources._finish(world.request, **arguments)
    assert result.source_state is expected
    assert result.change is None
    world.membership.assert_called_once_with(
        world.request,
        world.release,
        world.occurrence_id,
        world.recipient,
        operator=None,
    )
    world.generations.return_value = "b" * 64
    assert sources._finish(world.request, **arguments).snapshot_digest != (
        result.snapshot_digest
    )


@pytest.mark.parametrize("variant", ["empty", "other", "duplicate", "unchanged"])
def test_absent_duplicate_or_unchanged_occurrence_cannot_prepare_notice(world, variant):
    changes = {
        "empty": (),
        "other": (replace(world.change, occurrence_id=UUID(int=99)),),
        "duplicate": (world.change, world.change),
        "unchanged": (
            replace(world.change, kind=ReleaseSelectionChangeKind.UNCHANGED),
        ),
    }[variant]
    with pytest.raises(SchedulingUnavailableError):
        sources._finish(world.request, **{**world.arguments, "changes": changes})
    world.generations.assert_not_called()


def test_json_normalizes_timezone_but_rejects_ambiguous_or_unbounded_values():
    instant = datetime(2026, 9, 13, 10, tzinfo=UTC)
    other = instant.astimezone(timezone(timedelta(hours=2)))
    assert sources._jsonable(instant) == sources._jsonable(other)
    assert sources._jsonable({"ids": (UUID(int=1),)}) == {"ids": [str(UUID(int=1))]}
    for invalid in (instant.replace(tzinfo=None), {1: "not a JSON key"}, 1.2, object()):
        with pytest.raises(SchedulingUnavailableError):
            sources._jsonable(invalid)


@pytest.mark.parametrize("state", [None, ProgrammeReleaseState.ABSENT])
def test_no_publication_purpose_never_looks_up_release(world, monkeypatch, state):
    lookup = Mock()
    monkeypatch.setattr(sources.SchedulingRelease.objects, "filter", lookup)
    with pytest.raises(SchedulingUnavailableError):
        sources._publication(
            world.request,
            selected_release_id=world.release.id,
            current_release_id=None,
            pointer_version=None,
            state=state,
        )
    lookup.assert_not_called()


@pytest.mark.parametrize("withdrawn", [False, True])
def test_only_current_publication_or_exact_latest_withdrawal_is_selectable(
    world,
    monkeypatch,
    withdrawn,
):
    lookup = Mock()
    monkeypatch.setattr(sources.SchedulingRelease.objects, "filter", lookup)
    withdrawals = Mock()
    withdrawals.values_list.return_value.first.return_value = UUID(int=99)
    monkeypatch.setattr(
        sources.SchedulingReleaseWithdrawal.objects,
        "filter",
        Mock(return_value=withdrawals),
    )
    with pytest.raises(SchedulingVersionConflictError):
        sources._publication(
            world.request,
            selected_release_id=world.release.id,
            current_release_id=UUID(int=99),
            pointer_version=3,
            state=(
                ProgrammeReleaseState.WITHDRAWN
                if withdrawn
                else ProgrammeReleaseState.AVAILABLE
            ),
        )
    lookup.assert_not_called()


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_sender_operator_source_never_reads_output_as_recipient(
    world, monkeypatch, kind
):
    recipient = replace(world.recipient, purpose=ChangeRecipientPurpose(kind.value))
    selected = Mock(
        return_value=SimpleNamespace(
            account_id=recipient.operator_account_id, display_label="Selected operator"
        )
    )
    impact = OperatorReleaseImpact(
        kind,
        recipient.target_id,
        ProgrammeReleaseState.AVAILABLE,
        2,
        world.release.id,
        None,
        ProgrammeReleaseState.ABSENT,
        (),
        staffing_adopted=False,
        work_links=(),
        changes=(world.change,),
    )
    load = Mock(return_value=impact)
    monkeypatch.setattr(sources, "load_operator_change_recipient", selected)
    monkeypatch.setattr(sources, "load_operator_release_impact", load)
    monkeypatch.setattr(sources, "_publication", Mock(return_value=world.release))
    sender = sources._sender_sources(
        world.request,
        release_id=world.release.id,
        occurrence_id=world.occurrence_id,
        recipient=recipient,
    )
    assert selected.call_args.args[0].sender == world.request
    assert load.call_args.args[0].actor_id == world.request.actor_id
    own_request = replace(world.request, actor_id=recipient.operator_account_id)
    own = sources._self_sources(
        own_request,
        release_id=world.release.id,
        occurrence_id=world.occurrence_id,
        recipient=recipient,
    )
    assert load.call_args.args[0].actor_id == own_request.actor_id
    assert sender.snapshot_digest == own.snapshot_digest
    with pytest.raises(SchedulingUnavailableError):
        sources._self_sources(
            world.request,
            release_id=world.release.id,
            occurrence_id=world.occurrence_id,
            recipient=recipient,
        )
    assert load.call_count == 2


@pytest.fixture
def admitted(world, monkeypatch):
    preview = sources._finish(world.request, **world.arguments)
    source = Mock(return_value=preview)
    authority = Mock(return_value=object())
    audit = Mock()
    monkeypatch.setattr(queries, "_sender_sources", source)
    monkeypatch.setattr(planning_queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(planning_queries, "_lock_edition", Mock())
    monkeypatch.setattr(planning_queries, "_authorize", authority)
    monkeypatch.setattr(planning_queries, "_audit", audit)
    return SimpleNamespace(
        source=source, authority=authority, audit=audit, preview=preview
    )


def _preview(world, **overrides):
    return queries.preview_programme_change_notice(
        world.request,
        **{
            "release_id": world.release.id,
            "occurrence_id": world.occurrence_id,
            "recipient": world.recipient,
            **overrides,
        },
    )


def test_preview_uses_real_policy_repeated_sources_and_required_sender_audit(
    world, admitted
):
    assert _preview(world) == admitted.preview
    assert admitted.source.call_count == 2
    for call in admitted.source.call_args_list:
        assert call.args == (world.request,)
    for call in admitted.authority.call_args_list:
        assert call.args == (
            world.request,
            VIEW_CHANGE_NOTICES,
            frozenset({"change_notices"}),
            DEFAULT_SCHEDULING_AUTHORIZER,
        )
    assert admitted.authority.call_args.kwargs == {"lock": True}
    assert admitted.audit.call_args.args == (
        world.request,
        VIEW_CHANGE_NOTICES,
        "programme_change_notice_preview",
    )
    assert "Synthetic operator" not in repr(admitted.audit.call_args)


def test_denial_precedes_selector_validation_and_owner_discovery(world, admitted):
    admitted.authority.side_effect = SchedulingAuthorizationDeniedError
    with pytest.raises(SchedulingAuthorizationDeniedError):
        _preview(world, recipient=object())
    admitted.source.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient", object()),
        ("release_id", UUID(int=0)),
        ("occurrence_id", "bad"),
    ],
)
def test_authorized_malformed_selector_fails_before_source_read(
    world, admitted, field, value
):
    with pytest.raises(ValidationError):
        _preview(world, **{field: value})
    admitted.source.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_digest", "b" * 64),
        ("recipient_label", "Changed label"),
        ("recipient_id", UUID(int=100)),
        ("pointer_version", 3),
    ],
)
def test_moving_source_never_releases_first_observation(world, admitted, field, value):
    admitted.source.side_effect = [
        admitted.preview,
        replace(admitted.preview, **{field: value}),
    ]
    with pytest.raises(SchedulingUnavailableError):
        _preview(world)
    admitted.audit.assert_not_called()


@pytest.mark.parametrize("boundary", ["final_policy", "audit"])
def test_failed_final_policy_or_audit_never_returns_preview(world, admitted, boundary):
    if boundary == "final_policy":
        admitted.authority.side_effect = [object(), SchedulingAuthorizationDeniedError]
        error = SchedulingAuthorizationDeniedError
    else:
        admitted.audit.side_effect = RuntimeError("synthetic audit unavailable")
        error = RuntimeError
    with pytest.raises(error):
        _preview(world)
    assert admitted.source.call_count == 2


@pytest.mark.parametrize(
    "variant", ["empty", "missing_approval", "count", "duplicate", "regressed"]
)
def test_generation_snapshot_requires_complete_exact_approval_sources(
    monkeypatch, variant
):
    request = planning_queries.SchedulingReadRequest(
        *(UUID(int=n) for n in range(1, 5))
    )
    approval, second, dependency = UUID(int=10), UUID(int=11), UUID(int=12)
    rows = {
        "empty": (),
        "missing_approval": (
            (approval, dependency, 1, 2, 1, None, "disclosure", None),
        ),
        "count": ((approval, dependency, 1, 2, 2, None, "disclosure", None),),
        "duplicate": ((approval, dependency, 1, 2, 2, None, "disclosure", None),) * 2,
        "regressed": ((approval, dependency, 3, 2, 1, None, "disclosure", None),),
    }[variant]
    monkeypatch.setattr(
        sources,
        "_approval_ids",
        Mock(
            return_value=(
                (approval, second) if variant == "missing_approval" else (approval,)
            )
        ),
    )
    lookup = Mock()
    lookup.order_by.return_value.values_list.return_value = rows
    monkeypatch.setattr(
        sources.SchedulingReleaseApprovalDependency.objects,
        "filter",
        Mock(return_value=lookup),
    )
    with pytest.raises(SchedulingUnavailableError):
        sources._generation_digest(request, SimpleNamespace())


def test_shared_dependency_can_serve_several_distinct_placements(monkeypatch):
    request = planning_queries.SchedulingReadRequest(
        *(UUID(int=n) for n in range(1, 5))
    )
    approval, dependency = UUID(int=10), UUID(int=11)
    monkeypatch.setattr(sources, "_approval_ids", Mock(return_value=(approval,)))
    rows = (
        (approval, dependency, 1, 2, 2, UUID(int=12), "disclosure", None),
        (approval, dependency, 1, 2, 2, UUID(int=13), "disclosure", None),
    )
    lookup = Mock()
    lookup.order_by.return_value.values_list.return_value = rows
    monkeypatch.setattr(
        sources.SchedulingReleaseApprovalDependency.objects,
        "filter",
        Mock(return_value=lookup),
    )
    first = sources._generation_digest(request, SimpleNamespace())
    assert len(first) == 64
    lookup.order_by.return_value.values_list.return_value = tuple(
        (*row[:3], 3, *row[4:]) for row in rows
    )
    assert sources._generation_digest(request, SimpleNamespace()) != first


@pytest.mark.parametrize(
    "purpose", [ChangeRecipientPurpose.HOST, ChangeRecipientPurpose.WORK]
)
@pytest.mark.parametrize("suppressed", [False, True])
def test_host_and_work_sender_self_digests_match_without_impersonation(
    world,
    monkeypatch,
    purpose,
    suppressed,
):
    recipient = ChangeRecipientSelection(purpose, world.recipient.target_id)
    account = world.recipient.operator_account_id
    state = (
        ProgrammeReleaseState.INVALIDATED
        if suppressed
        else ProgrammeReleaseState.AVAILABLE
    )
    calls = []
    history = SimpleNamespace(
        release_id=world.release.id,
        is_active=True,
        observed_pointer_version=2,
        after_state=state,
        before_state=ProgrammeReleaseState.ABSENT,
        changes=None
        if suppressed
        else (
            SimpleNamespace(
                selection=SimpleNamespace(
                    occurrence_id=world.occurrence_id,
                    kind=ReleaseSelectionChangeKind.ADDED,
                    changed_fields=(),
                ),
                before=None,
                after=None,
                geometry_fields=(),
            ),
        ),
    )
    monkeypatch.setattr(sources, "authorize_scheduling_scope", Mock())
    monkeypatch.setattr(sources, "_publication", Mock(return_value=world.release))

    def history_read(request, **kwargs):
        calls.append(("history", request.actor_id))
        return history

    monkeypatch.setattr(sources, "load_programme_release_impact", history_read)
    if purpose is ChangeRecipientPurpose.HOST:
        host = sources.PersonalHostPurpose(
            recipient.target_id,
            UUID(int=70),
            "host",
            "confirmed",
            3,
            2,
            "Own invitation title",
            "Own private briefing",
        )
        lookup = Mock()
        lookup.values_list.return_value.first.return_value = host.item_id
        monkeypatch.setattr(
            sources.SchedulingOccurrence.objects, "filter", Mock(return_value=lookup)
        )

        def recipient_read(request, **kwargs):
            calls.append(("recipient", request.actor_id))
            assert kwargs == {"host_id": host.host_id}
            return SimpleNamespace(
                relationship=host,
                account_id=account,
                display_label="Selected host",
                item_id=host.item_id,
            )

        monkeypatch.setattr(sources, "load_host_change_recipient", recipient_read)
        own_change = sources.PersonalHostPresenceChange(
            host.host_id,
            host.version,
            host.invitation_sequence,
            world.occurrence_id,
            ReleaseSelectionChangeKind.ADDED,
            None,
            None,
            (),
        )
        manifest = SimpleNamespace(state=state, pointer_version=2, is_active=True)
        monkeypatch.setattr(sources, "_manifest", Mock(return_value=manifest))
        monkeypatch.setattr(sources, "_presences", Mock(return_value=()))
        monkeypatch.setattr(
            sources, "_compare_host_presence", Mock(return_value=(own_change,))
        )
        personal_owner = Mock(return_value=(host,))
        personal = Mock(
            return_value=SimpleNamespace(
                state=state,
                pointer_version=2,
                release_id=world.release.id,
                changes=None if suppressed else (own_change,),
            )
        )
        monkeypatch.setattr(sources, "load_personal_host_purposes", personal_owner)
        monkeypatch.setattr(sources, "load_personal_host_release_impact", personal)
    else:
        work = PersonalProgrammeWorkLink(
            recipient.target_id,
            3,
            "confirmed",
            UUID(int=71),
            4,
            world.occurrence_id,
            UUID(int=72),
            5,
            current=False,
        )

        def recipient_read(request):
            calls.append(("recipient", request.actor_id))
            assert request.commitment_id == work.commitment_id
            return SimpleNamespace(
                work=work, account_id=account, display_label="Volunteer"
            )

        monkeypatch.setattr(sources, "load_work_change_recipient", recipient_read)
        own_change = sources.PersonalWorkOccurrenceChange(
            work,
            ReleaseSelectionChangeKind.ADDED,
            None,
            None,
            (),
        )
        personal_owner = Mock(return_value=(work,))
        personal = Mock(
            return_value=SimpleNamespace(
                state=state,
                pointer_version=2,
                release_id=world.release.id,
                changes=None if suppressed else (own_change,),
            )
        )
        monkeypatch.setattr(
            sources, "load_personal_programme_work_links", personal_owner
        )
        monkeypatch.setattr(sources, "load_personal_work_release_impact", personal)
    sender = sources._sender_sources(
        world.request,
        release_id=world.release.id,
        occurrence_id=world.occurrence_id,
        recipient=recipient,
    )
    personal_owner.assert_not_called()
    personal.assert_not_called()
    assert calls == [
        ("recipient", world.request.actor_id),
        ("history", world.request.actor_id),
    ]
    own_request = replace(world.request, actor_id=account)
    own = sources._self_sources(
        own_request,
        release_id=world.release.id,
        occurrence_id=world.occurrence_id,
        recipient=recipient,
    )
    assert own.snapshot_digest == sender.snapshot_digest
    assert personal_owner.call_args.kwargs["actor_id"] == account
    assert personal.call_args.kwargs["actor_id"] == account
    assert "Own private briefing" not in repr(sender)
