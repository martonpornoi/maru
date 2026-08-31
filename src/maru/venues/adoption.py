"""Exact adoption adapter contracts owned by Venues."""

from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE = "venues.attendee-schedule@1"

VENUES_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="venues",
    descriptors=(
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
    descriptors=(),
)


__all__ = [
    "VENUES_ADOPTION_ADAPTERS",
    "VENUES_ADOPTION_CONFLICT_SOURCES",
    "VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE",
]
