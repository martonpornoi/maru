"""Exact dormant Scheduling adapters and conflict-source declarations."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    AdoptionConflictSourceDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

SCHEDULING_VENUE_RESERVATION_ADAPTER = "scheduling.venue-reservation@1"
SCHEDULING_TIME_CONFLICT_SOURCE = "scheduling.service-day-and-placement@1"
SCHEDULING_RELEASE_SOURCE_ADAPTER = "scheduling.release-candidate-source@1"
SCHEDULING_RELEASE_PREFLIGHT_ADAPTER = "scheduling.release-preflight@1"

SCHEDULING_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="scheduling",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=SCHEDULING_RELEASE_PREFLIGHT_ADAPTER,
            owner_module="scheduling",
            kind="complete-release-preflight",
            result_semantics=(
                "Collects all ten independently authorized release categories; "
                "never persists approval or changes a publication."
            ),
            failure_semantics=(
                "Missing, stale, denied or incomplete owner evidence cannot "
                "produce release eligibility or waive a warning."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=SCHEDULING_RELEASE_SOURCE_ADAPTER,
            owner_module="scheduling",
            kind="exact-release-candidate-source",
            result_semantics=(
                "Returns one complete authorized exact candidate manifest and "
                "minimized placement facts, not approval or publication."
            ),
            failure_semantics=(
                "Unpinned, foreign, incomplete, empty, archived or stale sources "
                "are unavailable and never yield release authority."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=SCHEDULING_VENUE_RESERVATION_ADAPTER,
            owner_module="scheduling",
            kind="programme-venue-reservation",
            result_semantics=(
                "Binds an exact occurrence placement to governed Venue occupancy "
                "without Programme publication."
            ),
            failure_semantics=(
                "No reservation or replacement commits for stale, unpinned, "
                "unauthorized or incomplete source evidence."
            ),
        ),
    ),
)
SCHEDULING_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="scheduling",
    descriptors=(
        AdoptionConflictSourceDescriptor(
            code=SCHEDULING_TIME_CONFLICT_SOURCE,
            owner_module="scheduling",
            kind="service-day-and-candidate-occupancy",
            result_semantics=(
                "Checks exact service-day revision, minute grid and candidate "
                "physical-member overlaps."
            ),
            failure_semantics=(
                "Missing, stale, over-bound or unavailable scope never produces "
                "a passing or complete result."
            ),
        ),
    ),
)
