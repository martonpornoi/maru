"""Exact source selection cannot infer an alternative or substitute owner authority."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.programme import staffing_sources as sources
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.staffing_inputs import ProgrammeStaffingSource
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from tests.unit.test_programme_staffing_inputs import expectation


@pytest.fixture
def selection(monkeypatch):
    request = ProgrammeStaffingReadRequest(uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    source = ProgrammeStaffingSource(
        uuid4(), uuid4(), 1, uuid4(), 1, uuid4(), uuid4(), uuid4()
    )
    terms = expectation().normalized()
    requirement = SimpleNamespace(
        requirement_id=source.requirement_id,
        revision_id=source.requirement_revision_id,
        version=1,
        occurrence_id=source.occurrence_id,
        occurrence_version=1,
        lifecycle="active",
        item_version=3,
        expectation=terms,
    )
    occurrence = SimpleNamespace(
        id=source.occurrence_id,
        revision_id=uuid4(),
        item_id=request.item_id,
        lifecycle="active",
        version=1,
    )
    candidate = SimpleNamespace(
        id=source.candidate_id,
        revision_id=source.candidate_revision_id,
        version=2,
        lifecycle="draft",
    )
    day = SimpleNamespace(id=uuid4(), revision_id=uuid4(), lifecycle="active")
    placement = SimpleNamespace(
        id=source.placement_id,
        occurrence_id=source.occurrence_id,
        occurrence_revision_id=occurrence.revision_id,
        day_id=day.id,
        day_revision_id=day.revision_id,
    )
    planning = SimpleNamespace(
        candidates=(candidate,),
        occurrences=(occurrence,),
        placements=(placement,),
        days=(day,),
        selected_candidate_id=source.candidate_id,
        accepts_writes=True,
        edition_version=1,
    )
    calls = []
    overview = SimpleNamespace(
        item_id=request.item_id, requirements=(requirement,), item_lifecycle="active"
    )

    def programme(*args, **kwargs):
        calls.append(("programme", args, kwargs))
        return overview

    def scheduling(*args, **kwargs):
        calls.append(("scheduling", args, kwargs))
        return planning

    def final(**kwargs):
        calls.append(("final", (), kwargs))

    monkeypatch.setattr(sources.transaction, "atomic", nullcontext)
    monkeypatch.setattr(sources, "load_programme_staffing_requirements", programme)
    monkeypatch.setattr(sources, "load_scheduling_planning", scheduling)
    monkeypatch.setattr(sources, "authorize_programme_scope", final)
    return SimpleNamespace(
        request=request,
        source=source,
        terms=terms,
        requirement=requirement,
        occurrence=occurrence,
        candidate=candidate,
        day=day,
        placement=placement,
        planning=planning,
        calls=calls,
        overview=overview,
    )


def load(world, **kwargs):
    return sources.load_programme_staffing_selection(
        world.request, source=world.source, **kwargs
    )


def test_exact_selected_source_preserves_explicit_work_and_independent_policies(
    selection,
):
    programme_policy, scheduling_policy = object(), object()
    result = load(
        selection,
        programme_authorizer=programme_policy,
        scheduling_authorizer=scheduling_policy,
    )
    assert result.expectation == selection.terms
    assert result.source == selection.source
    assert result.candidate_version == 2
    assert len(result.evidence_digest) == 64
    assert [row[0] for row in selection.calls] == ["programme", "scheduling", "final"]
    assert selection.calls[0][2]["authorizer"] is programme_policy
    assert selection.calls[1][2]["authorizer"] is scheduling_policy
    assert selection.calls[1][2]["candidate_id"] == selection.source.candidate_id
    assert selection.calls[2][2]["authorizer"] is programme_policy


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("overview", "item_lifecycle", "retired"),
        ("requirement", "revision_id", uuid4()),
        ("requirement", "version", 2),
        ("requirement", "occurrence_id", uuid4()),
        ("requirement", "occurrence_version", 2),
        ("requirement", "lifecycle", "retired"),
        ("candidate", "lifecycle", "archived"),
        ("candidate", "revision_id", uuid4()),
        ("occurrence", "version", 2),
        ("occurrence", "item_id", uuid4()),
        ("occurrence", "lifecycle", "retired"),
        ("placement", "occurrence_id", uuid4()),
        ("placement", "occurrence_revision_id", uuid4()),
        ("day", "lifecycle", "retired"),
        ("day", "revision_id", uuid4()),
        ("planning", "selected_candidate_id", uuid4()),
        ("planning", "accepts_writes", False),
        ("planning", "candidates", ()),
        ("planning", "occurrences", ()),
        ("planning", "placements", ()),
        ("planning", "days", ()),
    ],
)
def test_moved_retired_or_incomplete_source_never_becomes_current(
    selection, target, field, value
):
    setattr(getattr(selection, target), field, value)
    with pytest.raises(sources.ProgrammeStaffingSourceConflictError):
        load(selection)


@pytest.mark.parametrize(
    ("seam", "error"),
    [
        ("load_programme_staffing_requirements", ProgrammeAuthorizationDeniedError),
        ("load_scheduling_planning", SchedulingAuthorizationDeniedError),
        ("authorize_programme_scope", ProgrammeAuthorizationDeniedError),
    ],
)
def test_each_owner_and_final_recheck_can_withhold_the_composed_result(
    selection, monkeypatch, seam, error
):
    def deny(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(sources, seam, deny)
    with pytest.raises(error):
        load(selection)


def test_programme_admission_precedes_parsing_selection(selection, monkeypatch):
    def deny(*_args, **_kwargs):
        raise ProgrammeAuthorizationDeniedError

    monkeypatch.setattr(sources, "load_programme_staffing_requirements", deny)
    selection.source = None
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load(selection)


def test_digest_changes_with_explicit_terms_and_candidate_version(selection):
    original = load(selection).evidence_digest
    selection.requirement.expectation = replace(selection.terms, required_headcount=3)
    assert load(selection).evidence_digest != original
    selection.requirement.expectation = selection.terms
    selection.candidate.version += 1
    assert load(selection).evidence_digest != original


def test_another_alternative_is_never_selected_implicitly(selection):
    original = load(selection)
    selection.planning.candidates += (
        SimpleNamespace(id=uuid4(), revision_id=uuid4(), version=9, lifecycle="draft"),
    )
    assert load(selection) == original
