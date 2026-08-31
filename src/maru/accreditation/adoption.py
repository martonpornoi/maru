"""Exact adoption-manifest keys and contracts owned by Accreditation."""

from maru.events.adoption import profile_allows_adapter
from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

OFFLINE_CHECK_IN_RELAY_ADAPTER = "accreditation.offline-check-in-relay@1"
IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER = (
    "accreditation.identity-restriction-consequence@1"
)

ACCREDITATION_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="accreditation",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=OFFLINE_CHECK_IN_RELAY_ADAPTER,
            owner_module="accreditation",
            kind="offline-write-relay",
            result_semantics=(
                "Admits tenant-bound signed offline check-in reconciliation writes."
            ),
            failure_semantics=(
                "Rejects unavailable, unsigned, stale, or tenant-mismatched relay "
                "evidence without applying a check-in write."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER,
            owner_module="accreditation",
            kind="identity-restriction-consequence",
            result_semantics=(
                "Revokes compatible issued credentials for an organizer account "
                "restriction."
            ),
            failure_semantics=(
                "Leaves credentials unchanged when the edition's exact manifest "
                "does not pin this cross-module consequence."
            ),
        ),
    ),
)
ACCREDITATION_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="accreditation",
    descriptors=(),
)


def profile_allows_offline_check_in_relay(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Return whether an exact profile admits signed offline check-in writes.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins the relay adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        OFFLINE_CHECK_IN_RELAY_ADAPTER,
    )


__all__ = [
    "ACCREDITATION_ADOPTION_ADAPTERS",
    "ACCREDITATION_ADOPTION_CONFLICT_SOURCES",
    "IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER",
    "OFFLINE_CHECK_IN_RELAY_ADAPTER",
    "profile_allows_offline_check_in_relay",
]
