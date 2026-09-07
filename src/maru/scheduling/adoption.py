"""Exact dormant Scheduling adapters and conflict-source declarations."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    AdoptionConflictSourceDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

SCHEDULING_VENUE_RESERVATION_ADAPTER = "scheduling.venue-reservation@1"
SCHEDULING_TIME_CONFLICT_SOURCE = "scheduling.service-day-and-placement@1"

SCHEDULING_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="scheduling",
    descriptors=(
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
