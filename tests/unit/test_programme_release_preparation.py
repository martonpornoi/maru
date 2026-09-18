"""Real-signature release composition with mocks, not native independence proof."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.authorization import programme_role_scope_choices
from maru.authorization.catalog import ScopeLevel
from maru.scheduling import (
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
from maru.scheduling.release_artifacts import ReleaseArtifactSelection
from maru.scheduling.release_eligibility import (
    ReleaseCheck,
    ReleaseCheckEvidence,
    ReleaseCheckState,
    evaluate_release_eligibility,
)
from maru.scheduling.release_preflight import SchedulingReleasePreflight
from maru.scheduling.release_queries import (
    ProgrammeReleaseManifest,
    ProgrammeReleaseState,
)
from maru.venues.bindings import edition_space_binding_id
from tests.rehearsals import programme_release_preparation as preparation
from tests.unit.test_programme_release_scenario import _result, _sources
from tests.unit.test_programme_review_scenario import _authentication


def _stub(monkeypatch, module, name, **options):
    result = create_autospec(getattr(module, name), **options)
    monkeypatch.setattr(module, name, result)
    return result


def _evidence(planning, *, digest="0123456789abcdef" * 4):
    checks = tuple(
        ReleaseCheckEvidence(digest, check, ReleaseCheckState.SATISFIED)
        for check in ReleaseCheck
    )
    return SchedulingReleasePreflight(
        planning.candidate_revision_id,
        digest,
        checks,
        (),
        evaluate_release_eligibility(snapshot_digest=digest, checks=checks),
    )


@pytest.mark.parametrize(
    "fault", [None, "missing", "blocked", "inapplicable", "digest", "findings"]
)
def test_preflight_recollects_all_ten_current_owners_without_automatic_acknowledgement(
    monkeypatch, fault
):
    _authentication(monkeypatch)
    setup, _, _, _, planning, _, _ = _sources()
    evidence = _evidence(planning)
    if fault == "missing":
        evidence = replace(evidence, checks=evidence.checks[:-1])
    elif fault in {"blocked", "inapplicable"}:
        state = (
            ReleaseCheckState.BLOCKED
            if fault == "blocked"
            else ReleaseCheckState.NOT_APPLICABLE
        )
        evidence = replace(
            evidence,
            checks=(replace(evidence.checks[0], state=state), *evidence.checks[1:]),
        )
    elif fault == "digest":
        evidence = replace(evidence, snapshot_digest="b" * 64)
    elif fault == "findings":
        evidence = replace(
            evidence, findings=(SimpleNamespace(code="unexpected_warning"),)
        )
    load = _stub(
        monkeypatch, release_preflight, "load_release_preflight", return_value=evidence
    )
    if fault:
        with pytest.raises(
            preparation.ProgrammeReleasePreparationError,
            match="complete_sources_required",
        ):
            preparation._preflight(setup, planning.planner, planning)
    else:
        assert preparation._preflight(setup, planning.planner, planning) == evidence
    assert load.call_args.args[0].actor_id == planning.planner.account_id
    assert load.call_args.kwargs == {
        "candidate_id": planning.candidate_id,
        "candidate_revision_id": planning.candidate_revision_id,
        "expected_candidate_version": planning.candidate_version,
    }


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "prior",
        "reviewer",
        "self_approve",
        "approval_retry",
        "implicit_publish",
        "self_publish",
        "stale_publish",
        "publication_retry",
        "manifest",
    ],
)
def test_original_independent_people_approve_publish_and_retry_exact_intent(
    monkeypatch, fault
):
    _authentication(monkeypatch)
    setup, _, _, items, planning, _, _ = _sources()
    result = _result(setup, planning)
    absent = ProgrammeReleaseManifest(
        ProgrammeReleaseState.ABSENT, 0, None, is_active=False, selections=()
    )
    selections = tuple(
        ReleaseArtifactSelection(occurrence, placement, item.public_rendition_id)
        for occurrence, placement, item in zip(
            planning.occurrence_ids,
            planning.placement_ids,
            (items.ceremony, items.accepted, items.accepted),
            strict=True,
        )
    )
    available = ProgrammeReleaseManifest(
        ProgrammeReleaseState.AVAILABLE,
        1,
        result.release_id,
        is_active=True,
        selections=selections,
    )
    states = [absent, absent, absent, absent, available]
    if fault == "prior":
        states[0] = available
    elif fault == "implicit_publish":
        states[2] = available
    elif fault == "manifest":
        states[-1] = replace(available, selections=selections[:-1])
    _stub(
        monkeypatch,
        release_queries,
        "load_programme_release_manifest",
        side_effect=states,
    )
    evidence = _evidence(planning)
    _stub(
        monkeypatch,
        release_preflight,
        "load_release_preflight",
        side_effect=[
            evidence,
            _evidence(planning, digest="b" * 64) if fault == "reviewer" else evidence,
        ],
    )
    approved = SchedulingCommandResult(uuid4(), result.approval_id, 1, 10)
    published = SchedulingCommandResult(uuid4(), result.release_id, 1, 11)
    approve = _stub(
        monkeypatch,
        release_review_commands,
        "approve_programme_release",
        side_effect=[
            approved
            if fault == "self_approve"
            else SchedulingAuthorizationDeniedError(),
            approved,
            replace(
                approved,
                replayed=True,
                object_id=uuid4() if fault == "approval_retry" else approved.object_id,
            ),
        ],
    )
    publish = _stub(
        monkeypatch,
        release_publication_commands,
        "publish_programme_release",
        side_effect=[
            published
            if fault == "self_publish"
            else SchedulingAuthorizationDeniedError(),
            published if fault == "stale_publish" else SchedulingVersionConflictError(),
            published,
            replace(
                published,
                replayed=True,
                object_id=uuid4()
                if fault == "publication_retry"
                else published.object_id,
            ),
        ],
    )
    if fault:
        with pytest.raises(preparation.ProgrammeReleasePreparationError):
            preparation.prepare_first_release(setup, items, planning, result.reviewer)
    else:
        assert preparation.prepare_first_release(
            setup, items, planning, result.reviewer
        ) == (
            result.approval_id,
            result.release_id,
            1,
            result.source_digest,
        )
        assert [call.args[0].actor_id for call in approve.call_args_list] == [
            planning.planner.account_id,
            result.reviewer.account_id,
            result.reviewer.account_id,
        ]
        assert approve.call_args_list[1] == approve.call_args_list[2]
        assert [call.args[0].actor_id for call in publish.call_args_list] == [
            result.reviewer.account_id,
            planning.planner.account_id,
            planning.planner.account_id,
            planning.planner.account_id,
        ]
        assert publish.call_args_list[2] == publish.call_args_list[3]
        assert publish.call_args_list[1].kwargs["intent"].expected_release_version == 1
        assert publish.call_args_list[2].kwargs["intent"].expected_release_version == 0
        assert publish.call_args.kwargs["intent"].approval_id == result.approval_id
        assert approve.call_args.kwargs["intent"].acknowledgement_ids == ()
        assert set(approve.call_args.kwargs) == {"intent"}
        assert set(publish.call_args.kwargs) == {"intent"}


@pytest.mark.parametrize("bad_scope", [False, True])
def test_existing_roles_keep_both_independence_checks_real_and_room_sources_exact(
    monkeypatch, bad_scope
):
    _authentication(monkeypatch)
    setup, _, _, _, planning, _, _ = _sources()
    result = _result(setup, planning)
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
        return_value=SimpleNamespace(choices=tuple(scopes)),
    )
    grants = Mock(side_effect=list(result.role_assignment_ids))
    monkeypatch.setattr(preparation, "approve_synthetic_role", grants)
    if bad_scope:
        with pytest.raises(
            preparation.ProgrammeReleasePreparationError, match="room_scope_unavailable"
        ):
            preparation.approve_release_roles(setup, planning, result.reviewer)
    else:
        assert (
            preparation.approve_release_roles(setup, planning, result.reviewer)
            == result.role_assignment_ids
        )
        assert len(grants.call_args_list) == 13
        for call in grants.call_args_list:
            assert call.kwargs["people"] == setup.controllers
            assert call.kwargs["level"] in {ScopeLevel.EDITION, ScopeLevel.RESOURCE}
        for call, room in zip(
            grants.call_args_list[-2:], planning.room_ids, strict=True
        ):
            assert call.kwargs["code"] == "room-dependencies"
            assert call.kwargs["resource_binding_id"] == edition_space_binding_id(room)
        for person in (planning.planner, result.reviewer):
            assert {"release-approval", "publisher"} <= {
                call.kwargs["code"]
                for call in grants.call_args_list
                if call.kwargs["recipient"] == person
            }
