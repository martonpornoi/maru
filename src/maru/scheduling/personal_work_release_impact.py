"""Own operative Workforce context in exact releases, never a Shift reschedule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.workforce.personal_programme_links import load_personal_programme_work_links

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_WORK_SELF
from .command_support import SchedulingUnavailableError
from .models import SchedulingRelease
from .planning_queries import SchedulingReadRequest, _read
from .release_impact import ReleaseSelectionChangeKind, compare_release_selections
from .release_impact_queries import _changed_geometry, _geometry
from .release_queries import ProgrammeReleaseState, _manifest

if TYPE_CHECKING:
    from uuid import UUID

    from maru.workforce.personal_programme_links import PersonalProgrammeWorkLink

    from .release_impact_queries import ReleasedChangeGeometry


@dataclass(frozen=True, slots=True)
class PersonalWorkOccurrenceChange:
    """Released context change for one independently proven own operative commitment.

    Attributes
    ----------
    work
        Current own claim/confirmation and retained binding identity/versions.
        None of these fields replaces or confirms retained accepted work times.
    kind
        Occurrence addition/removal/change in the release, not work cancellation.
    before
        Earlier exact published context, absent only for an occurrence addition.
    after
        Current published context, absent only for an occurrence removal.
    changed_fields
        Closed changed placement/copy references and actual day/room/phase names.
        Copy flags carry no text authority and phase changes assign no new work.
    """

    work: PersonalProgrammeWorkLink
    kind: ReleaseSelectionChangeKind
    before: ReleasedChangeGeometry | None
    after: ReleasedChangeGeometry | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonalWorkReleaseImpact:
    """Active release transition for own linked work, with explicit missing purpose.

    Attributes
    ----------
    state
        Checked current release state; None means no operative own Programme work
        and no release lookup, not absence of a published timetable.
    pointer_version
        Current publication/withdrawal sequence, or None without own purpose.
    release_id
        Exact active release where present and lookup was justified.
    previous_release_id
        Its retained immediate predecessor, never a caller-selected historical ID.
    previous_state
        Checked predecessor state, absent on first publication, otherwise None
        where current state or own purpose prevents comparison.
    changes
        Complete own operative-work comparison or None on purpose/state suppression.
        Empty means no linked occurrence appears in either available release.
    """

    state: ProgrammeReleaseState | None
    pointer_version: int | None
    release_id: UUID | None
    previous_release_id: UUID | None
    previous_state: ProgrammeReleaseState | None
    changes: tuple[PersonalWorkOccurrenceChange, ...] | None


def _load(request: SchedulingReadRequest) -> PersonalWorkReleaseImpact:
    arguments = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "correlation_id": request.correlation_id,
    }
    links = load_personal_programme_work_links(**arguments)
    if links is None:
        # Scheduling work context without its owner adapter is partial adoption.
        raise SchedulingUnavailableError
    operative = tuple(link for link in links if link.status in {"claimed", "confirmed"})
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    current = _manifest(**ownership, release_id=None) if operative else None
    previous_id = None
    previous = None
    changes = None
    if current is not None and current.state is ProgrammeReleaseState.AVAILABLE:
        if current.release_id is None or not current.is_active:
            raise SchedulingUnavailableError
        release = (
            SchedulingRelease.objects.filter(
                **ownership,
                id=current.release_id,
            )
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
            selected = {link.occurrence_id for link in operative}
            prior = (
                _geometry(request, previous, occurrence_ids=selected)
                if previous
                else {}
            )
            after = _geometry(request, current, occurrence_ids=selected)
            differences = compare_release_selections(
                before=previous.selections if previous else (),
                after=current.selections,
            )
            comparison = {row.occurrence_id: row for row in differences.changes}
            changes = tuple(
                PersonalWorkOccurrenceChange(
                    link,
                    comparison[link.occurrence_id].kind,
                    prior.get(link.occurrence_id),
                    after.get(link.occurrence_id),
                    comparison[link.occurrence_id].changed_fields
                    + _changed_geometry(
                        prior.get(link.occurrence_id),
                        after.get(link.occurrence_id),
                    ),
                )
                for link in operative
                if link.occurrence_id in comparison
            )
    if load_personal_programme_work_links(**arguments) != links:
        raise SchedulingUnavailableError
    if (
        previous is not None
        and _manifest(**ownership, release_id=previous_id) != previous
    ):
        raise SchedulingUnavailableError
    if current is not None and _manifest(**ownership, release_id=None) != current:
        raise SchedulingUnavailableError
    return PersonalWorkReleaseImpact(
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


def load_personal_work_release_impact(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> PersonalWorkReleaseImpact:
    """Compare own linked work context under independent real Scheduling self policy.

    Parameters
    ----------
    actor_id : UUID
        Trusted current authenticated person, never a caller-selected recipient.
    organization_id : UUID
        Exact expected tenant, independently rechecked by Workforce.
    edition_id : UUID
        Exact edition admitting both owner contracts; no attendee system is used.
    correlation_id : UUID
        Trusted trace for mandatory owner sensitive-read audits.

    Returns
    -------
    PersonalWorkReleaseImpact
        Minimized release context changes, not amended or newly accepted Shifts.

    Notes
    -----
    Real Scheduling work-self and Workforce self authority are independent.
    Only own retained claimed/confirmed Programme-linked commitments justify
    release lookup; ended/unlinked work grants no schedule discovery. Each side
    selects only their occurrences after full native manifest verification.
    Repeated owner links, release checks, final authority and mandatory audit
    fence disclosure. No other work/person, private copy, host, availability,
    candidate, history selector or authorizer substitute is exposed. Comparison
    never cancels, retimes, relocates, confirms, delivers or acknowledges work.
    """
    request = SchedulingReadRequest(
        actor_id, organization_id, edition_id, correlation_id
    )
    return _read(
        request,
        capability=VIEW_WORK_SELF,
        fields=frozenset({"own_work_schedule"}),
        purpose="personal_work_release_impact",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=lambda _scope: _load(request),
    )
