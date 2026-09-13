"""Independent hosting and retained-work layers in one exact-person timetable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction
from django.utils import timezone

from maru.events.adoption import profile_allows_adapter, profile_allows_capability
from maru.events.personal_timetable_queries import (
    PersonalTimetableEditionLabel,
    resolve_personal_timetable_edition_label,
)
from maru.events.queries import edition_adoption_profile_reference
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import resolve_active_verified_person_reference
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.venues.personal_programme_queries import load_personal_host_room_wayfinding
from maru.venues.scheduling_queries import VenueSchedulingSourceUnavailableError
from maru.workforce.adoption import WORKFORCE_SELF_ADAPTER
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)
from maru.workforce.shift_queries import ShiftReadLimitExceededError
from maru.workforce.timetable_queries import (
    PersonalShiftTimetableEntry,
    load_personal_shift_timetable,
)

from .authorization import VIEW_HOST_SELF, SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .personal_release_references import (
    PersonalHostReleaseReference,
    load_personal_host_release_reference,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.venues.programme_output_queries import ReleasedRoomWayfinding


@dataclass(frozen=True, slots=True)
class PersonalHostingLayer:
    """Independently authorized hosting with exact presence and current wayfinding.

    Attributes
    ----------
    reference
        Own confirmed/retained purposes and checked approved host-presence source.
    rooms
        Complete independently proven current wayfinding for those presences only.
    """

    reference: PersonalHostReleaseReference
    rooms: tuple[ReleasedRoomWayfinding, ...]


@dataclass(frozen=True, slots=True)
class PersonalTimetable:
    """Closed private composition, not an augmented public response.

    Attributes
    ----------
    actor_id
        Exact current person owning both optional layers.
    organization_id
        Exact shared tenant scope.
    edition_id
        Exact edition, with no cross-edition work or attendee lookup.
    checked_at
        Server observation after complete independent owner/source rechecks.
    zone_name
        Current Events-owned IANA zone.
    hosting
        Authorized hosting layer; None means unadopted, never unavailable/empty.
    shifts
        Authorized retained Workforce work; None means unadopted, not no work.
    edition_label
        Current Events label/version only when actual own records justify context.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    checked_at: datetime
    zone_name: str
    hosting: PersonalHostingLayer | None
    shifts: tuple[PersonalShiftTimetableEntry, ...] | None
    edition_label: PersonalTimetableEditionLabel | None = None


def _adopted_layers(organization_id: UUID, edition_id: UUID) -> tuple[bool, bool]:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None:
        raise SchedulingAuthorizationDeniedError
    hosting = (
        profile_allows_capability(profile.code, profile.version, VIEW_HOST_SELF),
        profile_allows_capability(
            profile.code, profile.version, "programme.view_host_self"
        ),
    )
    workforce = (
        profile_allows_capability(profile.code, profile.version, "workforce.view_self"),
        profile_allows_adapter(profile.code, profile.version, WORKFORCE_SELF_ADAPTER),
    )
    if any(hosting) != all(hosting) or any(workforce) != all(workforce):
        raise SchedulingUnavailableError
    if not any((*hosting, *workforce)):
        raise SchedulingAuthorizationDeniedError
    return all(hosting), all(workforce)


def load_personal_timetable(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> PersonalTimetable:
    """Compose only adopted, independently authorized own hosting and retained work.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated current person; no caller-selected other owner.
    organization_id : UUID
        Exact common tenant for independently owned source layers.
    edition_id : UUID
        Exact edition; each layer's current adoption remains independent.
    correlation_id : UUID
        Trusted trace retained by the owners' mandatory sensitive-read audits.

    Returns
    -------
    PersonalTimetable
        Complete current private composition. Unadopted layers are explicitly
        absent; adopted but denied, unavailable or moving layers fail closed.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If current person, exact scope or any adopted owner's authority fails.
    SchedulingUnavailableError
        If adoption is incomplete or an adopted source is unavailable or moving.

    Notes
    -----
    Workforce-only performs no Programme or release lookup. Hosting does not
    require anonymous publication or a planner grant. Approved host presence
    never rewrites retained Shift intervals or silently changes their location.
    Claimed, confirmed and ended work retain their owner states. No availability,
    suitable unclaimed work, Participation, attendance or notification is created.
    This read-only projection is not a cache permission or offline-freshness lease.
    """
    for value in (actor_id, organization_id, edition_id, correlation_id):
        require_identifier(value)
    arguments = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }
    try:
        with transaction.atomic():
            adopted = _adopted_layers(organization_id, edition_id)
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise SchedulingAuthorizationDeniedError
            if (
                resolve_active_verified_person_reference(account_id=actor_id, lock=True)
                is None
            ):
                raise SchedulingAuthorizationDeniedError
            if _adopted_layers(organization_id, edition_id) != adopted:
                raise SchedulingUnavailableError
            edition = resolve_scheduling_edition_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if edition is None:
                raise SchedulingAuthorizationDeniedError
            hosting = _hosting(arguments) if adopted[0] else None
            shifts = load_personal_shift_timetable(**arguments) if adopted[1] else None
            label = None
            if shifts or (hosting is not None and hosting.reference.purposes):
                label = resolve_personal_timetable_edition_label(
                    organization_id=organization_id, edition_id=edition_id
                )
                if label is None:
                    raise SchedulingUnavailableError
            if (
                hosting is not None
                and load_personal_host_release_reference(**arguments)
                != hosting.reference
            ):
                raise SchedulingUnavailableError
            if (
                shifts is not None
                and load_personal_shift_timetable(**arguments) != shifts
            ):
                raise SchedulingUnavailableError
            if _adopted_layers(organization_id, edition_id) != adopted:
                raise SchedulingUnavailableError
            return PersonalTimetable(
                actor_id,
                organization_id,
                edition_id,
                timezone.now(),
                edition.zone_name,
                hosting,
                shifts,
                label,
            )
    except (ProgrammeAuthorizationDeniedError, ShiftAuthorizationDeniedError) as error:
        raise SchedulingAuthorizationDeniedError from error
    except (
        DatabaseError,
        ProgrammeQueryUnavailableError,
        VenueSchedulingSourceUnavailableError,
        ShiftUnavailableError,
        ShiftReadLimitExceededError,
    ) as error:
        raise SchedulingUnavailableError from error


def _hosting(arguments: dict[str, UUID]) -> PersonalHostingLayer:
    reference = load_personal_host_release_reference(**arguments)
    rooms: tuple[ReleasedRoomWayfinding, ...] = ()
    if reference.presences:
        if reference.release_id is None:
            raise SchedulingUnavailableError
        rooms = load_personal_host_room_wayfinding(
            **arguments, expected_release_id=reference.release_id
        )
        if len(rooms) != len({row.space_id for row in rooms}) or {
            row.space_id for row in rooms
        } != {row.space_id for row in reference.presences}:
            raise SchedulingUnavailableError
    return PersonalHostingLayer(reference, rooms)
