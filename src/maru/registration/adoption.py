"""Exact adoption-manifest keys and contracts owned by Registration."""

from maru.events.adoption import profile_allows_adapter, profile_allows_catalog_entry
from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER = (
    "registration.identity-restriction-consequence@1"
)

REGISTRATION_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="registration",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER,
            owner_module="registration",
            kind="identity-restriction-consequence",
            result_semantics=(
                "Applies a compatible organizer account restriction to retained "
                "Registration state and public-profile visibility."
            ),
            failure_semantics=(
                "Leaves Registration rows unchanged when the edition's exact "
                "manifest does not pin this cross-module consequence."
            ),
        ),
    ),
)
REGISTRATION_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="registration",
    descriptors=(),
)


def registration_starter_entry_code(starter_code: str, starter_version: int) -> str:
    """Return the manifest key for one immutable Registration starter.

    Parameters
    ----------
    starter_code : str
        Stable code owned by the Registration starter catalog.
    starter_version : int
        Immutable starter version.

    Returns
    -------
    str
        Exact versioned manifest entry.
    """
    return f"registration.starter.{starter_code}@{starter_version}"


def profile_allows_registration_starter(
    profile_code: str,
    profile_version: int,
    starter_code: str,
    starter_version: int,
) -> bool:
    """Return whether an exact profile pins one Registration starter.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    starter_code : str
        Stable code owned by the Registration starter catalog.
    starter_version : int
        Immutable starter version.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins the starter version.
    """
    return profile_allows_catalog_entry(
        profile_code,
        profile_version,
        registration_starter_entry_code(starter_code, starter_version),
    )


def profile_allows_identity_restriction_consequence(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Return whether Identity may apply Registration consequences.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins this cross-module adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER,
    )


__all__ = [
    "IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER",
    "REGISTRATION_ADOPTION_ADAPTERS",
    "REGISTRATION_ADOPTION_CONFLICT_SOURCES",
    "profile_allows_identity_restriction_consequence",
    "profile_allows_registration_starter",
    "registration_starter_entry_code",
]
