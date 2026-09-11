"""Exact adoption adapter contracts owned by Venues."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    AdoptionConflictSourceDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE = "venues.attendee-schedule@1"
VENUES_SCHEDULING_CONFLICT_SOURCE = "venues.physical-scheduling-dependencies@1"
VENUES_SCHEDULING_RESERVATION_ADAPTER = "venues.scheduling-reservation@1"
VENUES_ACCESSIBILITY_SOURCE_ADAPTER = "venues.accessibility-configuration-source@1"

VENUES_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="venues",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=VENUES_ACCESSIBILITY_SOURCE_ADAPTER,
            owner_module="venues",
            kind="exact-accessibility-configuration-source",
            result_semantics=(
                "Discloses only independently authorized current selected "
                "configuration and member access facts for an explicit fit decision."
            ),
            failure_semantics=(
                "Unpinned, unauthorized, incomplete or retired physical sources "
                "provide no fit evidence or inferred accessibility assessment."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=VENUES_SCHEDULING_RESERVATION_ADAPTER,
            owner_module="venues",
            kind="scheduling-physical-reservation",
            result_semantics=(
                "Atomically reserves or replaces exact Scheduling-owned physical "
                "intent without Venue approval or Programme publication."
            ),
            failure_semantics=(
                "Stale, unpinned, unauthorized or physically conflicting intent "
                "leaves both owners unchanged."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE,
            owner_module="venues",
            kind="attendee-schedule-projection",
            result_semantics=(
                "Projects approved public Venue bookings into an attendee schedule."
            ),
            failure_semantics=(
                "Returns no Venue-derived schedule entry when the exact adapter is "
                "unavailable or unpinned and discloses no booking."
            ),
        ),
    ),
)
VENUES_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="venues",
    descriptors=(
        AdoptionConflictSourceDescriptor(
            code=VENUES_SCHEDULING_CONFLICT_SOURCE,
            owner_module="venues",
            kind="physical-members-capacity-availability-and-busy-periods",
            result_semantics=(
                "Projects selected-space capacity and availability plus minimized "
                "physical-member busy periods inside the current edition envelope."
            ),
            failure_semantics=(
                "Unpinned, unauthorized, incomplete or over-bound dependencies "
                "remain unavailable; no private booking or foreign edition copy leaks."
            ),
        ),
    ),
)


__all__ = [
    "VENUES_ACCESSIBILITY_SOURCE_ADAPTER",
    "VENUES_ADOPTION_ADAPTERS",
    "VENUES_ADOPTION_CONFLICT_SOURCES",
    "VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE",
    "VENUES_SCHEDULING_CONFLICT_SOURCE",
    "VENUES_SCHEDULING_RESERVATION_ADAPTER",
]
