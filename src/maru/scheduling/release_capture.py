"""Private complete owner collection and generation capture for release commands."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from django.db import connection

from maru.identity.queries import lock_account_references_for_evidence
from maru.programme.placement_queries import ProgrammePlacementReadRequest
from maru.programme.release_queries import (
    collect_programme_release_person_references,
    load_programme_release_item_sources,
)
from maru.venues.release_queries import lock_venue_release_sources
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_release_references import (
    collect_programme_release_work_references,
)

from .catalogs import MAX_RELEASE_DEPENDENCY_USES
from .command_support import SchedulingLimitError, SchedulingUnavailableError
from .models import SchedulingReleaseDependencyKey
from .release_artifacts import ReleaseArtifactSelection
from .release_candidate_queries import load_release_candidate_source
from .release_catalogs import ReleaseDependencyKind as Kind
from .release_dependency_rules import ReleaseDependencyHorizon as Horizon
from .release_preflight import load_release_preflight
from .writer_boundary import require_scheduling_writer

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer
    from maru.programme.release_queries import ProgrammeReleasePeople
    from maru.venues.release_queries import VenueReleaseSources
    from maru.workforce.programme_release_references import (
        ProgrammeReleaseWorkReferences,
    )

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest
    from .release_candidate_queries import SchedulingReleaseCandidateSource
    from .release_inputs import ReleaseCandidateSelection
    from .release_preflight import SchedulingReleasePreflight


@dataclass(frozen=True, slots=True)
class _ReleaseDependencyReference:
    kind: Kind
    source_id: UUID
    organization_id: UUID | None
    edition_id: UUID | None
    placement_id: UUID | None
    horizon: Horizon
    operational_ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CapturedReleaseDependency:
    reference: _ReleaseDependencyReference
    dependency_id: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class _ReleaseSources:
    candidate: SchedulingReleaseCandidateSource
    preflight: SchedulingReleasePreflight
    placements: tuple[ReleaseArtifactSelection, ...]
    references: tuple[_ReleaseDependencyReference, ...]


def _reference_order(row: _ReleaseDependencyReference) -> tuple[str, ...]:
    return (
        row.kind.value,
        str(row.source_id),
        str(row.placement_id),
        row.horizon.value,
        row.operational_ends_at.isoformat() if row.operational_ends_at else "",
    )


def _references(
    request: SchedulingReadRequest,
    candidate: SchedulingReleaseCandidateSource,
    people: ProgrammeReleasePeople,
    work: ProgrammeReleaseWorkReferences,
    venues: VenueReleaseSources,
    placements: tuple[ReleaseArtifactSelection, ...],
    approval_actor_id: UUID,
) -> tuple[_ReleaseDependencyReference, ...]:
    references: dict[
        tuple[Kind, UUID, UUID | None, Horizon], _ReleaseDependencyReference
    ] = {}

    def add(
        kind: Kind,
        source_id: UUID,
        *,
        placement_id: UUID | None = None,
        horizon: Horizon = Horizon.APPROVAL_ONLY,
        ends_at: datetime | None = None,
    ) -> None:
        global_source = kind in {
            Kind.IDENTITY_ACCOUNT,
            Kind.WORKFORCE_PERSON_OBLIGATIONS,
        }
        organization_source = kind in {Kind.VENUE_PROPERTY, Kind.VENUE_MEMBER}
        identity = kind, source_id, placement_id, horizon
        prior = references.get(identity)
        if prior and prior.operational_ends_at is not None and ends_at is not None:
            ends_at = max(prior.operational_ends_at, ends_at)
        references[identity] = _ReleaseDependencyReference(
            kind,
            source_id,
            None if global_source else request.organization_id,
            None if global_source or organization_source else request.edition_id,
            placement_id,
            horizon,
            ends_at,
        )
        if len(references) > MAX_RELEASE_DEPENDENCY_USES:
            raise SchedulingLimitError

    for account in {
        *people.source_account_ids,
        approval_actor_id,
        *(row.account_id for row in work.commitments),
    }:
        add(Kind.IDENTITY_ACCOUNT, account)
    for account in {
        *(row.account_id for row in people.selected_hosts),
        *(row.account_id for row in work.commitments),
    }:
        add(Kind.WORKFORCE_PERSON_OBLIGATIONS, account)
    hosts = {row.host_id: row for row in people.selected_hosts}
    spaces = {row.selection_id: row for row in venues.selections}
    reservations = {row.placement_id: row for row in venues.snapshot.reservations}
    copies = {row.placement_id: row.public_rendition_id for row in placements}
    for placement in candidate.placements:
        end = placement.envelope.teardown_ends_at
        operational = partial(
            add, placement_id=placement.id, horizon=Horizon.OPERATIONAL, ends_at=end
        )
        operational(Kind.EDITION_OPERATIONAL, request.edition_id)
        operational(Kind.PROGRAMME_ITEM, placement.occurrence.item_id)
        operational(Kind.VENUE_SELECTION, placement.space_id)
        for member, property_id in spaces[placement.space_id].member_properties:
            operational(Kind.VENUE_PROPERTY, property_id)
            operational(Kind.VENUE_MEMBER, member)
        reservation = reservations.get(placement.id)
        if reservation is None or reservation.occurrence_id != placement.occurrence.id:
            raise SchedulingUnavailableError
        operational(Kind.VENUE_BOOKING, reservation.booking_id)
        add(
            Kind.PROGRAMME_PUBLIC_COPY,
            copies[placement.id],
            placement_id=placement.id,
            horizon=Horizon.DISCLOSURE,
        )
        for presence in placement.hosts:
            host = hosts.get(presence.host_id)
            if host is None or host.item_id != placement.occurrence.item_id:
                raise SchedulingUnavailableError
            operational(
                Kind.PROGRAMME_HOST_OPERATIONAL, host.host_id, ends_at=presence.ends_at
            )
            operational(
                Kind.IDENTITY_ACCOUNT, host.account_id, ends_at=presence.ends_at
            )
            add(
                Kind.PROGRAMME_HOST_DISCLOSURE,
                host.host_id,
                placement_id=placement.id,
                horizon=Horizon.DISCLOSURE,
            )
        demands = {
            identifier
            for identifier, occurrences in work.demand_occurrences
            if placement.occurrence.id in occurrences
        }
        for demand in demands:
            operational(Kind.WORKFORCE_DEMAND, demand)
        for commitment in work.commitments:
            if commitment.demand_id not in demands:
                continue
            for kind, identifier in (
                (Kind.IDENTITY_ACCOUNT, commitment.account_id),
                (Kind.WORKFORCE_ASSIGNMENT, commitment.assignment_id),
                (Kind.WORKFORCE_AVAILABILITY, commitment.availability_plan_id),
            ):
                operational(kind, identifier, ends_at=commitment.ends_at)
    return tuple(sorted(references.values(), key=_reference_order))


def _load_release_sources(
    request: SchedulingReadRequest,
    selection: ReleaseCandidateSelection,
    *,
    approval_actor_id: UUID,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
    retained_person_ids: tuple[UUID, ...] = (),
) -> _ReleaseSources:
    # Private composer only: approval_actor_id must come from this command's
    # admitted actor or an exact already scoped immutable Scheduling approval.
    if not connection.in_atomic_block:
        raise SchedulingUnavailableError
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone() != ("read committed",):
            raise SchedulingUnavailableError
    lock_programme_staffing_scope(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    load_candidate = partial(
        load_release_candidate_source,
        request,
        candidate_id=selection.candidate_id,
        candidate_revision_id=selection.candidate_revision_id,
        expected_candidate_version=selection.expected_candidate_version,
        authorizer=scheduling_authorizer,
    )
    candidate = load_candidate()
    owner_request = ProgrammePlacementReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    )
    item_ids = tuple(sorted({row.occurrence.item_id for row in candidate.placements}))
    load_people = partial(
        collect_programme_release_person_references,
        owner_request,
        item_ids=item_ids,
        host_ids=tuple(
            sorted({host.host_id for row in candidate.placements for host in row.hosts})
        ),
        authorizer=programme_authorizer,
    )
    load_work = partial(
        collect_programme_release_work_references,
        owner_request,
        candidate_id=selection.candidate_id,
        candidate_revision_id=selection.candidate_revision_id,
        expected_candidate_version=selection.expected_candidate_version,
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
    )
    people, work = load_people(), load_work()
    accounts = tuple(
        sorted(
            {
                *people.account_ids,
                approval_actor_id,
                *(row.account_id for row in work.commitments),
                *retained_person_ids,
            }
        )
    )
    if lock_account_references_for_evidence(account_ids=accounts) != accounts:
        raise SchedulingUnavailableError
    if load_people() != people or load_work() != work or load_candidate() != candidate:
        raise SchedulingUnavailableError
    venues = lock_venue_release_sources(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        selection_ids=tuple(sorted({row.space_id for row in candidate.placements})),
        placement_ids=tuple(sorted(row.id for row in candidate.placements)),
        correlation_id=request.correlation_id,
    )
    preflight = load_release_preflight(
        request,
        candidate_id=selection.candidate_id,
        candidate_revision_id=selection.candidate_revision_id,
        expected_candidate_version=selection.expected_candidate_version,
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
    )
    if preflight.snapshot_digest != selection.source_snapshot_digest:
        raise SchedulingUnavailableError
    items = load_programme_release_item_sources(
        owner_request, item_ids=item_ids, authorizer=programme_authorizer
    )
    copies = {row.item_id: row.public_rendition_id for row in items}
    selections = []
    for row in candidate.placements:
        rendition_id = copies.get(row.occurrence.item_id)
        if rendition_id is None:
            raise SchedulingUnavailableError
        selections.append(
            ReleaseArtifactSelection(row.occurrence.id, row.id, rendition_id)
        )
    placements = tuple(selections)
    return _ReleaseSources(
        candidate,
        preflight,
        placements,
        _references(
            request, candidate, people, work, venues, placements, approval_actor_id
        ),
    )


def _capture_release_generations(
    sources: _ReleaseSources,
    *,
    create_missing: bool = True,
) -> tuple[_CapturedReleaseDependency, ...]:
    # Called only by a Scheduling command after complete source/person/physical
    # closure. Every native identity is revalidated by its database source guard.
    require_scheduling_writer()
    if not connection.in_atomic_block:
        raise SchedulingUnavailableError
    keys: dict[tuple[Kind, UUID], SchedulingReleaseDependencyKey] = {}
    if not 1 <= len(sources.references) <= MAX_RELEASE_DEPENDENCY_USES:
        raise SchedulingLimitError
    result = []
    for reference in sources.references:
        identity = reference.kind, reference.source_id
        key = keys.get(identity)
        if key is None:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT public.maru_scheduling_lock_release_source(%s, %s, %s, %s)",
                    [
                        reference.kind.value,
                        reference.source_id,
                        reference.organization_id,
                        reference.edition_id,
                    ],
                )
                if cursor.fetchone() != (True,):
                    raise SchedulingUnavailableError
            query = SchedulingReleaseDependencyKey.objects.select_for_update()
            if create_missing:
                key, _created = query.get_or_create(
                    kind=reference.kind.value,
                    source_id=reference.source_id,
                    defaults={
                        "organization_id": reference.organization_id,
                        "edition_id": reference.edition_id,
                    },
                )
            else:
                key = query.filter(
                    kind=reference.kind.value, source_id=reference.source_id
                ).first()
                if key is None:
                    raise SchedulingUnavailableError
            if (key.organization_id, key.edition_id) != (
                reference.organization_id,
                reference.edition_id,
            ):
                raise SchedulingUnavailableError
            keys[identity] = key
        result.append(_CapturedReleaseDependency(reference, key.id, key.generation))
    return tuple(result)
