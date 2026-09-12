"""Exact-person approved host presence, independent from anonymous publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Count

from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.programme.timetable_queries import (
    PersonalHostPurpose,
    load_personal_host_purposes,
)

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HOST_SELF
from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .models import (
    SchedulingPlacementHostPresence,
    SchedulingPlacementRevision,
    SchedulingRelease,
)
from .planning_queries import SchedulingReadRequest, _read
from .release_queries import ProgrammeReleaseManifest, ProgrammeReleaseState, _manifest
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    type _PresenceRow = tuple[
        UUID,
        UUID,
        UUID,
        UUID,
        UUID,
        UUID,
        datetime,
        datetime,
        datetime,
        datetime,
        datetime,
        datetime,
        datetime,
        datetime,
    ]


@dataclass(frozen=True, slots=True)
class PersonalHostPresence:
    """One exact approved own presence, not everybody's preparation assignment.

    Attributes
    ----------
    host_id
        Current person's confirmed Programme relationship.
    occurrence_id
        Stable occurrence selected by the checked active release.
    placement_id
        Exact immutable placement source for this interval.
    space_id
        Opaque room identity; owner labels require a separate purpose-bound read.
    day_id
        Exact stable service day, without a private planning label.
    day_starts_at
        Exact selected service-day start.
    day_ends_at
        Exact selected service-day end.
    starts_at
        Approved required own presence start, not private availability.
    ends_at
        Approved required own presence end.
    envelope
        Surrounding preparation, effective delivery and teardown context.
    """

    host_id: UUID
    occurrence_id: UUID
    placement_id: UUID
    space_id: UUID
    day_id: UUID
    day_starts_at: datetime
    day_ends_at: datetime
    starts_at: datetime
    ends_at: datetime
    envelope: SchedulingEnvelope


@dataclass(frozen=True, slots=True)
class PersonalHostReleaseReference:
    """Purpose-bound checked source, never a reusable permission or public roster.

    Attributes
    ----------
    state
        Checked release state, or None when no confirmed purpose permits lookup.
    pointer_version
        Checked pointer sequence, or None when no release lookup was authorized.
    release_id
        Exact checked release identity, where applicable.
    published_at
        Exact release creation instant, where applicable.
    zone_name
        Current Events-owned IANA zone.
    purposes
        Complete independently authorized own retained relationships/invitations.
    presences
        Own approved presence only while a complete active release is available.
    """

    state: ProgrammeReleaseState | None
    pointer_version: int | None
    release_id: UUID | None
    published_at: datetime | None
    zone_name: str
    purposes: tuple[PersonalHostPurpose, ...]
    presences: tuple[PersonalHostPresence, ...]


def _presences(
    request: SchedulingReadRequest,
    manifest: ProgrammeReleaseManifest,
    confirmed: dict[UUID, PersonalHostPurpose],
) -> tuple[PersonalHostPresence, ...]:
    if manifest.state is not ProgrammeReleaseState.AVAILABLE:
        return ()
    selected = {row.placement_id: row for row in manifest.selections}
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    counts = tuple(
        SchedulingPlacementRevision.objects.filter(**ownership, id__in=selected)
        .annotate(actual=Count("host_presences"))
        .values_list("id", "host_presence_count", "actual")[: MAX_OCCURRENCES + 1]
    )
    if (
        len(counts) != len(selected)
        or any(expected != actual for _, expected, actual in counts)
        or {identifier for identifier, _, _ in counts} != set(selected)
    ):
        raise SchedulingUnavailableError
    rows = tuple(
        SchedulingPlacementHostPresence.objects.filter(
            **ownership,
            placement_id__in=selected,
            host_relationship_id__in=confirmed,
            placement__organization_id=request.organization_id,
            placement__edition_id=request.edition_id,
            placement__occurrence_revision__organization_id=request.organization_id,
            placement__occurrence_revision__edition_id=request.edition_id,
            placement__occurrence_revision__occurrence__organization_id=request.organization_id,
            placement__occurrence_revision__occurrence__edition_id=request.edition_id,
            placement__day_revision__organization_id=request.organization_id,
            placement__day_revision__edition_id=request.edition_id,
        )
        .order_by("starts_at", "placement_id", "host_relationship_id")
        .values_list(
            "host_relationship_id",
            "placement_id",
            "placement__occurrence_revision__occurrence_id",
            "placement__occurrence_revision__occurrence__programme_item_id",
            "placement__space_selection_id",
            "placement__day_revision__day_id",
            "placement__day_revision__starts_at",
            "placement__day_revision__ends_at",
            "starts_at",
            "ends_at",
            "placement__setup_starts_at",
            "placement__effective_starts_at",
            "placement__effective_ends_at",
            "placement__teardown_ends_at",
        )[: MAX_OCCURRENCES + 1]
    )
    if len(rows) > MAX_OCCURRENCES:
        raise SchedulingUnavailableError
    return tuple(
        _presence(row, selected[row[1]].occurrence_id, confirmed[row[0]])
        for row in rows
    )


def _presence(
    row: _PresenceRow, occurrence_id: UUID, purpose: PersonalHostPurpose
) -> PersonalHostPresence:
    (
        host,
        placement,
        occurrence,
        item,
        space,
        day,
        day_start,
        day_end,
        start,
        end,
        setup,
        effective_start,
        effective_end,
        teardown,
    ) = row
    if (
        occurrence != occurrence_id
        or item != purpose.item_id
        or not day_start
        <= setup
        <= effective_start
        < effective_end
        <= teardown
        <= day_end
        or not setup <= start < end <= teardown
    ):
        raise SchedulingUnavailableError
    return PersonalHostPresence(
        host,
        occurrence,
        placement,
        space,
        day,
        day_start,
        day_end,
        start,
        end,
        SchedulingEnvelope(setup, effective_start, effective_end, teardown),
    )


def load_personal_host_release_reference(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> PersonalHostReleaseReference:
    """Prove exact self and host purpose before selecting any released own presence.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated current person; no other subject selector exists.
    organization_id : UUID
        Exact expected owner, rechecked independently by Programme.
    edition_id : UUID
        Exact edition admitting both host-self capability contracts.
    correlation_id : UUID
        Trace identifier for both owners' mandatory sensitive-read evidence.

    Returns
    -------
    PersonalHostReleaseReference
        Complete own-purpose source with current approved presence only. No
        confirmed hosting yields no release lookup, not a false absent release.

    Notes
    -----
    Real self policy is mandatory; neither planner grants nor public admission
    stand in for this purpose. Shared parents precede the exact person lock.
    Programme purposes and the canonical/native manifest are rechecked before
    final Scheduling authorization and audit. Withdrawn/invalidated releases
    contain no approved host intervals. This read never alters accepted Shifts,
    reveals other hosts, treats pending invitations as work or infers attendance.
    """
    request = SchedulingReadRequest(
        actor_id, organization_id, edition_id, correlation_id
    )
    arguments = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }

    def load(_scope: object) -> PersonalHostReleaseReference:
        purposes = load_personal_host_purposes(**arguments)
        confirmed = {row.host_id: row for row in purposes if row.state == "confirmed"}
        edition = resolve_scheduling_edition_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        if edition is None:
            raise SchedulingUnavailableError
        manifest = None
        presences: tuple[PersonalHostPresence, ...] = ()
        published_at = None
        if confirmed:
            manifest = _manifest(
                organization_id=organization_id, edition_id=edition_id, release_id=None
            )
            presences = _presences(request, manifest, confirmed)
            if manifest.release_id is not None:
                published_at = (
                    SchedulingRelease.objects.filter(
                        organization_id=organization_id,
                        edition_id=edition_id,
                        id=manifest.release_id,
                    )
                    .values_list("occurred_at", flat=True)
                    .first()
                )
                if published_at is None:
                    raise SchedulingUnavailableError
        if load_personal_host_purposes(**arguments) != purposes:
            raise SchedulingUnavailableError
        if (
            manifest is not None
            and _manifest(
                organization_id=organization_id, edition_id=edition_id, release_id=None
            )
            != manifest
        ):
            raise SchedulingUnavailableError
        return PersonalHostReleaseReference(
            manifest.state if manifest else None,
            manifest.pointer_version if manifest else None,
            manifest.release_id if manifest else None,
            published_at,
            edition.zone_name,
            purposes,
            presences,
        )

    return _read(
        request,
        capability=VIEW_HOST_SELF,
        fields=frozenset({"own_host_schedule"}),
        purpose="personal_host_release",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=load,
    )
