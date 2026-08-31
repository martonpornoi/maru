"""Exact adoption adapter contracts owned by Participation."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

PARTICIPATION_ATTENDEE_ADAPTER_CODE = "participation.attendee@1"

PARTICIPATION_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="participation",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=PARTICIPATION_ATTENDEE_ADAPTER_CODE,
            owner_module="participation",
            kind="attendee-discovery",
            result_semantics=(
                "Discovers exact-edition attendee relationships for personal context."
            ),
            failure_semantics=(
                "Returns no attendee relationship when the exact adapter is "
                "unavailable or unpinned and never infers Participation."
            ),
        ),
    ),
)
PARTICIPATION_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="participation",
    descriptors=(),
)


__all__ = [
    "PARTICIPATION_ADOPTION_ADAPTERS",
    "PARTICIPATION_ADOPTION_CONFLICT_SOURCES",
    "PARTICIPATION_ATTENDEE_ADAPTER_CODE",
]
