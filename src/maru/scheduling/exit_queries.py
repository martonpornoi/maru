"""Complete source-authorized Scheduling history for the restricted exit archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HISTORY, VIEW_PLANNING
from .catalogs import SchedulingOperation
from .command_support import SchedulingUnavailableError
from .models import (
    SchedulingOccurrenceRevision,
    SchedulingRelease,
    SchedulingServiceDayRevision,
)
from .planning_queries import (
    HISTORY_FIELDS,
    PLANNING_FIELDS,
    PlanningHistoricalManifest,
    SchedulingPlanningSnapshot,
    SchedulingReadRequest,
    _authorize,
    _read,
    list_scheduling_candidate_history,
    load_scheduling_historical_manifest,
    load_scheduling_planning,
)
from .release_artifacts import (
    CanonicalReleaseArtifact,
    ReleaseArtifactInvalidError,
    verify_canonical_release_artifact,
)
from .release_publication_commands import _placements
from .release_queries import RELEASE_MANIFEST_FIELDS
from .release_workspace_queries import (
    ReleaseHistoryEntry,
    ReleasePointerObservation,
    list_release_history,
    load_release_pointer,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer

    from .authorization import SchedulingAuthorizer

MAX_EXIT_CANDIDATE_REVISIONS: Final = 20_000
MAX_EXIT_PLACEMENTS: Final = 250_000
MAX_EXIT_METADATA_REVISIONS: Final = 100_000
MAX_EXIT_RELEASE_HISTORY: Final = 10_000
MAX_EXIT_ARTIFACT_BYTES: Final = 67_108_864
DAY_COLUMNS: Final = (
    "id",
    "day_id",
    "sequence",
    "label",
    "starts_at",
    "ends_at",
    "precision_minutes",
    "edition_version",
    "lifecycle",
    "actor_id",
    "reason",
    "occurred_at",
)
OCCURRENCE_COLUMNS: Final = (
    "id",
    "occurrence_id",
    "sequence",
    "group_key",
    "group_sequence",
    "lifecycle",
    "actor_id",
    "reason",
    "occurred_at",
)


@dataclass(frozen=True, slots=True)
class SchedulingExitRelease:
    """Verified immutable canonical identity evidence, never a serving permit.

    Attributes
    ----------
    release_id, approval_id, candidate_revision_id, previous_release_id
        Exact original source/predecessor links; no foreign body access follows.
    pointer_version, source_digest
        Original publication sequence and retained complete source fingerprint.
    artifact
        Canonical identity-only bytes checked against original owner selections.
    """

    release_id: UUID = field(repr=False)
    approval_id: UUID = field(repr=False)
    candidate_revision_id: UUID = field(repr=False)
    previous_release_id: UUID | None = field(repr=False)
    pointer_version: int
    source_digest: str = field(repr=False)
    artifact: CanonicalReleaseArtifact = field(repr=False)


@dataclass(frozen=True, slots=True)
class SchedulingExitOwner:
    """Complete bounded historical Scheduling owner evidence, with no foreign copy.

    Attributes
    ----------
    planning, manifests
        Current inventory and every exact immutable candidate manifest.
    day_revisions, occurrence_revisions
        Explicit DAY_COLUMNS/OCCURRENCE_COLUMNS tuples, not discovered model fields.
    pointer, release_history, releases
        Current monotonic pointer and complete original publication/withdrawal and
        canonical artifact evidence. No assertion of current release usability.
    """

    planning: SchedulingPlanningSnapshot = field(repr=False)
    manifests: tuple[PlanningHistoricalManifest, ...] = field(repr=False)
    day_revisions: tuple[tuple[object, ...], ...] = field(repr=False)
    occurrence_revisions: tuple[tuple[object, ...], ...] = field(repr=False)
    pointer: ReleasePointerObservation = field(repr=False)
    release_history: tuple[ReleaseHistoryEntry, ...] = field(repr=False)
    releases: tuple[SchedulingExitRelease, ...] = field(repr=False)


def _metadata(
    request: SchedulingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
) -> tuple[tuple[tuple[object, ...], ...], tuple[tuple[object, ...], ...]]:
    results = []
    total = 0
    for model, columns, expected in (
        (
            SchedulingServiceDayRevision,
            DAY_COLUMNS,
            {row.id: row.version for row in snapshot.days},
        ),
        (
            SchedulingOccurrenceRevision,
            OCCURRENCE_COLUMNS,
            {row.id: row.version for row in snapshot.occurrences},
        ),
    ):
        rows = tuple(
            model.objects.filter(
                organization_id=request.organization_id, edition_id=request.edition_id
            )
            .order_by(columns[1], "sequence")
            .values_list(*columns)[: MAX_EXIT_METADATA_REVISIONS + 1]
        )
        total += len(rows)
        if total > MAX_EXIT_METADATA_REVISIONS:
            raise SchedulingUnavailableError
        seen: dict[UUID, int] = {}
        for row in rows:
            parent, version = row[1:3]
            if parent not in expected or version != seen.get(parent, 0) + 1:
                raise SchedulingUnavailableError
            seen[parent] = version
        if seen != expected:
            raise SchedulingUnavailableError
        results.append(rows)
    return results[0], results[1]


def _manifests(
    request: SchedulingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    authorizer: SchedulingAuthorizer,
) -> tuple[PlanningHistoricalManifest, ...]:
    manifests: list[PlanningHistoricalManifest] = []
    membership_count = 0
    for candidate in snapshot.candidates:
        expected = candidate.version
        cursor = None
        while expected:
            page = list_scheduling_candidate_history(
                request,
                candidate_id=candidate.id,
                before_version=cursor,
                authorizer=authorizer,
            )
            if (
                not page.entries
                or len(manifests) + len(page.entries) > MAX_EXIT_CANDIDATE_REVISIONS
            ):
                raise SchedulingUnavailableError
            for entry in page.entries:
                if entry.version != expected:
                    raise SchedulingUnavailableError
                manifest = load_scheduling_historical_manifest(
                    request, revision_id=entry.revision_id, authorizer=authorizer
                )
                if (
                    manifest.candidate_id != candidate.id
                    or manifest.entry != entry
                    or len(manifest.placements) != entry.placement_count
                ):
                    raise SchedulingUnavailableError
                membership_count += len(manifest.placements)
                if membership_count > MAX_EXIT_PLACEMENTS:
                    raise SchedulingUnavailableError
                manifests.append(manifest)
                expected -= 1
            cursor = expected + 1 if expected else None
            if page.next_before_version != cursor:
                raise SchedulingUnavailableError
    return tuple(manifests)


def _history(
    request: SchedulingReadRequest,
    pointer: ReleasePointerObservation,
    authorizer: SchedulingAuthorizer,
) -> tuple[ReleaseHistoryEntry, ...]:
    if pointer.version > MAX_EXIT_RELEASE_HISTORY:
        raise SchedulingUnavailableError
    expected = pointer.version
    cursor = None
    history = []
    while True:
        page = list_release_history(
            request, before_version=cursor, authorizer=authorizer
        )
        if not page.entries and expected:
            raise SchedulingUnavailableError
        for entry in page.entries:
            if entry.version != expected:
                raise SchedulingUnavailableError
            expected -= 1
            history.append(entry)
        cursor = expected + 1 if expected else None
        if page.next_before_version != cursor:
            raise SchedulingUnavailableError
        if not expected:
            return tuple(history)


def _releases(
    request: SchedulingReadRequest, history: tuple[ReleaseHistoryEntry, ...]
) -> tuple[SchedulingExitRelease, ...]:
    identifiers = {entry.release_id for entry in history}
    rows = tuple(
        SchedulingRelease.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
        )
        .select_related("approval")
        .order_by("pointer_version")[: MAX_EXIT_RELEASE_HISTORY + 1]
    )
    if len(rows) > MAX_EXIT_RELEASE_HISTORY or {row.id for row in rows} != identifiers:
        raise SchedulingUnavailableError
    result = []
    byte_count = 0
    predecessors: dict[UUID, UUID | None] = {}
    active = None
    for entry in reversed(history):
        if entry.operation == SchedulingOperation.RELEASE_PUBLISH:
            predecessors[entry.release_id] = active
            active = entry.release_id
        elif entry.operation == SchedulingOperation.RELEASE_WITHDRAW:
            if active != entry.release_id:
                raise SchedulingUnavailableError
            active = None
        else:
            raise SchedulingUnavailableError
    for row in rows:
        if (
            row.id not in predecessors
            or row.previous_release_id != predecessors[row.id]
        ):
            raise SchedulingUnavailableError
        artifacts = tuple(
            row.artifacts.filter(
                organization_id=request.organization_id, edition_id=request.edition_id
            )[:2]
        )
        if len(artifacts) != 1 or (
            row.approval.organization_id,
            row.approval.edition_id,
        ) != (request.organization_id, request.edition_id):
            raise SchedulingUnavailableError
        artifact = artifacts[0]
        canonical = CanonicalReleaseArtifact(
            artifact.contract,
            bytes(artifact.payload),
            artifact.sha256,
            artifact.byte_length,
        )
        try:
            verify_canonical_release_artifact(
                canonical,
                release_id=row.id,
                approval_id=row.approval_id,
                candidate_revision_id=row.approval.candidate_revision_id,
                source_snapshot_digest=row.approval.source_snapshot_digest,
                selections=_placements(row.approval),
            )
        except ReleaseArtifactInvalidError as error:
            raise SchedulingUnavailableError from error
        byte_count += artifact.byte_length
        if byte_count > MAX_EXIT_ARTIFACT_BYTES:
            raise SchedulingUnavailableError
        result.append(
            SchedulingExitRelease(
                row.id,
                row.approval_id,
                row.approval.candidate_revision_id,
                row.previous_release_id,
                row.pointer_version,
                row.approval.source_snapshot_digest,
                canonical,
            )
        )
    return tuple(result)


def load_scheduling_exit_owner(  # noqa: DOC502 -- guarded loader propagates unavailability.
    request: SchedulingReadRequest,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> SchedulingExitOwner:
    """Collect complete historical evidence under independent export/source rights.

    Parameters
    ----------
    request : SchedulingReadRequest
        Actual requester, exact tenant/edition and server-owned audit trace.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Existing planning, history and release-manifest source policy.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional archive-purpose admission, not a foreign source content grant.

    Returns
    -------
    SchedulingExitOwner
        Complete bounded owned history and verified identity artifacts.

    Raises
    ------
    SchedulingUnavailableError
        If completeness, source consistency, artifact integrity or resource limits fail.

    Notes
    -----
    Withdrawn canonical identities are archive-only historical evidence. This does
    not call an old release available, disclose owner private bodies, or change
    ordinary serving suppression. Whole-archive closure must precede child reads.
    """

    def purpose() -> None:
        authorize_programme_archive_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    def collect(_scope: object) -> SchedulingExitOwner:
        purpose()
        _authorize(
            request,
            VIEW_PLANNING,
            PLANNING_FIELDS | RELEASE_MANIFEST_FIELDS,
            authorizer,
        )
        snapshot = load_scheduling_planning(request, authorizer=authorizer)
        day_revisions, occurrence_revisions = _metadata(request, snapshot)
        manifests = _manifests(request, snapshot, authorizer)
        pointer = load_release_pointer(request, authorizer=authorizer)
        history = _history(request, pointer, authorizer)
        releases = _releases(request, history)
        if (
            load_scheduling_planning(request, authorizer=authorizer) != snapshot
            or load_release_pointer(request, authorizer=authorizer) != pointer
        ):
            raise SchedulingUnavailableError
        purpose()
        return SchedulingExitOwner(
            snapshot,
            manifests,
            day_revisions,
            occurrence_revisions,
            pointer,
            history,
            releases,
        )

    purpose()
    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS,
        purpose="exit_owner",
        authorizer=authorizer,
        loader=collect,
    )
