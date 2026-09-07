"""Identifier-free current-person checks behind authorized readiness summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.events.queries import resolve_edition_time_envelope_reference
from maru.identity.queries import resolve_active_verified_person_reference

from .host_catalogs import MAX_HOST_AVAILABILITY_PERIODS, MAX_HOSTS_PER_ITEM
from .models import ProgrammeHostAvailabilityWindow, ProgrammeHostRelationship

if TYPE_CHECKING:
    from uuid import UUID


def _current_host_readiness(
    *, organization_id: UUID, edition_id: UUID, item_id: UUID
) -> dict[str, bool]:
    envelope = resolve_edition_time_envelope_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=True,
    )
    hosts = tuple(
        ProgrammeHostRelationship.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            item_id=item_id,
            state__in=("invited", "confirmed"),
        ).order_by("account_id")[: MAX_HOSTS_PER_ITEM + 1]
    )
    confirmation = bool(hosts) and len(hosts) <= MAX_HOSTS_PER_ITEM
    availability = confirmation and envelope is not None
    for host in hosts:
        current = resolve_active_verified_person_reference(
            account_id=host.account_id, lock=True
        )
        confirmed = current is not None and host.state == "confirmed"
        confirmation = confirmation and confirmed
        if not confirmed or host.availability_state != "shared" or envelope is None:
            availability = False
            continue
        periods = tuple(
            ProgrammeHostAvailabilityWindow.objects.filter(host=host).values_list(
                "starts_at", "ends_at"
            )[: MAX_HOST_AVAILABILITY_PERIODS + 1]
        )
        availability = (
            availability
            and bool(periods)
            and len(periods) <= MAX_HOST_AVAILABILITY_PERIODS
            and all(
                envelope.starts_at <= start < end <= envelope.ends_at
                for start, end in periods
            )
        )
    return {"host_confirmation": confirmation, "schedule_availability": availability}
