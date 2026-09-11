"""Candidate-source admission, completeness and disclosure remain fail closed."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.scheduling import release_candidate_queries as sources
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import SchedulingReadRequest


@pytest.fixture
def source_world(monkeypatch):
    request = SchedulingReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    candidate_id, revision_id = uuid4(), uuid4()
    scope = SimpleNamespace(accepts_writes=True, edition_version=7)
    authorize = Mock(return_value=scope)
    monkeypatch.setattr(sources, "authorize_scheduling_scope", authorize)
    monkeypatch.setattr(
        sources,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="synthetic", version=1),
    )
    monkeypatch.setattr(sources, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(sources.transaction, "atomic", nullcontext)
    locks = Mock()
    monkeypatch.setattr(sources, "lock_programme_staffing_scope", locks)
    revision = SimpleNamespace(
        id=revision_id, sequence=2, placement_count=1, manifest_digest="a" * 64
    )
    manager = Mock()
    manager.filter.return_value.only.return_value.first.return_value = revision
    monkeypatch.setattr(sources.SchedulingCandidateRevision, "objects", manager)
    facts = Mock(return_value=(object(),))
    monkeypatch.setattr(sources, "_placement_facts", facts)
    audit = Mock()
    monkeypatch.setattr(sources, "_audit", audit)
    return SimpleNamespace(
        request=request,
        arguments={
            "candidate_id": candidate_id,
            "candidate_revision_id": revision_id,
            "expected_candidate_version": 2,
        },
        scope=scope,
        authorize=authorize,
        locks=locks,
        revision=revision,
        manager=manager,
        facts=facts,
        audit=audit,
    )


def test_source_is_exact_minimized_and_audited(source_world):
    world = source_world
    result = sources.load_release_candidate_source(world.request, **world.arguments)
    assert result.revision_id == world.revision.id
    assert result.candidate_version == 2
    assert result.edition_version == 7
    assert result.placements == world.facts.return_value
    assert not hasattr(result, "label")
    assert not hasattr(result, "reason")
    world.locks.assert_called_once_with(
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
    )
    selected = world.manager.filter.call_args.kwargs
    assert selected["organization_id"] == world.request.organization_id
    assert selected["edition_id"] == world.request.edition_id
    assert selected["candidate__organization_id"] == world.request.organization_id
    assert selected["candidate__edition_id"] == world.request.edition_id
    assert selected["id"] == world.arguments["candidate_revision_id"]
    assert selected["candidate_id"] == world.arguments["candidate_id"]
    assert selected["candidate__aggregate_version"] == selected["sequence"] == 2
    assert selected["candidate__lifecycle"] == "draft"
    assert world.authorize.call_count == 3
    world.audit.assert_called_once()


@pytest.mark.parametrize("absent_profile", [False, True])
def test_unpinned_source_is_denied_before_selection(
    source_world, monkeypatch, absent_profile
):
    world = source_world
    if absent_profile:
        monkeypatch.setattr(
            sources, "edition_adoption_profile_reference", lambda **_kwargs: None
        )
    else:
        monkeypatch.setattr(sources, "profile_allows_adapter", lambda *_args: False)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        sources.load_release_candidate_source(
            world.request, **(world.arguments | {"candidate_id": "private-invalid"})
        )
    world.manager.filter.assert_not_called()
    world.locks.assert_not_called()


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_authority_loss_never_releases_source(source_world, phase):
    world = source_world
    world.authorize.side_effect = [world.scope] * phase + [
        SchedulingAuthorizationDeniedError()
    ]
    with pytest.raises(SchedulingAuthorizationDeniedError):
        sources.load_release_candidate_source(world.request, **world.arguments)
    world.audit.assert_not_called()
    if phase < 2:
        world.manager.filter.assert_not_called()


@pytest.mark.parametrize("problem", ["lifecycle", "missing", "empty", "partial"])
def test_incomplete_candidate_never_returns_a_success(source_world, problem):
    world = source_world
    if problem == "lifecycle":
        world.scope.accepts_writes = False
    elif problem == "missing":
        world.manager.filter.return_value.only.return_value.first.return_value = None
    elif problem == "empty":
        world.revision.placement_count = 0
    else:
        world.facts.return_value = ()
    with pytest.raises(SchedulingUnavailableError):
        sources.load_release_candidate_source(world.request, **world.arguments)
    world.audit.assert_not_called()


def test_manifest_integrity_failure_and_audit_failure_propagate(source_world):
    world = source_world
    world.facts.side_effect = SchedulingUnavailableError()
    with pytest.raises(SchedulingUnavailableError):
        sources.load_release_candidate_source(world.request, **world.arguments)
    world.audit.assert_not_called()
    world.facts.side_effect = None
    world.audit.side_effect = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        sources.load_release_candidate_source(world.request, **world.arguments)
