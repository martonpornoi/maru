"""Exact edition admission and parent locks for Announcements owner commands."""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from maru.events.models import EventEdition
from maru.events.queries import resolve_edition_series_identity
from maru.organizations.write_references import lock_series_ownership


@dataclass(frozen=True, slots=True)
class AnnouncementsEditionScope:
    """Expose current owner facts without content, people or granted authority.

    Attributes
    ----------
    organization_id, series_id, edition_id
        Exact coherent owner identities.
    adoption_profile_code, adoption_profile_version
        The exact supported standalone adoption pair.
    edition_version
        Current edition aggregate version for optimistic source fencing.
    lifecycle
        Current edition lifecycle, including read-only terminal states.
    language_codes, time_zone
        Configured language choices and IANA time zone.
    accepts_writes
        Whether the active parent chain and edition admit ordinary writing.
    """

    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    adoption_profile_code: str
    adoption_profile_version: int
    edition_version: int
    lifecycle: str
    language_codes: tuple[str, ...]
    time_zone: str
    accepts_writes: bool


def resolve_announcements_edition_scope(
    *, organization_id: UUID, edition_id: UUID, for_update: bool = False
) -> AnnouncementsEditionScope | None:
    """Resolve one exact adopted scope, optionally locking its complete chain.

    Parameters
    ----------
    organization_id : UUID
        Independently authorized organization identity, outside session context.
    edition_id : UUID
        Independently authorized edition identity within the organization.
    for_update : bool, default=False
        Lock Organization, ConventionSeries, then EventEdition in the caller's
        atomic transaction before it locks people or Announcements records.

    Returns
    -------
    AnnouncementsEditionScope | None
        Minimized current owner facts, or unavailable for a foreign, unsupported
        or malformed scope, or a requested lock outside an atomic transaction.

    Notes
    -----
    This internal seam grants no authority. Consumers independently authorize
    before disclosure, recheck current people after parent locking, and retain
    the edition version when binding a source observation to a command.
    """
    if any(
        not isinstance(value, UUID) or value.int == 0
        for value in (organization_id, edition_id)
    ):
        return None
    if for_update and not transaction.get_connection().in_atomic_block:
        return None
    series_id = resolve_edition_series_identity(
        organization_id=organization_id, edition_id=edition_id
    )
    if series_id is None:
        return None
    if for_update and not lock_series_ownership(
        organization_id=organization_id, series_id=series_id
    ):
        return None
    query = EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
        series_id=series_id,
        series__organization_id=organization_id,
        adoption_profile_code="announcements_only",
        adoption_profile_version=1,
    )
    if for_update:
        query = query.select_for_update(of=("self",))
    row = query.values(
        "aggregate_version",
        "lifecycle",
        "language_codes",
        "time_zone",
        "organization__lifecycle",
        "series__is_active",
    ).first()
    if row is None:
        return None
    return AnnouncementsEditionScope(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        adoption_profile_code="announcements_only",
        adoption_profile_version=1,
        edition_version=row["aggregate_version"],
        lifecycle=row["lifecycle"],
        language_codes=tuple(row["language_codes"]),
        time_zone=row["time_zone"],
        accepts_writes=(
            row["organization__lifecycle"] == "active"
            and row["series__is_active"]
            and row["lifecycle"] in {"draft", "preparing", "ready", "live"}
        ),
    )
