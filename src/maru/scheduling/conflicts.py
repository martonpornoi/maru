"""Pure explainable current-dependency checks, never a release or reservation."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.programme.adoption import PROGRAMME_SCHEDULING_CONFLICT_SOURCE
from maru.venues.adoption import VENUES_SCHEDULING_CONFLICT_SOURCE

from .adoption import SCHEDULING_TIME_CONFLICT_SOURCE
from .catalogs import MAX_CONFLICT_COMPARISONS, MAX_CONFLICTS, MAX_OCCURRENCES
from .catalogs import SchedulingConflictCode as Code
from .catalogs import SchedulingConflictSeverity as Severity
from .time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
    permitted_turnover_window,
    placement_fits_service_day,
    room_envelopes_conflict,
    scheduling_windows_overlap,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from maru.programme.scheduling_queries import (
        ProgrammeSchedulingHost,
        ProgrammeSchedulingSnapshot,
    )
    from maru.venues.scheduling_queries import (
        VenueSchedulingSnapshot,
        VenueSchedulingSpace,
    )


@dataclass(frozen=True, slots=True)
class SchedulingOccurrenceFacts:
    """Owned current identity compared with the immutable selected metadata revision.

    Attributes
    ----------
    id
        Stable Scheduling occurrence.
    item_id
        Immutable Programme source identity.
    selected_version
        Occurrence revision retained by the placement.
    current_version
        Current occurrence metadata version.
    active
        Whether the current occurrence remains active.
    """

    id: UUID
    item_id: UUID
    selected_version: int
    current_version: int
    active: bool


@dataclass(frozen=True, slots=True)
class SchedulingDayFacts:
    """Selected day window and grid with current metadata freshness.

    Attributes
    ----------
    id
        Stable explicit service day.
    selected_version
        Day revision retained by the placement.
    current_version
        Current day metadata version.
    active
        Whether the current day remains active.
    window
        Selected immutable day window, not silently substituted current intent.
    precision_minutes
        Grid precision of that selected day revision.
    """

    id: UUID
    selected_version: int
    current_version: int
    active: bool
    window: SchedulingWindow
    precision_minutes: int


@dataclass(frozen=True, slots=True)
class SchedulingPlacementFacts:
    """Exact private placement input to a pure evaluation, not caller authority.

    Attributes
    ----------
    id
        Immutable Scheduling placement revision.
    occurrence
        Owned source identity and current metadata consequence.
    day
        Explicit selected day window and current version consequence.
    space_id
        Exact selected physical dependency to find in the Venue owner result.
    envelope
        Complete proposed room preparation/effective/teardown envelope.
    capacity_mode
        Explicit requested seated, standing or table configuration.
    expected_attendance
        Positive explicit planning estimate, not an attendee count.
    hosts
        Explicit required presence intervals, never supplied personal availability.
    own_booking_id
        Exact matching live booking proven by a future binding query, otherwise none.
        Pure evaluation cannot establish or accept authorization for this identity.
    """

    id: UUID
    occurrence: SchedulingOccurrenceFacts
    day: SchedulingDayFacts
    space_id: UUID
    envelope: SchedulingEnvelope
    capacity_mode: str
    expected_attendance: int
    hosts: tuple[SchedulingHostPresence, ...]
    own_booking_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SchedulingFinding:
    """One closed outcome without private source content or copied calendars.

    Attributes
    ----------
    source_code
        Exact owning conflict-source descriptor.
    code
        Closed explainable finding code.
    severity
        Hard blocker, reason-acknowledgeable warning or unavailable check.
    occurrence_id
        Exact affected occurrence, or none for a complete-source failure.
    other_occurrence_id
        Optional conflicting occurrence inside this same candidate.
    """

    source_code: str
    code: Code
    severity: Severity
    occurrence_id: UUID | None = None
    other_occurrence_id: UUID | None = None


class _FindingLimitError(Exception):
    pass


class _Findings:
    def __init__(self) -> None:
        self.values: set[SchedulingFinding] = set()
        self.comparisons = 0

    def compare(self) -> None:
        self.comparisons += 1
        if self.comparisons > MAX_CONFLICT_COMPARISONS:
            raise _FindingLimitError

    def add(
        self,
        source: str,
        code: Code,
        severity: Severity,
        occurrence_id: UUID | None = None,
        other_id: UUID | None = None,
    ) -> None:
        if occurrence_id is not None and other_id is not None:
            occurrence_id, other_id = sorted((occurrence_id, other_id), key=str)
        self.values.add(
            SchedulingFinding(source, code, severity, occurrence_id, other_id)
        )
        if len(self.values) > MAX_CONFLICTS:
            raise _FindingLimitError


def _covered(window: SchedulingWindow, periods: Iterable[SchedulingWindow]) -> bool:
    cursor = window.starts_at
    for period in sorted(periods, key=lambda value: value.starts_at):
        if period.ends_at <= cursor:
            continue
        if period.starts_at > cursor:
            return False
        cursor = period.ends_at
        if cursor >= window.ends_at:
            return True
    return False


def _time_findings(
    placement: SchedulingPlacementFacts,
    edition: SchedulingWindow | None,
    findings: _Findings,
) -> None:
    occurrence, day, envelope = placement.occurrence, placement.day, placement.envelope
    source = SCHEDULING_TIME_CONFLICT_SOURCE
    if not occurrence.active:
        findings.add(source, Code.OCCURRENCE_RETIRED, Severity.BLOCKER, occurrence.id)
    if occurrence.selected_version != occurrence.current_version:
        findings.add(source, Code.OCCURRENCE_CHANGED, Severity.BLOCKER, occurrence.id)
    if not day.active:
        findings.add(source, Code.DAY_RETIRED, Severity.BLOCKER, occurrence.id)
    if day.selected_version != day.current_version:
        findings.add(source, Code.DAY_CHANGED, Severity.BLOCKER, occurrence.id)
    if edition is not None and (
        not edition.starts_at
        <= envelope.setup_starts_at
        < envelope.teardown_ends_at
        <= edition.ends_at
        or not edition.starts_at
        <= day.window.starts_at
        < day.window.ends_at
        <= edition.ends_at
    ):
        findings.add(source, Code.EDITION_BOUNDS, Severity.BLOCKER, occurrence.id)
    if (
        not day.window.starts_at
        <= envelope.setup_starts_at
        < envelope.teardown_ends_at
        <= day.window.ends_at
    ):
        findings.add(source, Code.DAY_BOUNDS, Severity.BLOCKER, occurrence.id)
    elif not placement_fits_service_day(
        envelope, window=day.window, precision_minutes=day.precision_minutes
    ):
        findings.add(source, Code.MINUTE_GRID, Severity.BLOCKER, occurrence.id)


def _host_findings(
    placement: SchedulingPlacementFacts,
    presence: SchedulingHostPresence,
    host: ProgrammeSchedulingHost | None,
    findings: _Findings,
) -> None:
    source, occurrence = PROGRAMME_SCHEDULING_CONFLICT_SOURCE, placement.occurrence
    if host is None or host.item_id != occurrence.item_id:
        findings.add(
            source, Code.HOST_SOURCE_UNAVAILABLE, Severity.UNAVAILABLE, occurrence.id
        )
        return
    if host.status in {"ended", "inactive", "unconfirmed"}:
        findings.add(source, Code.HOST_NOT_CURRENT, Severity.BLOCKER, occurrence.id)
    elif host.status == "unavailable":
        findings.add(source, Code.HOST_UNAVAILABLE, Severity.BLOCKER, occurrence.id)
    elif host.status != "shared" or host.person_key is None:
        findings.add(
            source, Code.HOST_SOURCE_UNAVAILABLE, Severity.UNAVAILABLE, occurrence.id
        )
    else:
        required = SchedulingWindow(presence.starts_at, presence.ends_at)
        if not _covered(
            required, (SchedulingWindow(p.starts_at, p.ends_at) for p in host.periods)
        ):
            findings.add(
                source, Code.HOST_OUTSIDE_AVAILABILITY, Severity.BLOCKER, occurrence.id
            )
        else:
            preferred = tuple(
                SchedulingWindow(p.starts_at, p.ends_at)
                for p in host.periods
                if p.kind == "preferred"
            )
            if preferred and not _covered(required, preferred):
                findings.add(
                    source,
                    Code.HOST_OUTSIDE_PREFERENCE,
                    Severity.WARNING,
                    occurrence.id,
                )


def _programme_findings(
    placements: tuple[SchedulingPlacementFacts, ...],
    programme: ProgrammeSchedulingSnapshot | None,
    findings: _Findings,
) -> None:
    source = PROGRAMME_SCHEDULING_CONFLICT_SOURCE
    if programme is None or programme.contract != source:
        findings.add(source, Code.PROGRAMME_UNAVAILABLE, Severity.UNAVAILABLE)
        return
    items = {item.item_id: item for item in programme.items}
    hosts = {host.host_id: host for host in programme.hosts}
    people: dict[UUID, list[tuple[UUID, SchedulingWindow]]] = {}
    for placement in placements:
        item = items.get(placement.occurrence.item_id)
        if item is None:
            findings.add(
                source,
                Code.PROGRAMME_UNAVAILABLE,
                Severity.UNAVAILABLE,
                placement.occurrence.id,
            )
            continue
        if item.lifecycle != "active":
            findings.add(
                source, Code.ITEM_RETIRED, Severity.BLOCKER, placement.occurrence.id
            )
        if item.hosting_required and not placement.hosts:
            findings.add(
                source, Code.HOST_REQUIRED, Severity.BLOCKER, placement.occurrence.id
            )
        for presence in placement.hosts:
            host = hosts.get(presence.host_id)
            _host_findings(placement, presence, host, findings)
            if (
                host is not None
                and host.item_id == placement.occurrence.item_id
                and host.person_key is not None
            ):
                people.setdefault(host.person_key, []).append(
                    (
                        placement.occurrence.id,
                        SchedulingWindow(presence.starts_at, presence.ends_at),
                    )
                )
    for commitments in people.values():
        ordered = sorted(commitments, key=lambda value: value[1].starts_at)
        for index, (left, left_window) in enumerate(ordered):
            for right, right_window in islice(ordered, index + 1, None):
                if right_window.starts_at >= left_window.ends_at:
                    break
                findings.compare()
                if left != right:
                    findings.add(
                        source, Code.HOST_OVERLAP, Severity.BLOCKER, left, right
                    )


def _space_findings(
    placement: SchedulingPlacementFacts,
    space: VenueSchedulingSpace,
    findings: _Findings,
) -> None:
    source, occurrence = VENUES_SCHEDULING_CONFLICT_SOURCE, placement.occurrence.id
    if not space.active:
        findings.add(source, Code.VENUE_INACTIVE, Severity.BLOCKER, occurrence)
    limit = {
        "seated": space.seated_capacity,
        "standing": space.standing_capacity,
        "table": space.table_capacity,
    }.get(placement.capacity_mode, 0)
    if placement.expected_attendance > min(limit, space.fire_capacity):
        findings.add(source, Code.VENUE_CAPACITY, Severity.BLOCKER, occurrence)
    if space.availability_version < 1:
        findings.add(
            source, Code.VENUE_AVAILABILITY_MISSING, Severity.UNAVAILABLE, occurrence
        )
    elif not any(
        window.starts_at
        <= placement.envelope.setup_starts_at
        < placement.envelope.teardown_ends_at
        <= window.ends_at
        for window in space.windows
    ):
        # The physical owner requires one containing hard window, not a union.
        findings.add(source, Code.VENUE_HARD_AVAILABILITY, Severity.BLOCKER, occurrence)


def _venue_findings(
    placements: tuple[SchedulingPlacementFacts, ...],
    venues: VenueSchedulingSnapshot | None,
    findings: _Findings,
) -> None:
    source = VENUES_SCHEDULING_CONFLICT_SOURCE
    if venues is None or venues.contract != source:
        findings.add(source, Code.VENUE_UNAVAILABLE, Severity.UNAVAILABLE)
        return
    spaces = {space.selection_id: space for space in venues.spaces}
    members: dict[UUID, list[SchedulingPlacementFacts]] = {}
    for placement in placements:
        space = spaces.get(placement.space_id)
        if space is None or not space.member_ids:
            findings.add(
                source,
                Code.VENUE_UNAVAILABLE,
                Severity.UNAVAILABLE,
                placement.occurrence.id,
            )
            continue
        _space_findings(placement, space, findings)
        for member in space.member_ids:
            members.setdefault(member, []).append(placement)
    compared: set[tuple[UUID, UUID]] = set()
    for sharing in members.values():
        ordered = sorted(sharing, key=lambda value: value.envelope.setup_starts_at)
        for index, left in enumerate(ordered):
            for right in islice(ordered, index + 1, None):
                if right.envelope.setup_starts_at >= left.envelope.teardown_ends_at:
                    break
                _candidate_pair(left, right, compared, findings)
    _busy_findings(members, venues, findings)


def _candidate_pair(
    left: SchedulingPlacementFacts,
    right: SchedulingPlacementFacts,
    compared: set[tuple[UUID, UUID]],
    findings: _Findings,
) -> None:
    source = VENUES_SCHEDULING_CONFLICT_SOURCE
    first, second = sorted((left.occurrence.id, right.occurrence.id), key=str)
    pair = (first, second)
    if pair in compared:
        return
    findings.compare()
    compared.add(pair)
    if room_envelopes_conflict(left.envelope, right.envelope):
        findings.add(
            source,
            Code.CANDIDATE_ROOM_OVERLAP,
            Severity.BLOCKER,
            left.occurrence.id,
            right.occurrence.id,
        )
    elif permitted_turnover_window(left.envelope, right.envelope) is not None:
        findings.add(
            source,
            Code.TURNOVER_OVERLAP,
            Severity.WARNING,
            left.occurrence.id,
            right.occurrence.id,
        )


def _busy_findings(
    members: dict[UUID, list[SchedulingPlacementFacts]],
    venues: VenueSchedulingSnapshot,
    findings: _Findings,
) -> None:
    interactions: dict[tuple[UUID, UUID], tuple[bool, bool]] = {}
    source = VENUES_SCHEDULING_CONFLICT_SOURCE
    for busy in venues.busy_periods:
        if busy.conflict_group not in {"setup_effective", "effective_teardown"}:
            findings.add(source, Code.VENUE_UNAVAILABLE, Severity.UNAVAILABLE)
            continue
        for placement in members.get(busy.member_id, ()):
            findings.compare()
            if (
                busy.booking_id is not None
                and busy.booking_id == placement.own_booking_id
            ):
                continue
            envelope = placement.envelope
            clique = (
                SchedulingWindow(envelope.setup_starts_at, envelope.effective_ends_at)
                if busy.conflict_group == "setup_effective"
                else SchedulingWindow(
                    envelope.effective_starts_at, envelope.teardown_ends_at
                )
            )
            blocked = scheduling_windows_overlap(
                clique, SchedulingWindow(busy.window.starts_at, busy.window.ends_at)
            )
            touching = scheduling_windows_overlap(
                SchedulingWindow(envelope.setup_starts_at, envelope.teardown_ends_at),
                SchedulingWindow(busy.window.starts_at, busy.window.ends_at),
            )
            pair = (placement.occurrence.id, busy.source_key)
            previous = interactions.get(pair, (False, False))
            interactions[pair] = (previous[0] or blocked, previous[1] or touching)
    for (occurrence_id, _source_key), (blocked, touching) in interactions.items():
        if blocked:
            findings.add(
                source, Code.RESERVED_ROOM_OVERLAP, Severity.BLOCKER, occurrence_id
            )
        elif touching:
            findings.add(source, Code.TURNOVER_OVERLAP, Severity.WARNING, occurrence_id)


def evaluate_scheduling_facts(
    placements: tuple[SchedulingPlacementFacts, ...],
    *,
    edition: SchedulingWindow | None,
    programme: ProgrammeSchedulingSnapshot | None,
    venues: VenueSchedulingSnapshot | None,
) -> tuple[SchedulingFinding, ...]:
    """Evaluate declared current dependencies without storing personal calendars.

    Inputs are independently owner-resolved facts, not an authorization API.
    Unknown sources and bounded overflow return explicit unavailable findings.
    This evaluates only the declared time, Programme and physical sources; it
    makes no staffing, accessibility-fit, reservation-approval or release claim.

    Parameters
    ----------
    placements : tuple[SchedulingPlacementFacts, ...]
        Complete unique candidate placement facts, bounded to 2000 occurrences.
    edition : SchedulingWindow | None
        Current Events time envelope, or no available owner proof.
    programme : ProgrammeSchedulingSnapshot | None
        Complete current independently authorized item/host source.
    venues : VenueSchedulingSnapshot | None
        Complete current independently authorized physical source.

    Returns
    -------
    tuple[SchedulingFinding, ...]
        Stable deduplicated outcomes, or an explicit complete-evaluation limit failure.

    Raises
    ------
    ValidationError
        If the placement collection is unbounded, duplicated or untyped.
    """
    if (
        not isinstance(placements, tuple)
        or len(placements) > MAX_OCCURRENCES
        or any(not isinstance(value, SchedulingPlacementFacts) for value in placements)
        or len({value.occurrence.id for value in placements}) != len(placements)
    ):
        raise ValidationError(
            "Evaluate one complete bounded unique candidate manifest."
        )
    findings = _Findings()
    try:
        if edition is None:
            findings.add(
                SCHEDULING_TIME_CONFLICT_SOURCE,
                Code.EDITION_UNAVAILABLE,
                Severity.UNAVAILABLE,
            )
        for placement in placements:
            _time_findings(placement, edition, findings)
        _programme_findings(placements, programme, findings)
        _venue_findings(placements, venues, findings)
    except _FindingLimitError:
        return (
            SchedulingFinding(
                SCHEDULING_TIME_CONFLICT_SOURCE,
                Code.EVALUATION_LIMIT,
                Severity.UNAVAILABLE,
            ),
        )
    return tuple(
        sorted(
            findings.values,
            key=lambda finding: (
                finding.source_code,
                finding.code.value,
                str(finding.occurrence_id),
                str(finding.other_occurrence_id),
            ),
        )
    )
