"""Unit coverage for exact Workforce adoption adapters."""

import importlib

import pytest

from maru.workforce.adoption import (
    AssignmentAdoptionProfileError,
    assignment_uses_participation_evidence,
    profile_allows_workforce_self,
)


def test_assignment_evidence_adapter_is_exact_per_current_profile() -> None:
    """Keep current assignment evidence behavior pinned to exact manifests."""
    assert assignment_uses_participation_evidence("full_convention", 1)
    assert not assignment_uses_participation_evidence("workforce_only", 1)


@pytest.mark.parametrize(
    ("profile_code", "profile_version"),
    [("full_convention", 2), ("workforce_only", 2), ("unknown", 1)],
)
def test_assignment_evidence_adapter_fails_closed_for_unknown_exact_profile(
    profile_code: str,
    profile_version: int,
) -> None:
    """Reject unknown versions instead of inferring evidence from a code."""
    with pytest.raises(
        AssignmentAdoptionProfileError,
        match="does not define assignment evidence",
    ):
        assignment_uses_participation_evidence(profile_code, profile_version)


def test_workforce_self_discovery_is_pinned_to_exact_manifest_versions() -> None:
    """Keep both current profiles working without accepting future versions."""
    assert profile_allows_workforce_self("full_convention", 1)
    assert profile_allows_workforce_self("workforce_only", 1)
    assert not profile_allows_workforce_self("full_convention", 2)
    assert not profile_allows_workforce_self("workforce_only", 2)
    assert not profile_allows_workforce_self("unknown", 1)


def test_assignment_database_guard_transformation_is_exact_and_reversible() -> None:
    """Pin the additive SQL transform to its reviewed source fingerprints."""
    code_only = importlib.import_module(
        "maru.workforce.migrations.0014_workforce_only_assignment_evidence"
    )
    exact = importlib.import_module(
        "maru.workforce.migrations.0015_exact_assignment_adoption_profile"
    )
    prior_source = code_only._assignment_source(
        _initial_assignment_guard_source(),
        enable=True,
    )

    exact_source = exact._assignment_source(prior_source, enable=True)

    assert exact._source_sha256(prior_source) == exact._PRIOR_SOURCE_SHA256
    assert exact._source_sha256(exact_source) == exact._EXACT_PROFILE_SOURCE_SHA256
    assert "edition.adoption_profile_version" in exact_source
    assert "assignment_profile_version = 1" in exact_source
    assert "exact adoption profile is unsupported" in exact_source
    assert exact._assignment_source(exact_source, enable=False) == prior_source


def _initial_assignment_guard_source() -> str:
    migration = importlib.import_module(
        "maru.workforce.migrations.0011_owner_assignment_commands"
    )
    delimiter = "$assignment_guard$"
    return migration.FORWARD_SQL.split(f"AS {delimiter}", 1)[1].split(
        delimiter,
        1,
    )[0]
