"""Code-owned event-edition adoption profiles and module boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection


class AdoptionProfileCode(StrEnum):
    """Enumerate supported event-edition adoption profiles."""

    FULL_CONVENTION = "full_convention"
    WORKFORCE_ONLY = "workforce_only"


ADOPTION_PROFILE_VERSION = 1

FOUNDATION_MODULES = frozenset(
    {
        "audit",
        "authorization",
        "effects",
        "events",
        "identity",
        "organizations",
        "privacy",
    }
)

FULL_CONVENTION_MODULES = FOUNDATION_MODULES | frozenset(
    {
        "accreditation",
        "applications",
        "catalog",
        "charities",
        "communications",
        "logistics",
        "participation",
        "registration",
        "venues",
        "workforce",
    }
)

WORKFORCE_ONLY_MODULES = FOUNDATION_MODULES | frozenset({"workforce"})


@dataclass(frozen=True, slots=True)
class AdoptionProfile:
    """Describe one versioned, code-owned edition adoption profile.

    Attributes
    ----------
    code
        The stable profile code stored on an event edition.
    version
        The code-owned semantic version of the profile contract.
    label
        The concise human-readable profile name.
    description
        The plain-language boundary shown during setup and review.
    modules
        The module namespaces permitted for exact-edition operations.
    primary_module
        The product module that anchors the next action after setup.
    """

    code: AdoptionProfileCode
    version: int
    label: str
    description: str
    modules: frozenset[str]
    primary_module: str


ADOPTION_PROFILES = {
    AdoptionProfileCode.FULL_CONVENTION: AdoptionProfile(
        code=AdoptionProfileCode.FULL_CONVENTION,
        version=ADOPTION_PROFILE_VERSION,
        label="Full convention",
        description=(
            "Use Maru as the convention-wide operating platform. All implemented "
            "edition modules may be configured independently."
        ),
        modules=FULL_CONVENTION_MODULES,
        primary_module="events",
    ),
    AdoptionProfileCode.WORKFORCE_ONLY: AdoptionProfile(
        code=AdoptionProfileCode.WORKFORCE_ONLY,
        version=ADOPTION_PROFILE_VERSION,
        label="Workforce only",
        description=(
            "Use Maru for volunteer structure, Positions, assignments, "
            "Availability, and Shifts without adopting attendee registration, "
            "payments, or unrelated convention modules."
        ),
        modules=WORKFORCE_ONLY_MODULES,
        primary_module="workforce",
    ),
}

ADOPTION_PROFILE_CHOICES = tuple(
    (profile.code.value, profile.label) for profile in ADOPTION_PROFILES.values()
)


def adoption_profile(code: str) -> AdoptionProfile | None:
    """Return the supported profile for a persisted code.

    Parameters
    ----------
    code : str
        The persisted adoption-profile code.

    Returns
    -------
    AdoptionProfile | None
        The matching profile, or ``None`` for an unknown code.
    """
    try:
        normalized = AdoptionProfileCode(code)
    except ValueError:
        return None
    return ADOPTION_PROFILES.get(normalized)


def profile_adopts_module(profile_code: str, module_code: str) -> bool:
    """Return whether a profile deliberately adopts one module namespace.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    module_code : str
        The stable top-level product or foundation module namespace.

    Returns
    -------
    bool
        ``True`` only when the profile and module are both code-owned.
    """
    profile = adoption_profile(profile_code)
    return profile is not None and module_code in profile.modules


def profile_allows_capability(profile_code: str, capability_code: str) -> bool:
    """Return whether an exact-edition capability belongs to the profile.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    capability_code : str
        The code-owned capability being evaluated.

    Returns
    -------
    bool
        ``True`` only when the capability namespace is adopted.
    """
    module_code, separator, _operation = capability_code.partition(".")
    return bool(separator and profile_adopts_module(profile_code, module_code))


def profile_allows_capabilities(
    profile_code: str,
    capability_codes: Collection[str],
) -> bool:
    """Return whether every capability belongs to an adopted module.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    capability_codes : Collection[str]
        The complete capability set of one access group.

    Returns
    -------
    bool
        ``True`` only for a non-empty capability set wholly inside the profile.
    """
    return bool(capability_codes) and all(
        profile_allows_capability(profile_code, code) for code in capability_codes
    )


def profile_codes_for_module(module_code: str) -> tuple[str, ...]:
    """Return profile codes that deliberately adopt one module.

    Parameters
    ----------
    module_code : str
        The stable top-level product or foundation module namespace.

    Returns
    -------
    tuple[str, ...]
        Matching profile codes in deterministic catalog order.
    """
    return tuple(
        profile.code.value
        for profile in ADOPTION_PROFILES.values()
        if module_code in profile.modules
    )
