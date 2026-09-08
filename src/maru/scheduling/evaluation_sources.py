"""Current owner-resolved candidate facts and calendar-free dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.events.adoption import profile_allows_conflict_source
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_edition_time_envelope_reference,
)
from maru.programme.adoption import PROGRAMME_SCHEDULING_CONFLICT_SOURCE
from maru.programme.authorization import ProgrammeAuthorizationDenied
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.programme.scheduling_queries import load_programme_scheduling_dependencies
from maru.venues.adoption import VENUES_SCHEDULING_CONFLICT_SOURCE
from maru.venues.scheduling_queries import (
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
    load_venue_scheduling_dependencies,
)

from .adoption import SCHEDULING_TIME_CONFLICT_SOURCE
from .candidate_commands import _load_manifest
from .catalogs import DEFERRED_SCHEDULING_CHECKS, MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .conflicts import (
    SchedulingDayFacts,
    SchedulingFinding,
    SchedulingOccurrenceFacts,
    SchedulingPlacementFacts,
    evaluate_scheduling_facts,
)
from .inputs import SchedulingCommandRequest, scheduling_digest
from .models import (
    SchedulingCandidateRevision,
    SchedulingPlacementHostPresence,
    SchedulingPlacementRevision,
)
from .time_rules import SchedulingEnvelope, SchedulingHostPresence, SchedulingWindow

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.scheduling_queries import ProgrammeSchedulingSnapshot
    from maru.venues.scheduling_queries import VenueSchedulingSnapshot

_MAX_PRESENCES = MAX_OCCURRENCES * 100


@dataclass(frozen=True, slots=True)
class _SchedulingSourceRead:
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    source_channel: str = "scheduling-planning"


type _SourceRequest = SchedulingCommandRequest | _SchedulingSourceRead


@dataclass(frozen=True, slots=True)
class _CurrentEvaluation:
    revision: SchedulingCandidateRevision
    findings: tuple[SchedulingFinding, ...]
    evidence: list[dict[str, object]]
    digest: str

    @property
    def complete(self) -> bool:
        return all(finding.severity != "unavailable" for finding in self.findings)


def _placement_facts(
    revision: SchedulingCandidateRevision,
) -> tuple[SchedulingPlacementFacts, ...]:
    manifest = _load_manifest(revision)
    ids = tuple(placement_id for _, placement_id in manifest)
    scope = {
        "organization_id": revision.organization_id,
        "edition_id": revision.edition_id,
    }
    rows = tuple(
        SchedulingPlacementRevision.objects.filter(**scope, id__in=ids)
        .select_related("occurrence_revision__occurrence", "day_revision__day")
        .order_by("id")
    )
    presences = tuple(
        SchedulingPlacementHostPresence.objects.filter(**scope, placement_id__in=ids)
        .order_by("placement_id", "host_relationship_id")
        .values_list("placement_id", "host_relationship_id", "starts_at", "ends_at")[
            : _MAX_PRESENCES + 1
        ]
    )
    if len(rows) != len(ids) or len(presences) > _MAX_PRESENCES:
        raise SchedulingUnavailableError
    hosts: dict[UUID, list[SchedulingHostPresence]] = {}
    for placement_id, host_id, start, end in presences:
        hosts.setdefault(placement_id, []).append(
            SchedulingHostPresence(host_id, start, end)
        )
    expected = dict(manifest)
    facts = []
    for row in rows:
        occurrence, day = row.occurrence_revision, row.day_revision
        selected = tuple(hosts.get(row.id, []))
        if (
            expected.get(occurrence.occurrence_id) != row.id
            or len(selected) != row.host_presence_count
        ):
            raise SchedulingUnavailableError
        facts.append(
            SchedulingPlacementFacts(
                row.id,
                SchedulingOccurrenceFacts(
                    occurrence.occurrence_id,
                    occurrence.occurrence.programme_item_id,
                    occurrence.sequence,
                    occurrence.occurrence.aggregate_version,
                    occurrence.occurrence.lifecycle == "active",
                ),
                SchedulingDayFacts(
                    day.day_id,
                    day.sequence,
                    day.day.aggregate_version,
                    day.day.lifecycle == "active",
                    SchedulingWindow(day.starts_at, day.ends_at),
                    day.precision_minutes,
                ),
                row.space_selection_id,
                SchedulingEnvelope(
                    row.setup_starts_at,
                    row.effective_starts_at,
                    row.effective_ends_at,
                    row.teardown_ends_at,
                ),
                row.capacity_mode,
                row.expected_attendance,
                selected,
            )
        )
    return tuple(facts)


def _programme_source(
    request: _SourceRequest, facts: tuple[SchedulingPlacementFacts, ...]
) -> ProgrammeSchedulingSnapshot | None:
    try:
        return load_programme_scheduling_dependencies(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_ids=tuple(sorted({fact.occurrence.item_id for fact in facts})),
            host_ids=tuple(
                sorted({host.host_id for fact in facts for host in fact.hosts})
            ),
            correlation_id=request.correlation_id,
            source_channel=request.source_channel,
        )
    except (
        ProgrammeQueryUnavailableError,
        ProgrammeAuthorizationDenied,
        ValidationError,
    ):
        return None


def _venue_source(
    request: _SourceRequest, facts: tuple[SchedulingPlacementFacts, ...]
) -> VenueSchedulingSnapshot | None:
    try:
        return load_venue_scheduling_dependencies(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            selection_ids=tuple(sorted({fact.space_id for fact in facts})),
            placement_ids=tuple(sorted(fact.id for fact in facts)),
            correlation_id=request.correlation_id,
            source_channel=request.source_channel,
        )
    except (
        VenueSchedulingSourceUnavailableError,
        VenueSchedulingSourceDeniedError,
        ValidationError,
    ):
        return None


def _programme_evidence(
    source: ProgrammeSchedulingSnapshot | None,
) -> dict[str, object]:
    # Explicit version-only allowlist: never serialize the owner DTO with asdict;
    # its periods and person conflict key are ephemeral evaluation inputs only.
    return {
        "source_code": PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
        "available": source is not None,
        "edition_version": source.edition_version if source else None,
        "items": [
            {
                "id": str(item.item_id),
                "version": item.item_version,
                "lifecycle": item.lifecycle,
                "hosting_required": item.hosting_required,
            }
            for item in source.items
        ]
        if source
        else [],
        "hosts": [
            {
                "id": str(host.host_id),
                "version": host.host_version,
                "availability_version": host.availability_version,
                "status": host.status,
            }
            for host in source.hosts
        ]
        if source
        else [],
    }


def _venue_evidence(
    source: VenueSchedulingSnapshot | None, facts: tuple[SchedulingPlacementFacts, ...]
) -> dict[str, object]:
    bindings = (
        {binding.placement_id: binding for binding in source.reservations}
        if source
        else {}
    )
    return {
        "source_code": VENUES_SCHEDULING_CONFLICT_SOURCE,
        "physical_bindings": [
            {
                "placement_id": str(fact.id),
                "state": (
                    "unavailable"
                    if source is None
                    else "unreserved"
                    if fact.id not in bindings
                    else "reserved_approved"
                    if bindings[fact.id].review_state == "approved"
                    else "reserved_draft"
                ),
            }
            for fact in facts
        ],
        "available": source is not None,
        "edition_version": source.edition_version if source else None,
        "spaces": [
            {
                "id": str(space.selection_id),
                "version": space.version,
                "availability_version": space.availability_version,
                "active": space.active,
            }
            for space in source.spaces
        ]
        if source
        else [],
        "busy_sources": [
            {"id": str(key), "version": version}
            for key, version in sorted(
                {
                    (period.source_key, period.source_version)
                    for period in source.busy_periods
                }
            )
        ]
        if source
        else [],
        "reservations": [
            {
                "placement_id": str(binding.placement_id),
                "booking_id": str(binding.booking_id),
                "version": binding.booking_version,
                "review_state": binding.review_state,
            }
            for binding in source.reservations
        ]
        if source
        else [],
    }


def _require_source_adoption(request: _SourceRequest) -> None:
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_conflict_source(
        profile.code, profile.version, SCHEDULING_TIME_CONFLICT_SOURCE
    ):
        raise SchedulingUnavailableError


def _current_evaluation(
    request: _SourceRequest, *, candidate_id: UUID, expected_version: int
) -> _CurrentEvaluation:
    _require_source_adoption(request)
    revision = SchedulingCandidateRevision.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        candidate_id=candidate_id,
        sequence=expected_version,
        candidate__aggregate_version=expected_version,
        candidate__lifecycle="draft",
    ).first()
    if revision is None:
        raise SchedulingUnavailableError
    facts = _placement_facts(revision)
    return _evaluate_candidate_facts(request, revision, facts)


def _evaluate_candidate_facts(
    request: _SourceRequest,
    revision: SchedulingCandidateRevision,
    facts: tuple[SchedulingPlacementFacts, ...],
) -> _CurrentEvaluation:
    # Caller owns edition mutex and current Scheduling/source authorization;
    # both dependency owners independently authorize and audit their reads.
    # Unsaved previews use this same algorithm but never expose its digest as
    # persisted evaluation evidence or warning-acknowledgement authority.
    programme = _programme_source(request, facts)
    venues = _venue_source(request, facts)
    bindings = (
        {binding.placement_id: binding for binding in venues.reservations}
        if venues
        else {}
    )
    facts = tuple(
        replace(
            fact,
            own_booking_id=(
                bindings[fact.id].booking_id
                if fact.id in bindings
                and bindings[fact.id].occurrence_id == fact.occurrence.id
                else None
            ),
        )
        for fact in facts
    )
    edition = resolve_edition_time_envelope_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    findings = evaluate_scheduling_facts(
        facts,
        edition=SchedulingWindow(edition.starts_at, edition.ends_at)
        if edition
        else None,
        programme=programme,
        venues=venues,
    )
    evidence: list[dict[str, object]] = [
        {
            "source_code": SCHEDULING_TIME_CONFLICT_SOURCE,
            "schema_version": 1,
            "not_evaluated": list(DEFERRED_SCHEDULING_CHECKS),
            "revision_id": str(revision.id),
            "manifest_digest": revision.manifest_digest,
            "edition_version": edition.version if edition else None,
            "occurrences": [
                {"id": str(key), "version": version, "active": active}
                for key, version, active in sorted(
                    {
                        (
                            fact.occurrence.id,
                            fact.occurrence.current_version,
                            fact.occurrence.active,
                        )
                        for fact in facts
                    }
                )
            ],
            "days": [
                {"id": str(key), "version": version, "active": active}
                for key, version, active in sorted(
                    {
                        (fact.day.id, fact.day.current_version, fact.day.active)
                        for fact in facts
                    }
                )
            ],
        },
        _programme_evidence(programme),
        _venue_evidence(venues, facts),
    ]
    return _CurrentEvaluation(
        revision, findings, evidence, scheduling_digest({"sources": evidence})
    )


def _finding_fingerprint(dependency_digest: str, finding: SchedulingFinding) -> str:
    return scheduling_digest(
        {
            "dependency_digest": dependency_digest,
            "source_code": finding.source_code,
            "code": finding.code.value,
            "severity": finding.severity.value,
            "occurrence_id": str(finding.occurrence_id)
            if finding.occurrence_id
            else None,
            "other_occurrence_id": str(finding.other_occurrence_id)
            if finding.other_occurrence_id
            else None,
        }
    )
