"""Exact adoption-profile adapters owned by Workforce."""

from django.core.exceptions import ValidationError

from maru.events.adoption import profile_allows_adapter
from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER = (
    "workforce.assignment.participation-required@1"
)
ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER = (
    "workforce.assignment.participation-excluded@1"
)
WORKFORCE_SELF_ADAPTER = "workforce.self@1"

WORKFORCE_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="workforce",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER,
            owner_module="workforce",
            kind="assignment-evidence",
            result_semantics=(
                "Requires assignment activation to create Participation evidence."
            ),
            failure_semantics=(
                "Rejects assignment evidence selection when the exact adapter is "
                "unavailable or ambiguous and commits no assignment effects."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER,
            owner_module="workforce",
            kind="assignment-evidence",
            result_semantics=(
                "Excludes Participation evidence and requires a null assignment "
                "capacity pointer."
            ),
            failure_semantics=(
                "Rejects assignment evidence selection when the exact adapter is "
                "unavailable or ambiguous and creates no substitute Participation."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=WORKFORCE_SELF_ADAPTER,
            owner_module="workforce",
            kind="self-discovery",
            result_semantics=(
                "Discovers person-owned Workforce surfaces for an exact edition."
            ),
            failure_semantics=(
                "Returns no Workforce self-service surface when the exact adapter is "
                "unavailable or unpinned."
            ),
        ),
    ),
)
WORKFORCE_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="workforce",
    descriptors=(),
)


class AssignmentAdoptionProfileError(ValidationError):
    """Report an exact profile that has no unambiguous assignment adapter."""


def profile_allows_workforce_self(profile_code: str, profile_version: int) -> bool:
    """Return whether an exact manifest pins Workforce personal discovery.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code for the personal edition scope.
    profile_version : int
        Persisted adoption-profile version for the personal edition scope.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins the Workforce self adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        WORKFORCE_SELF_ADAPTER,
    )


def assignment_uses_participation_evidence(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Resolve the exact Workforce assignment-evidence adapter.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code for the assignment's edition.
    profile_version : int
        Persisted adoption-profile version for the assignment's edition.

    Returns
    -------
    bool
        ``True`` when assignment activation must create Participation evidence;
        ``False`` when the exact profile deliberately excludes it.

    Raises
    ------
    AssignmentAdoptionProfileError
        If the exact manifest is unknown, pins neither adapter, or pins both.
    """
    participation_required = profile_allows_adapter(
        profile_code,
        profile_version,
        ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER,
    )
    participation_excluded = profile_allows_adapter(
        profile_code,
        profile_version,
        ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER,
    )
    if participation_required == participation_excluded:
        raise AssignmentAdoptionProfileError(
            "The edition adoption profile does not define assignment evidence.",
            code="unsupported_assignment_adoption_profile",
        )
    return participation_required


__all__ = [
    "ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER",
    "ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER",
    "WORKFORCE_ADOPTION_ADAPTERS",
    "WORKFORCE_ADOPTION_CONFLICT_SOURCES",
    "WORKFORCE_SELF_ADAPTER",
    "AssignmentAdoptionProfileError",
    "assignment_uses_participation_evidence",
    "profile_allows_workforce_self",
]
