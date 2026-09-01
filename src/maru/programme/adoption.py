"""Dormant exact-adoption contracts owned by Programme."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER = (
    "programme.accepted-application-source@1"
)

PROGRAMME_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="programme",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER,
            owner_module="programme",
            kind="accepted-application-source",
            result_semantics=(
                "Binds one exact immutable accepted-application transition to one "
                "Programme item without copying private proposal or review content."
            ),
            failure_semantics=(
                "Creates no Programme item or source binding when the exact adapter "
                "is unavailable, unpinned, foreign, stale, or otherwise untrusted."
            ),
        ),
    ),
)

PROGRAMME_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="programme",
    descriptors=(),
)

__all__ = [
    "PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER",
    "PROGRAMME_ADOPTION_ADAPTERS",
    "PROGRAMME_ADOPTION_CONFLICT_SOURCES",
]
