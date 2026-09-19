"""Actual notice signatures, distinct purposes and independent retained facts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.authorization import programme_role_scope_choices
from maru.authorization.catalog import ScopeLevel
from maru.scheduling import change_notice_commands as commands
from maru.scheduling import change_notice_queries as queries
from maru.scheduling.change_catalogs import (
    ChangeNoticeReview,
    ChangeNoticeSourceState,
    ChangeRecipientPurpose,
)
from maru.scheduling.change_inputs import ChangeRecipientSelection
from maru.scheduling.change_lifecycle import ChangeNoticeState
from maru.scheduling.change_notice_queries import (
    PersonalProgrammeChangeNotice,
    ProgrammeChangeNotice,
)
from maru.scheduling.change_notice_sources import ProgrammeChangeNoticePreview
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingLifecycleConflictError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.venues.bindings import edition_space_binding_id
from tests.rehearsals import programme_notice_preparation as preparation
from tests.unit.test_programme_change_scenario import _sources
from tests.unit.test_programme_release_preparation import _stub
from tests.unit.test_programme_review_scenario import _authentication


@pytest.mark.parametrize("bad_scope", [False, True])
def test_notice_roles_are_existing_recipes_and_exact_room_not_catch_all(
    monkeypatch, bad_scope
):
    _authentication(monkeypatch)
    setup, _, _, _, planning, physical, _, release = _sources()
    scopes = [
        SimpleNamespace(
            scope=SimpleNamespace(
                level=ScopeLevel.RESOURCE,
                department_id=setup.department_id,
                resource_kind="venue.edition_space",
                resource_binding_id=edition_space_binding_id(room),
            )
        )
        for room in planning.room_ids
    ]
    if bad_scope:
        scopes[0].scope.department_id = uuid4()
    _stub(
        monkeypatch,
        programme_role_scope_choices,
        "load_programme_role_scope_choices",
        return_value=SimpleNamespace(choices=scopes),
    )
    grant = Mock(side_effect=lambda *_a, **_kw: uuid4())
    monkeypatch.setattr(preparation, "approve_synthetic_role", grant)
    if bad_scope:
        with pytest.raises(RuntimeError, match="room_scope_unavailable"):
            preparation.approve_notice_roles(setup, planning, physical, release)
    else:
        assert (
            len(preparation.approve_notice_roles(setup, planning, physical, release))
            == 9
        )
        room = grant.call_args.kwargs
        assert room["recipient"] == physical.reviewer
        assert room["code"] == "run-sheet"
        assert room["level"] == ScopeLevel.RESOURCE
        assert room["resource_binding_id"] == edition_space_binding_id(
            planning.room_ids[0]
        )
    assert all(
        call.kwargs["people"] == setup.controllers for call in grant.call_args_list
    )


@pytest.mark.parametrize(
    "purpose",
    [
        ChangeRecipientPurpose.HOST,
        ChangeRecipientPurpose.WORK,
        ChangeRecipientPurpose.ROOM,
    ],
)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "unsuppressed",
        "preparation_retry",
        "unreviewed",
        "self_review",
        "handoff_early",
        "implicit_handoff",
        "wrong_ack",
        "implicit_ack",
        "stale_ack",
        "final_recipient",
    ],
)
def test_notice_keeps_review_handoff_and_exact_recipient_ack_distinct(
    monkeypatch, purpose, fault
):
    _authentication(monkeypatch)
    setup, _, _, items, planning, physical, staffing, release = _sources()
    person = {
        ChangeRecipientPurpose.HOST: items.ceremony_host,
        ChangeRecipientPurpose.WORK: staffing.volunteer,
        ChangeRecipientPurpose.ROOM: physical.reviewer,
    }[purpose]
    selection = ChangeRecipientSelection(
        purpose,
        uuid4(),
        person.account_id if purpose == ChangeRecipientPurpose.ROOM else None,
    )
    publication, notice = uuid4(), uuid4()
    preview = ProgrammeChangeNoticePreview(
        publication,
        planning.occurrence_ids[0],
        2,
        ChangeNoticeSourceState.COMPARISON_SUPPRESSED,
        person.account_id,
        "Synthetic person",
        selection,
        "a" * 64,
        "b" * 64,
        None,
    )
    _stub(
        monkeypatch,
        queries,
        "preview_programme_change_notice",
        return_value=replace(preview, source_state=ChangeNoticeSourceState.AVAILABLE)
        if fault == "unsuppressed"
        else preview,
    )
    prepared = SchedulingCommandResult(uuid4(), notice, 1, 10)
    prepare = _stub(
        monkeypatch,
        commands,
        "prepare_programme_change_notice",
        side_effect=[
            prepared,
            replace(
                prepared,
                replayed=True,
                object_id=uuid4() if fault == "preparation_retry" else notice,
            ),
        ],
    )
    approved = replace(prepared, version=2)
    review = _stub(
        monkeypatch,
        commands,
        "review_programme_change_notice",
        side_effect=[
            approved if fault == "self_review" else SchedulingLifecycleConflictError(),
            approved,
            replace(approved, replayed=True),
        ],
    )
    handed = replace(prepared, version=3)
    handoff = _stub(
        monkeypatch,
        commands,
        "handoff_programme_change_notice",
        side_effect=[
            handed if fault == "handoff_early" else SchedulingLifecycleConflictError(),
            handed,
            replace(handed, replayed=True),
        ],
    )
    acknowledged = replace(prepared, version=4)
    ack = _stub(
        monkeypatch,
        commands,
        "acknowledge_programme_change_notice",
        side_effect=[
            acknowledged if fault == "wrong_ack" else SchedulingUnavailableError(),
            acknowledged if fault == "stale_ack" else SchedulingVersionConflictError(),
            acknowledged,
            replace(acknowledged, replayed=True),
        ],
    )
    visible = PersonalProgrammeChangeNotice(
        notice, preview, 2, handed_off=False, acknowledged=False
    )
    _stub(
        monkeypatch,
        queries,
        "load_personal_programme_change_notice",
        side_effect=[
            visible if fault == "unreviewed" else SchedulingUnavailableError(),
            replace(visible, handed_off=fault == "implicit_handoff"),
            replace(
                visible,
                version=3,
                handed_off=True,
                acknowledged=fault == "implicit_ack",
            ),
            replace(visible, version=4, handed_off=True, acknowledged=True),
        ],
    )
    detail = ProgrammeChangeNotice(
        notice,
        preview,
        ChangeNoticeState(
            planning.planner.account_id,
            person.account_id,
            4,
            ChangeNoticeReview.APPROVED,
            release.reviewer.account_id,
            planning.planner.account_id,
            uuid4() if fault == "final_recipient" else person.account_id,
        ),
        "Synthetic reason",
    )
    _stub(monkeypatch, queries, "load_programme_change_notice", return_value=detail)
    if fault:
        with pytest.raises(RuntimeError):
            preparation.prepare_review_handoff_ack(
                setup, planning, release.reviewer, person, selection, publication
            )
    else:
        assert (
            preparation.prepare_review_handoff_ack(
                setup, planning, release.reviewer, person, selection, publication
            )
            == notice
        )
        assert prepare.call_args.args[0].actor_id == planning.planner.account_id
        assert review.call_args.args[0].actor_id == release.reviewer.account_id
        assert handoff.call_args.args[0].actor_id == planning.planner.account_id
        assert ack.call_args.args[0].actor_id == person.account_id
        assert set(ack.call_args.kwargs) == {"idempotency_key"}
