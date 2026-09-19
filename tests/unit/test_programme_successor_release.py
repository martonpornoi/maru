"""Independent replacement publication and suppressed predecessor disclosure."""

from dataclasses import replace
from uuid import uuid4

import pytest

from maru.scheduling import (
    operator_output_queries,
    release_impact_queries,
    release_preflight,
    release_publication_commands,
    release_queries,
    release_review_commands,
)
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingVersionConflictError,
)
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.release_impact_queries import ProgrammeReleaseImpact
from maru.scheduling.release_queries import (
    ProgrammeReleaseManifest,
    ProgrammeReleaseState,
)
from tests.rehearsals import programme_successor_release as preparation
from tests.unit.test_programme_change_scenario import _result, _sources
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import sheet as sheet  # noqa: PLC0414
from tests.unit.test_programme_release_preparation import _evidence, _stub
from tests.unit.test_programme_review_scenario import _authentication


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "old_safe",
        "old_digest",
        "self_review",
        "implicit_publish",
        "self_publish",
        "pointer",
        "retry",
        "comparison",
        "predecessor",
    ],
)
def test_replacement_requires_fresh_independent_evidence_and_retains_suppression(
    monkeypatch, fault
):
    _authentication(monkeypatch)
    sources = _sources()
    setup, _, _, _, planning, _, _, release = sources
    result = _result(sources)
    before = ProgrammeReleaseManifest(
        ProgrammeReleaseState.INVALIDATED,
        1,
        release.release_id,
        is_active=True,
        selections=(),
    )
    after = ProgrammeReleaseManifest(
        ProgrammeReleaseState.AVAILABLE,
        2,
        result.release_id,
        is_active=True,
        selections=(),
    )
    _stub(
        monkeypatch,
        release_queries,
        "load_programme_release_manifest",
        side_effect=[
            after if fault == "old_safe" else before,
            after if fault == "implicit_publish" else before,
            before,
            after,
        ],
    )
    evidence = _evidence(
        planning,
        digest=release.source_digest if fault == "old_digest" else result.source_digest,
    )
    _stub(
        monkeypatch, release_preflight, "load_release_preflight", return_value=evidence
    )
    approved = SchedulingCommandResult(uuid4(), result.approval_id, 1, 20)
    approve = _stub(
        monkeypatch,
        release_review_commands,
        "approve_programme_release",
        side_effect=[
            approved
            if fault == "self_review"
            else SchedulingAuthorizationDeniedError(),
            approved,
            replace(approved, replayed=True),
        ],
    )
    published = SchedulingCommandResult(uuid4(), result.release_id, 2, 21)
    publish = _stub(
        monkeypatch,
        release_publication_commands,
        "publish_programme_release",
        side_effect=[
            published
            if fault == "self_publish"
            else SchedulingAuthorizationDeniedError(),
            published if fault == "pointer" else SchedulingVersionConflictError(),
            published,
            replace(
                published,
                replayed=True,
                object_id=uuid4() if fault == "retry" else published.object_id,
            ),
        ],
    )
    impact = ProgrammeReleaseImpact(
        result.release_id,
        uuid4() if fault == "predecessor" else release.release_id,
        2,
        2,
        is_active=True,
        before_state=ProgrammeReleaseState.INVALIDATED,
        after_state=ProgrammeReleaseState.AVAILABLE,
        changes=() if fault == "comparison" else None,
    )
    _stub(
        monkeypatch,
        release_impact_queries,
        "load_programme_release_impact",
        return_value=impact,
    )
    if fault:
        with pytest.raises(RuntimeError):
            preparation.republish_after_work_change(setup, planning, release)
    else:
        assert preparation.republish_after_work_change(setup, planning, release) == (
            result.approval_id,
            result.release_id,
            result.source_digest,
        )
        assert approve.call_args.args[0].actor_id == release.reviewer.account_id
        assert publish.call_args.args[0].actor_id == planning.planner.account_id
        intent = publish.call_args.kwargs["intent"]
        assert intent.expected_active_release_id == release.release_id
        assert intent.expected_release_version == 1
        assert intent.source_snapshot_digest == result.source_digest


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing_history",
        "history_current",
        "history_locked",
        "unlocked",
        "source",
    ],
)
def test_operator_output_keeps_cancelled_history_distinct_from_current_work(
    monkeypatch, full_sheet, fault
):
    _authentication(monkeypatch)
    sources = _sources()
    setup, _, _, _, planning, _, staffing, _ = sources
    change = _result(sources)

    def read(request, *, layers):
        expected = (
            change.work,
            *staffing.work[1 : 2 if request.kind == OperatorScopeKind.ROOM else 3],
        )
        current = tuple(
            replace(
                full_sheet.staffing.links[0],
                demand_id=row.demand_id,
                demand_version=row.demand_version,
                current=True,
            )
            for row in expected
        )
        prior = replace(
            current[0],
            demand_id=change.predecessor_demand_id,
            current=fault == "history_current",
        )
        links = current if fault == "missing_history" else (*current, prior)
        demands = tuple(
            replace(
                full_sheet.staffing.demands[0],
                demand_id=row.demand_id,
                state="open" if fault == "unlocked" else "locked",
            )
            for row in current
        )
        demands += (
            replace(
                demands[0],
                demand_id=prior.demand_id,
                state="locked" if fault == "history_locked" else "cancelled",
            ),
        )
        return replace(
            full_sheet,
            kind=request.kind,
            target_id=request.target_id,
            layers=layers,
            reference=replace(
                full_sheet.reference,
                release_id=uuid4() if fault == "source" else change.release_id,
                pointer_version=2,
            ),
            entries=tuple(replace(row, delivery=None) for row in full_sheet.entries),
            staffing=replace(full_sheet.staffing, links=links, demands=demands),
        )

    query = _stub(
        monkeypatch,
        operator_output_queries,
        "load_operator_run_sheet",
        side_effect=read,
    )
    if fault:
        with pytest.raises(RuntimeError):
            preparation.verify_successor_operator_output(
                setup, planning, staffing, change
            )
    else:
        preparation.verify_successor_operator_output(setup, planning, staffing, change)
        assert [
            (call.args[0].kind, call.args[0].target_id) for call in query.call_args_list
        ] == [
            (OperatorScopeKind.EDITION, setup.edition_id),
            (OperatorScopeKind.DEPARTMENT, setup.department_id),
            (OperatorScopeKind.ROOM, planning.room_ids[0]),
        ]
