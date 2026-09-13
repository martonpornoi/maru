"""Current public-admitted release references, never a portable access token."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.events.write_references import lock_edition_ownership

from .adoption import SCHEDULING_PUBLIC_RELEASE_ADAPTER
from .authorization import SchedulingAuthorizationDeniedError
from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .models import SchedulingPlacementRevision, SchedulingRelease
from .release_queries import ProgrammeReleaseManifest, ProgrammeReleaseState, _manifest

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicReleaseOccurrenceReference:
    """Exact effective geometry and opaque references for independent owner reads.

    Attributes
    ----------
    occurrence_id
        Stable released occurrence identity.
    item_id
        Opaque Programme owner reference, not a private-content permission.
    public_rendition_id
        Exact immutable approved copy selected by the release.
    space_id
        Exact selected room; wayfinding names belong to Venues.
    day_id
        Stable service-day identity without its private planning label.
    day_starts_at
        Exact selected immutable service-day start instant.
    day_ends_at
        Exact selected immutable service-day end instant.
    starts_at
        Approved effective delivery start, excluding private work phases.
    ends_at
        Approved effective delivery end, excluding private work phases.
    """

    occurrence_id: UUID
    item_id: UUID
    public_rendition_id: UUID
    space_id: UUID
    day_id: UUID
    day_starts_at: datetime
    day_ends_at: datetime
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class PublicReleaseReference:
    """Bounded internal source identity, independently refreshed by each owner.

    Attributes
    ----------
    manifest
        Checked current active release state and exact canonical selections.
    zone_name
        Current Events-owned IANA zone, never a browser-supplied zone.
    published_at
        Immutable release creation instant, absent before any active selection.
    occurrences
        Complete deterministic effective geometry only while available.
    """

    manifest: ProgrammeReleaseManifest
    zone_name: str
    published_at: datetime | None
    occurrences: tuple[PublicReleaseOccurrenceReference, ...]


def _admit(organization_id: UUID, edition_id: UUID) -> None:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_PUBLIC_RELEASE_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError


def _geometry(
    organization_id: UUID, edition_id: UUID, manifest: ProgrammeReleaseManifest
) -> tuple[PublicReleaseOccurrenceReference, ...]:
    if manifest.state is not ProgrammeReleaseState.AVAILABLE:
        return ()
    selections = {row.placement_id: row for row in manifest.selections}
    rows = tuple(
        SchedulingPlacementRevision.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=selections,
            occurrence_revision__organization_id=organization_id,
            occurrence_revision__edition_id=edition_id,
            occurrence_revision__occurrence__organization_id=organization_id,
            occurrence_revision__occurrence__edition_id=edition_id,
            day_revision__organization_id=organization_id,
            day_revision__edition_id=edition_id,
        )
        .order_by("effective_starts_at", "occurrence_revision__occurrence_id")
        .values_list(
            "id",
            "occurrence_revision__occurrence_id",
            "occurrence_revision__occurrence__programme_item_id",
            "space_selection_id",
            "day_revision__day_id",
            "day_revision__starts_at",
            "day_revision__ends_at",
            "effective_starts_at",
            "effective_ends_at",
        )[: MAX_OCCURRENCES + 1]
    )
    if not 1 <= len(rows) == len(selections) <= MAX_OCCURRENCES:
        raise SchedulingUnavailableError
    projected = []
    for placement, occurrence, item, space, day, day_start, day_end, start, end in rows:
        selected = selections[placement]
        if (
            selected.occurrence_id != occurrence
            or not day_start <= start < end <= day_end
        ):
            raise SchedulingUnavailableError
        projected.append(
            PublicReleaseOccurrenceReference(
                occurrence,
                item,
                selected.public_rendition_id,
                space,
                day,
                day_start,
                day_end,
                start,
                end,
            )
        )
    return tuple(projected)


def load_public_release_reference(
    *, organization_id: UUID, edition_id: UUID
) -> PublicReleaseReference:
    """Resolve one current public-admitted release without organizer authority.

    Parameters
    ----------
    organization_id : UUID
        Exact expected owner, independently resolved before any release lookup.
    edition_id : UUID
        Exact edition; no arbitrary historical release or candidate is accepted.

    Returns
    -------
    PublicReleaseReference
        Complete point-in-time internal references, never public content or a
        reusable permission token. Withdrawn/invalidated states contain no rows.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If exact scope or current profile does not admit this public adapter.
    SchedulingUnavailableError
        If source evidence is missing, moving, oversized or unavailable.

    Notes
    -----
    Identifier validation propagates ValidationError for malformed typed scope.
    Owner public-copy and room-label queries call this boundary themselves.
    The compositor keeps an outer transaction and repeats the reference after
    all owner reads. Shared parents precede any person or owner locks. Native
    disclosure invalidation remains mandatory, including for past occurrences.
    No anonymous activity is audited and no fictitious account is constructed.
    """
    require_identifier(organization_id)
    require_identifier(edition_id)
    try:
        with transaction.atomic():
            _admit(organization_id, edition_id)
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise SchedulingAuthorizationDeniedError
            _admit(organization_id, edition_id)
            edition = resolve_scheduling_edition_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if edition is None:
                raise SchedulingAuthorizationDeniedError
            manifest = _manifest(
                organization_id=organization_id, edition_id=edition_id, release_id=None
            )
            occurrences = _geometry(organization_id, edition_id, manifest)
            published_at = None
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
            _admit(organization_id, edition_id)
            if (
                _manifest(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    release_id=None,
                )
                != manifest
            ):
                raise SchedulingUnavailableError
            return PublicReleaseReference(
                manifest, edition.zone_name, published_at, occurrences
            )
    except DatabaseError as error:
        raise SchedulingUnavailableError from error
