from __future__ import annotations

import pytest

from maru.programme.catalogs import (
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
    ProgrammeReadinessProjectionState,
)
from maru.programme.readiness import project_readiness_state


def test_required_without_evidence_stays_explicit() -> None:
    projection = project_readiness_state(
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        requirement_version=1,
        dependency_version=0,
        evidence_state=None,
        evidence_requirement_version=None,
        evidence_dependency_version=None,
    )
    assert projection.state is ProgrammeReadinessProjectionState.REQUIRED
    assert projection.dependency_version == 0


@pytest.mark.parametrize(
    ("evidence_state", "projected_state"),
    [
        ("satisfied", ProgrammeReadinessProjectionState.SATISFIED),
        ("blocked", ProgrammeReadinessProjectionState.BLOCKED),
        ("unavailable", ProgrammeReadinessProjectionState.UNAVAILABLE),
    ],
)
def test_current_evidence_projects_without_a_score(
    evidence_state: str,
    projected_state: ProgrammeReadinessProjectionState,
) -> None:
    projection = project_readiness_state(
        disposition="required",
        requirement_version=3,
        dependency_version=7,
        evidence_state=evidence_state,
        evidence_requirement_version=3,
        evidence_dependency_version=7,
    )
    assert projection.state is projected_state


def test_changed_requirement_or_dependency_makes_evidence_stale() -> None:
    for evidence_versions in ((2, 7), (3, 6)):
        projection = project_readiness_state(
            disposition=ProgrammeReadinessDisposition.REQUIRED,
            requirement_version=3,
            dependency_version=7,
            evidence_state=ProgrammeReadinessEvidenceState.SATISFIED,
            evidence_requirement_version=evidence_versions[0],
            evidence_dependency_version=evidence_versions[1],
        )
        assert projection.state is ProgrammeReadinessProjectionState.STALE


def test_not_applicable_is_explicit_even_when_old_evidence_exists() -> None:
    projection = project_readiness_state(
        disposition=ProgrammeReadinessDisposition.NOT_APPLICABLE,
        requirement_version=4,
        dependency_version=9,
        evidence_state=ProgrammeReadinessEvidenceState.BLOCKED,
        evidence_requirement_version=3,
        evidence_dependency_version=8,
    )
    assert projection.state is ProgrammeReadinessProjectionState.NOT_APPLICABLE


@pytest.mark.parametrize(
    "values",
    [
        {
            "requirement_version": 0,
            "dependency_version": 0,
            "evidence_state": None,
            "evidence_requirement_version": None,
            "evidence_dependency_version": None,
        },
        {
            "requirement_version": 1,
            "dependency_version": -1,
            "evidence_state": None,
            "evidence_requirement_version": None,
            "evidence_dependency_version": None,
        },
        {
            "requirement_version": 1,
            "dependency_version": 0,
            "evidence_state": None,
            "evidence_requirement_version": 1,
            "evidence_dependency_version": 0,
        },
        {
            "requirement_version": 1,
            "dependency_version": 0,
            "evidence_state": "satisfied",
            "evidence_requirement_version": None,
            "evidence_dependency_version": 0,
        },
    ],
)
def test_projection_rejects_incomplete_or_invalid_versions(values) -> None:
    with pytest.raises(ValueError, match="version"):
        project_readiness_state(
            disposition="required",
            **values,
        )
