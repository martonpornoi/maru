"""Minimized exact-person host purposes for independently composed timetables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models import F

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_HOST_SELF,
    authorize_programme_scope,
)
from .models import ProgrammeHostInvitation, ProgrammeHostRelationship
from .queries import ProgrammeQueryUnavailableError, _authorized_query

MAX_PERSONAL_HOST_PURPOSES: Final = 2000
_FIELDS: Final = frozenset({"own_host_relationship", "own_host_invitation"})


@dataclass(frozen=True, slots=True)
class PersonalHostPurpose:
    """One retained own relationship and its exact deliberate invitation copy.

    Attributes
    ----------
    host_id
        Stable relationship identity, never another person's roster entry.
    item_id
        Exact purpose identity for an independently authorized schedule lookup.
    role
        Current host or co-host role.
    state
        Retained invitation/confirmation lifecycle; pending is not accepted work.
    version
        Current relationship source version.
    invitation_sequence
        Exact immutable invitation selected by the current relationship.
    title
        Deliberately host-visible invitation title, not working or public copy.
    briefing
        Deliberately host-visible briefing, not private organizer rationale.
    """

    host_id: UUID
    item_id: UUID
    role: str
    state: str
    version: int
    invitation_sequence: int
    title: str
    briefing: str


def _purposes(
    actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> tuple[PersonalHostPurpose, ...]:
    owned = ProgrammeHostRelationship.objects.filter(
        organization_id=organization_id, edition_id=edition_id, account_id=actor_id
    )
    identifiers = tuple(
        owned.order_by("id").values_list("id", flat=True)[
            : MAX_PERSONAL_HOST_PURPOSES + 1
        ]
    )
    if len(identifiers) > MAX_PERSONAL_HOST_PURPOSES:
        raise ProgrammeQueryUnavailableError
    rows = tuple(
        owned.filter(
            id__in=identifiers,
            item__organization_id=organization_id,
            item__edition_id=edition_id,
        )
        .order_by("item_id", "id")
        .values_list("id", "item_id", "role", "state", "version", "invitation_sequence")
    )
    invitations = tuple(
        ProgrammeHostInvitation.objects.filter(
            host_id__in=identifiers,
            organization_id=organization_id,
            edition_id=edition_id,
            host__organization_id=organization_id,
            host__edition_id=edition_id,
            host__account_id=actor_id,
            item_id=F("host__item_id"),
            sequence=F("host__invitation_sequence"),
            role=F("host__role"),
        ).values_list("host_id", "title", "briefing")[: MAX_PERSONAL_HOST_PURPOSES + 1]
    )
    copies = {host_id: (title, briefing) for host_id, title, briefing in invitations}
    if (
        len(rows) != len(identifiers)
        or len(invitations) != len(identifiers)
        or set(copies) != set(identifiers)
    ):
        raise ProgrammeQueryUnavailableError
    return tuple(PersonalHostPurpose(*row, *copies[row[0]]) for row in rows)


def load_personal_host_purposes(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> tuple[PersonalHostPurpose, ...]:
    """Read the current person's complete retained purposes under real self policy.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated person; no independently selectable subject exists.
    organization_id : UUID
        Exact expected owner of relationships and invitation copy.
    edition_id : UUID
        Exact edition whose current profile must admit the host-self capability.
    correlation_id : UUID
        Trusted identifier for the mandatory sensitive-read evidence.

    Returns
    -------
    tuple[PersonalHostPurpose, ...]
        Complete, bounded own purposes in stable item/relationship order. An
        empty result means no retained own host purpose, not an empty roster.

    Raises
    ------
    ProgrammeQueryUnavailableError
        If owner evidence is missing, inconsistent, over-bound or unavailable.
    ValidationError
        If trusted routing identifiers are malformed.

    Notes
    -----
    The authorization boundary propagates ProgrammeAuthorizationDeniedError
    when exact-self, profile, scope or independently required field authority fails.
    Canonical parent and actor locks precede owner reads; final authorization
    and required audit precede disclosure. No availability periods, other host,
    private item copy, public rendition, reviewer or organizer reason is fetched.
    Invitation copy is not a published title or approval of a schedule. Retained
    declined/removed purposes are history, not work or attendance. Only a separate
    checked schedule query may assign released times to confirmed host purposes.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise ValidationError(
            "Exact typed personal timetable identifiers are required."
        )

    def load() -> tuple[PersonalHostPurpose, ...]:
        authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_VIEW_HOST_SELF,
            requested_fields=_FIELDS,
            lock=True,
        )
        return _purposes(actor_id, organization_id, edition_id)

    try:
        return _authorized_query(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_VIEW_HOST_SELF,
            requested_fields=_FIELDS,
            operation="programme.query.personal_host_timetable",
            loader=load,
            target_type="events.event_edition",
            target_id=edition_id,
            target_count=len,
            reason="Own retained host timetable purposes",
            correlation_id=correlation_id,
            source_channel="programme-timetable",
            authorizer=DEFAULT_PROGRAMME_AUTHORIZER,
        )
    except DatabaseError as error:
        raise ProgrammeQueryUnavailableError from error
