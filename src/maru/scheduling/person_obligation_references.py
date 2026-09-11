"""Owner-only minimized published-host seam for already authorized person work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

from django.db import connection

from .command_support import SchedulingUnavailableError
from .inputs import require_identifier

if TYPE_CHECKING:
    from uuid import UUID

_SHA256_LENGTH: Final = 64


@dataclass(frozen=True, slots=True)
class PublishedPersonConflictReference:
    """Only conflict consequences and opaque source freshness, never calendars.

    Attributes
    ----------
    overlap
        Whether the selected work overlaps an operative published host interval.
    rest
        Whether the selected work's retained rest overlaps published hosting.
    evidence_digest
        Exact retained publication/pointer/host-version fingerprint. It detects
        intervening publish/withdraw history even if current visible work matches.
    """

    overlap: bool
    rest: bool
    evidence_digest: str


def resolve_published_person_conflict(  # noqa: DOC503 - Identifier validator propagates ValidationError.
    *,
    account_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    rest_ends_at: datetime,
    replaced_edition_id: UUID | None = None,
) -> PublishedPersonConflictReference:
    """Check native operative hosting for an owner-resolved person and work interval.

    Parameters
    ----------
    account_id : UUID
        Exact person discovered and authorized by the calling work owner.
    starts_at : datetime
        Inclusive owner-resolved work or host-presence start.
    ends_at : datetime
        Exclusive owner-resolved work or host-presence end.
    rest_ends_at : datetime
        Retained work-rest end; hosting invents no additional rest.
    replaced_edition_id : UUID | None, default=None
        Only Scheduling's authorized candidate composer excludes its own edition
        whose whole release would be replaced. Workforce claims must omit this.

    Returns
    -------
    PublishedPersonConflictReference
        Bounded current consequence and opaque historical source fingerprint.

    Raises
    ------
    SchedulingUnavailableError
        If no owning transaction, valid aware interval or complete source is available.
    ValidationError
        If trusted identifiers are malformed, from the shared identifier validator.

    Notes
    -----
    Not an HTTP/API or user-calendar query. The caller owns authorization and audit,
    and must hold the exact account lock when making a mutation decision. This seam
    acquires no foreign edition or person locks. Safety invalidation, copy/privacy
    sharing changes and room closure do not silently cancel a confirmed host's time;
    host relationship exit or deliberate release replacement/withdrawal does.
    """
    if not connection.in_atomic_block:
        raise SchedulingUnavailableError
    require_identifier(account_id)
    if replaced_edition_id is not None:
        require_identifier(replaced_edition_id)
    if (
        any(
            type(value) is not datetime or value.utcoffset() is None
            for value in (starts_at, ends_at, rest_ends_at)
        )
        or not starts_at < ends_at <= rest_ends_at
    ):
        raise SchedulingUnavailableError
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.maru_scheduling_published_person_conflict"
            "(%s, %s, %s, %s, %s)",
            [account_id, starts_at, ends_at, rest_ends_at, replaced_edition_id],
        )
        row = cursor.fetchone()
    if (
        row is None
        or type(row[0]) is not bool
        or type(row[1]) is not bool
        or type(row[2]) is not str
        or len(row[2]) != _SHA256_LENGTH
    ):
        raise SchedulingUnavailableError
    return PublishedPersonConflictReference(*row)
