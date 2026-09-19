"""Typed owner-command composition and private codecs, not PostgreSQL evidence."""

import io
from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from maru.scheduling import release_publication_commands, release_review_commands
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingVersionConflictError,
)
from maru.scheduling.release_queries import (
    ProgrammeReleaseManifest,
    ProgrammeReleaseState,
)
from tests.rehearsals import programme_continuity_transition as transition
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_change_scenario import SOURCE_KEYS
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_change_scenario import _document, _result, _sources
from tests.unit.test_programme_release_preparation import _evidence, _stub
from tests.unit.test_programme_review_scenario import _authentication


@pytest.mark.parametrize("operation", ["withdraw", "republish"])
@pytest.mark.parametrize("fault", [None, "before", "stale", "retry", "pointer", "work"])
def test_owner_transitions_keep_independent_approval_and_retained_work(
    monkeypatch, operation, fault
):
    _authentication(monkeypatch)
    sources = _sources()
    _, _, _, _, planning, _, staffing, release = sources
    changed = _result(sources)
    monkeypatch.setattr(transition, "require_programme_runtime_environment", Mock())
    build = _stub(monkeypatch, programme_runtime, "build_candidate_application")
    withdrawn = ProgrammeReleaseManifest(
        ProgrammeReleaseState.WITHDRAWN, 3, None, is_active=False, selections=()
    )
    before = (
        ProgrammeReleaseManifest(
            ProgrammeReleaseState.AVAILABLE,
            2,
            changed.release_id,
            is_active=True,
            selections=(),
        )
        if operation == "withdraw"
        else withdrawn
    )
    result = SchedulingCommandResult(
        uuid4(), uuid4(), 3 if operation == "withdraw" else 4, 1
    )
    after = (
        withdrawn
        if operation == "withdraw"
        else ProgrammeReleaseManifest(
            ProgrammeReleaseState.AVAILABLE,
            4,
            result.object_id,
            is_active=True,
            selections=("one", "two", "three"),
        )
    )
    observations = (
        [before, before, after]
        if operation == "withdraw"
        else [before, before, before, after]
    )
    if fault == "before":
        observations[0] = replace(before, pointer_version=99)
    if fault == "pointer":
        observations[-1] = replace(after, pointer_version=99)
    monkeypatch.setattr(transition, "_manifest", Mock(side_effect=observations))
    monkeypatch.setattr(
        transition, "_preflight", Mock(return_value=_evidence(planning))
    )
    retained = dict.fromkeys(
        (
            changed.work.commitment_id,
            changed.predecessor_commitment_id,
            *(row.commitment_id for row in staffing.work[1:]),
        ),
        "retained",
    )
    monkeypatch.setattr(
        transition,
        "_own_work",
        Mock(side_effect=[retained, {} if fault == "work" else retained]),
    )
    approval = SchedulingCommandResult(uuid4(), uuid4(), 1, 2)
    approve = _stub(
        monkeypatch,
        release_review_commands,
        "approve_programme_release",
        side_effect=[approval, replace(approval, replayed=True)],
    )
    command = _stub(
        monkeypatch,
        release_publication_commands,
        "withdraw_programme_release"
        if operation == "withdraw"
        else "publish_programme_release",
        side_effect=[
            result if fault == "stale" else SchedulingVersionConflictError(),
            result,
            replace(result, object_id=uuid4())
            if fault == "retry"
            else replace(result, replayed=True),
        ],
    )
    document = {
        "sources": dict(
            zip(
                SOURCE_KEYS,
                map(_document, sources),
                strict=True,
            )
        ),
        "change": _document(changed),
        "operation": operation,
    }
    if fault:
        with pytest.raises(RuntimeError):
            transition.prepare_continuity_transition(document)
    else:
        actual = transition.prepare_continuity_transition(document)
        assert actual.object_id == result.object_id
        assert actual.pointer_version == result.version
        assert command.call_args_list[1] == command.call_args_list[2]
        assert command.call_args.args[0].actor_id == planning.planner.account_id
        if operation == "withdraw":
            approve.assert_not_called()
            assert actual.approval_id is None
        else:
            assert approve.call_args_list[0] == approve.call_args_list[1]
            assert approve.call_args.args[0].actor_id == release.reviewer.account_id
            assert actual.approval_id == approval.object_id
            assert actual.approval_id not in {changed.approval_id, release.approval_id}
            assert command.call_args.kwargs["intent"].expected_release_version == 3
    build.assert_called_once_with()


@pytest.mark.parametrize("operation", ["withdraw", "republish"])
@pytest.mark.parametrize(
    "fault",
    [None, "scope", "version", "boolean", "operation", "zero", "approval", "extra"],
)
def test_private_result_is_closed_and_scope_pinned(operation, fault):
    setup = _sources()[0]
    result = transition.ProgrammeContinuityTransition(
        operation,
        setup.organization_id,
        setup.edition_id,
        uuid4(),
        None if operation == "withdraw" else uuid4(),
        3 if operation == "withdraw" else 4,
    )
    document = _document(result)
    if fault == "scope":
        document["edition_id"] = str(uuid4())
    elif fault == "version":
        document["pointer_version"] += 1
    elif fault == "boolean":
        document["pointer_version"] = True
    elif fault == "operation":
        document["operation"] = "activate"
    elif fault == "zero":
        document["object_id"] = str(UUID(int=0))
    elif fault == "approval":
        document["approval_id"] = str(uuid4()) if operation == "withdraw" else None
    elif fault == "extra":
        document["secret"] = "not accepted"
    if fault:
        with pytest.raises(ValueError, match="result_invalid"):
            transition.transition_from_document(
                document, setup=setup, operation=operation
            )
    else:
        assert (
            transition.transition_from_document(
                document, setup=setup, operation=operation
            )
            == result
        )


def test_transition_guard_precedes_input_and_bootstrap(monkeypatch):
    monkeypatch.setattr(
        transition,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    build = _stub(monkeypatch, programme_runtime, "build_candidate_application")
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        transition.prepare_continuity_transition(None)
    build.assert_not_called()


@pytest.mark.parametrize("raw", [b"{}", b"x" * 65_537], ids=["invalid", "oversize"])
def test_private_main_refuses_invalid_or_oversize_input_without_output(
    monkeypatch, raw
):
    monkeypatch.setattr(transition, "require_programme_runtime_environment", Mock())
    monkeypatch.setattr(transition.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    output = io.StringIO()
    monkeypatch.setattr(transition.sys, "stdout", output)
    assert transition._main() == 2
    assert output.getvalue() == ""
