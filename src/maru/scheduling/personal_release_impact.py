"""Exact-self approved-presence changes, never filtered planner history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.programme.timetable_queries import load_personal_host_purposes

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HOST_SELF
from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .models import SchedulingRelease
from .personal_release_references import _presences
from .planning_queries import SchedulingReadRequest, _read
from .release_impact import ReleaseSelectionChangeKind
from .release_queries import ProgrammeReleaseState, _manifest

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.timetable_queries import PersonalHostPurpose

    from .personal_release_references import PersonalHostPresence
    from .release_queries import ProgrammeReleaseManifest


@dataclass(frozen=True, slots=True)
class PersonalHostPresenceChange:
    """One own-purpose transition with current relationship and immutable sources.

    Attributes
    ----------
    host_id
        Current person's confirmed relationship, not another host's identity.
    host_version
        Current Programme relationship version at this observation.
    invitation_sequence
        Current deliberate invitation sequence, not timetable approval.
    occurrence_id
        Stable occurrence used with host_id as the comparison identity.
    kind
        Addition, removal, change or no change to own approved presence.
    before
        Earlier own approved presence, absent only for a real addition.
    after
        Current own approved presence, absent only for a real removal.
    changed_fields
        Closed independently changed reference, day, room, own-time or phase
        names. Copy reference change grants no permission to display its text.
    """

    host_id: UUID
    host_version: int
    invitation_sequence: int
    occurrence_id: UUID
    kind: ReleaseSelectionChangeKind
    before: PersonalHostPresence | None
    after: PersonalHostPresence | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonalHostReleaseImpact:
    """Active own-host transition, not a recipient or acknowledgement receipt.

    Attributes
    ----------
    state
        Current active-release state; None means no confirmed own purpose and
        no authorized release lookup, not absence of a published timetable.
    pointer_version
        Observed current publication/withdrawal sequence, or None without purpose.
    release_id
        Exact active release if present and lookup was authorized.
    previous_release_id
        Active publication's retained predecessor, never caller-selected history.
    previous_state
        Checked predecessor state, absent for first publication, or None when
        no current available publication permits a comparison lookup.
    changes
        Complete own-presence union; None means comparison unavailable by state
        or purpose. Empty means an available comparison has no own presences.
    """

    state: ProgrammeReleaseState | None
    pointer_version: int | None
    release_id: UUID | None
    previous_release_id: UUID | None
    previous_state: ProgrammeReleaseState | None
    changes: tuple[PersonalHostPresenceChange, ...] | None


def _fields(
    before: PersonalHostPresence, after: PersonalHostPresence, *, copy_changed: bool
) -> tuple[str, ...]:
    return (
        tuple(
            name
            for name in (
                "placement_id",
                "space_id",
                "day_id",
                "day_starts_at",
                "day_ends_at",
                "starts_at",
                "ends_at",
            )
            if getattr(before, name) != getattr(after, name)
        )
        + tuple(
            name
            for name in (
                "setup_starts_at",
                "effective_starts_at",
                "effective_ends_at",
                "teardown_ends_at",
            )
            if getattr(before.envelope, name) != getattr(after.envelope, name)
        )
        + (("public_rendition_id",) if copy_changed else ())
    )


def _compare(
    confirmed: dict[UUID, PersonalHostPurpose],
    before: tuple[PersonalHostPresence, ...],
    after: tuple[PersonalHostPresence, ...],
    prior_manifest: ProgrammeReleaseManifest | None,
    current_manifest: ProgrammeReleaseManifest,
) -> tuple[PersonalHostPresenceChange, ...]:
    prior = {(row.host_id, row.occurrence_id): row for row in before}
    current = {(row.host_id, row.occurrence_id): row for row in after}
    if (
        len(prior) != len(before)
        or len(current) != len(after)
        or max(len(prior), len(current)) > MAX_OCCURRENCES
        or any(host not in confirmed for host, _ in prior.keys() | current.keys())
    ):
        raise SchedulingUnavailableError
    copies_before = (
        {
            row.occurrence_id: row.public_rendition_id
            for row in prior_manifest.selections
        }
        if prior_manifest is not None
        else {}
    )
    copies_after = {
        row.occurrence_id: row.public_rendition_id
        for row in current_manifest.selections
    }
    if any(occurrence not in copies_before for _, occurrence in prior) or any(
        occurrence not in copies_after for _, occurrence in current
    ):
        raise SchedulingUnavailableError
    result = []
    for host, occurrence in sorted(prior.keys() | current.keys()):
        old = prior.get((host, occurrence))
        new = current.get((host, occurrence))
        fields = (
            _fields(
                old,
                new,
                copy_changed=copies_before[occurrence] != copies_after[occurrence],
            )
            if old is not None and new is not None
            else ()
        )
        kind = (
            ReleaseSelectionChangeKind.ADDED
            if old is None
            else ReleaseSelectionChangeKind.REMOVED
            if new is None
            else ReleaseSelectionChangeKind.CHANGED
            if fields
            else ReleaseSelectionChangeKind.UNCHANGED
        )
        purpose = confirmed[host]
        result.append(
            PersonalHostPresenceChange(
                host,
                purpose.version,
                purpose.invitation_sequence,
                occurrence,
                kind,
                old,
                new,
                fields,
            )
        )
    return tuple(result)


def _load(request: SchedulingReadRequest) -> PersonalHostReleaseImpact:
    arguments = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "correlation_id": request.correlation_id,
    }
    purposes = load_personal_host_purposes(**arguments, purpose="timetable")
    confirmed = {row.host_id: row for row in purposes if row.state == "confirmed"}
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    current = _manifest(**ownership, release_id=None) if confirmed else None
    previous = None
    previous_id = None
    changes = None
    if current is not None and current.state is ProgrammeReleaseState.AVAILABLE:
        if current.release_id is None or not current.is_active:
            raise SchedulingUnavailableError
        release = (
            SchedulingRelease.objects.filter(**ownership, id=current.release_id)
            .only("id", "previous_release_id", "pointer_version")
            .first()
        )
        if release is None or release.pointer_version != current.pointer_version:
            raise SchedulingUnavailableError
        previous_id = release.previous_release_id
        previous = (
            _manifest(**ownership, release_id=previous_id)
            if previous_id is not None
            else None
        )
        if previous is not None and previous.pointer_version != current.pointer_version:
            raise SchedulingUnavailableError
        if previous is None or previous.state is ProgrammeReleaseState.AVAILABLE:
            before = (
                _presences(request, previous, confirmed) if previous is not None else ()
            )
            after = _presences(request, current, confirmed)
            changes = _compare(confirmed, before, after, previous, current)
    if load_personal_host_purposes(**arguments, purpose="timetable") != purposes:
        raise SchedulingUnavailableError
    if (
        previous is not None
        and _manifest(**ownership, release_id=previous_id) != previous
    ):
        raise SchedulingUnavailableError
    if current is not None and _manifest(**ownership, release_id=None) != current:
        raise SchedulingUnavailableError
    return PersonalHostReleaseImpact(
        current.state if current else None,
        current.pointer_version if current else None,
        current.release_id if current else None,
        previous_id,
        previous.state
        if previous
        else (
            ProgrammeReleaseState.ABSENT
            if current is not None and current.state is ProgrammeReleaseState.AVAILABLE
            else None
        ),
        changes,
    )


def load_personal_host_release_impact(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> PersonalHostReleaseImpact:
    """Compare current and predecessor own presence under independent real self policy.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated exact person; no other recipient selector exists.
    organization_id : UUID
        Exact tenant independently checked by Programme and Scheduling.
    edition_id : UUID
        Exact edition admitting both dormant self-service capability contracts.
    correlation_id : UUID
        Trusted trace for mandatory sensitive-read evidence in both owners.

    Returns
    -------
    PersonalHostReleaseImpact
        Complete own-purpose comparison or explicit purpose/state suppression.

    Notes
    -----
    Real owner self authority precedes release lookup, with no planner/history
    grant or authorizer injection. Canonical parents, repeated owner purposes and
    native manifests, final Scheduling authority and required audit fence every
    disclosure. Denied, missing, oversized or moving sources fail closed. This
    read does not deliver, acknowledge or change work; no withdrawn selection,
    other host, private copy, contact, availability or Workforce work is returned.
    """
    request = SchedulingReadRequest(
        actor_id, organization_id, edition_id, correlation_id
    )
    return _read(
        request,
        capability=VIEW_HOST_SELF,
        fields=frozenset({"own_host_schedule"}),
        purpose="personal_host_release_impact",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=lambda _scope: _load(request),
    )
