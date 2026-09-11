"""Dormant exact-adoption contracts owned by Programme."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    AdoptionConflictSourceDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER = (
    "programme.accepted-application-source@1"
)
PROGRAMME_SCHEDULING_CONFLICT_SOURCE = "programme.item-and-host-availability@1"
PROGRAMME_PLACEMENT_DECISION_ADAPTER = "programme.placement-decisions@1"
PROGRAMME_RELEASE_SOURCE_ADAPTER = "programme.release-source@1"

PROGRAMME_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="programme",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=PROGRAMME_RELEASE_SOURCE_ADAPTER,
            owner_module="programme",
            kind="release-source",
            result_semantics=(
                "Supplies complete current readiness, independently reviewed-copy "
                "consequences and purpose-bounded person references for release checks."
            ),
            failure_semantics=(
                "Withholds incomplete, unpinned or independently unauthorized "
                "sources without treating curation as independent publication approval."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=PROGRAMME_PLACEMENT_DECISION_ADAPTER,
            owner_module="programme",
            kind="placement-decisions",
            result_semantics=(
                "Retains independently authorized exact-source accessibility-fit "
                "and explicit no-staffing assessments without publishing a candidate."
            ),
            failure_semantics=(
                "Denies unpinned profiles and incomplete, stale or unauthorized "
                "placement evidence without changing retained owner decisions."
            ),
        ),
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
    descriptors=(
        AdoptionConflictSourceDescriptor(
            code=PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
            owner_module="programme",
            kind="item-and-explicit-host-consequences",
            result_semantics=(
                "Projects current item and selected host status, edition-bounded "
                "person conflict keys and only deliberately shared current periods."
            ),
            failure_semantics=(
                "Absent, unpinned, unauthorized or over-bound scope is unavailable; "
                "private or withdrawn availability never means free."
            ),
        ),
    ),
)

__all__ = [
    "PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER",
    "PROGRAMME_ADOPTION_ADAPTERS",
    "PROGRAMME_ADOPTION_CONFLICT_SOURCES",
    "PROGRAMME_PLACEMENT_DECISION_ADAPTER",
    "PROGRAMME_RELEASE_SOURCE_ADAPTER",
    "PROGRAMME_SCHEDULING_CONFLICT_SOURCE",
]
