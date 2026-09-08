"""Bounded, audited Scheduling projections without cross-owner private data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import DatabaseError, transaction
from django.db.models import F

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_HISTORY,
    VIEW_PLANNING,
    AuthorizedSchedulingScope,
    SchedulingAuthorizationDeniedError,
    SchedulingAuthorizer,
    authorize_scheduling_scope,
)
from .candidate_commands import _load_manifest
from .catalogs import MAX_CANDIDATES, MAX_OCCURRENCES, MAX_RETAINED_SERVICE_DAYS
from .command_support import SchedulingLimitError, SchedulingUnavailableError
from .inputs import require_identifier, require_version
from .models import (
    SchedulingCandidate,
    SchedulingCandidateRevision,
    SchedulingEditionControl,
    SchedulingOccurrence,
    SchedulingOccurrenceRevision,
    SchedulingPlacementRevision,
    SchedulingServiceDay,
    SchedulingServiceDayRevision,
)
from .time_rules import SchedulingEnvelope, SchedulingWindow

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from uuid import UUID

PLANNING_FIELDS: Final = frozenset(
    {"service_days", "occurrences", "candidates", "placement_times"}
)
HISTORY_FIELDS: Final = frozenset({"planning_history"})
HISTORY_PAGE_SIZE: Final = 50


@dataclass(frozen=True, slots=True)
class SchedulingReadRequest:
    """Trusted exact-scope read attribution without collecting private rationale.

    Attributes
    ----------
    actor_id
        Authenticated person, independently resolved by policy.
    organization_id
        Expected exact owner, not proof of ownership.
    edition_id
        Exact edition, independently resolved before any identifying read.
    correlation_id
        Server-owned trace identifier; never a permission or retry credential.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class PlanningDay:
    """Current Scheduling-owned service-day facts, excluding change rationale.

    Attributes
    ----------
    id
        Stable day identifier.
    revision_id
        Exact current immutable revision for placement preconditions.
    version
        Current metadata version.
    label
        Private operational day label, not a public rendition.
    lifecycle
        Active or retained retired state.
    window
        Absolute overnight-capable window.
    precision_minutes
        Grid step anchored to the window start.
    """

    id: UUID
    revision_id: UUID
    version: int
    label: str
    lifecycle: str
    window: SchedulingWindow
    precision_minutes: int


@dataclass(frozen=True, slots=True)
class PlanningOccurrence:
    """Current stable occurrence metadata without Programme content or hosts.

    Attributes
    ----------
    id
        Stable occurrence identifier.
    revision_id
        Exact current immutable metadata revision.
    version
        Current occurrence version.
    item_id
        Opaque owner link; dereferencing requires Programme authorization.
    lifecycle
        Active or retained retired state.
    group_key
        Optional explicit group identity.
    group_sequence
        Optional positive sequence within that group.
    """

    id: UUID
    revision_id: UUID
    version: int
    item_id: UUID
    lifecycle: str
    group_key: UUID | None
    group_sequence: int | None


@dataclass(frozen=True, slots=True)
class PlanningCandidate:
    """Current candidate summary without history, approver or publication claims.

    Attributes
    ----------
    id
        Stable private candidate identity.
    revision_id
        Exact current manifest revision.
    version
        Current optimistic candidate version.
    label
        Current private candidate label.
    lifecycle
        Draft or terminal archive state.
    placement_count
        Declared complete manifest count, not a reservation count.
    """

    id: UUID
    revision_id: UUID
    version: int
    label: str
    lifecycle: str
    placement_count: int


@dataclass(frozen=True, slots=True)
class PlanningPlacement:
    """Immutable proposed geometry; neither host details nor physical approval.

    Attributes
    ----------
    id
        Exact immutable placement revision.
    occurrence_id
        Stable occurrence used for candidate comparison.
    occurrence_revision_id
        Exact historical occurrence metadata selected by the placement.
    day_revision_id
        Exact historical service-day revision selected by the placement.
    space_id
        Opaque Venue selection; labels and physical facts require its owner.
    capacity_mode
        Requested configured seating, standing or table interpretation.
    expected_attendance
        Proposed capacity, not an attendee or Registration count.
    envelope
        Absolute preparation, effective delivery and teardown boundaries.
    """

    id: UUID
    occurrence_id: UUID
    occurrence_revision_id: UUID
    day_revision_id: UUID
    space_id: UUID
    capacity_mode: str
    expected_attendance: int
    envelope: SchedulingEnvelope


@dataclass(frozen=True, slots=True)
class SchedulingPlanningSnapshot:
    """One complete bounded edition snapshot and optionally selected manifest.

    Attributes
    ----------
    control_version
        Observed command aggregate, zero only before the first planning command.
    edition_version
        Current Events version, not a public edition projection.
    accepts_writes
        Events lifecycle consequence only; each command needs separate authority.
    days
        All retained current day revisions in deterministic window order.
    occurrences
        All retained current occurrence revisions in stable identity order.
    candidates
        All current candidate summaries in stable creation order.
    selected_candidate_id
        Explicit selected candidate, or none; no implicit first-candidate choice.
    placements
        Complete selected current manifest, excluding private owner layers.
    """

    control_version: int
    edition_version: int
    accepts_writes: bool
    days: tuple[PlanningDay, ...]
    occurrences: tuple[PlanningOccurrence, ...]
    candidates: tuple[PlanningCandidate, ...]
    selected_candidate_id: UUID | None
    placements: tuple[PlanningPlacement, ...]


@dataclass(frozen=True, slots=True)
class PlanningHistoryEntry:
    """Independently authorized immutable candidate change evidence.

    Attributes
    ----------
    revision_id
        Exact immutable revision for comparison, copy or restore.
    version
        Historical candidate sequence.
    label
        Label retained by this revision, not a current owner label.
    operation
        Closed Scheduling operation that created the revision.
    source_revision_id
        Optional exact copy/restore source, not dereference authority.
    placement_count
        Declared complete manifest size.
    actor_id
        Attributable actor reference, without identity/contact disclosure.
    reason
        Restricted retained action rationale.
    occurred_at
        Server-recorded revision creation instant.
    """

    revision_id: UUID
    version: int
    label: str
    operation: str
    source_revision_id: UUID | None
    placement_count: int
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PlanningHistoryPage:
    """Explicitly paged history; a partial page never claims complete history.

    Attributes
    ----------
    entries
        Up to fifty newest-first revisions before the requested cursor.
    next_before_version
        Exclusive sequence cursor for older evidence, or none at the end.
    """

    entries: tuple[PlanningHistoryEntry, ...]
    next_before_version: int | None


@dataclass(frozen=True, slots=True)
class PlanningHistoricalManifest:
    """One authorized immutable revision with its complete minimized geometry.

    Attributes
    ----------
    candidate_id
        Exact owning candidate.
    entry
        Retained change identity and rationale.
    placements
        Complete digest-validated manifest; current owner labels are excluded.
    """

    candidate_id: UUID
    entry: PlanningHistoryEntry
    placements: tuple[PlanningPlacement, ...]


def _ownership(request: SchedulingReadRequest) -> dict[str, UUID]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _authorize(
    request: SchedulingReadRequest,
    capability: str,
    fields: frozenset[str],
    authorizer: SchedulingAuthorizer,
    *,
    lock: bool = False,
) -> AuthorizedSchedulingScope:
    return authorize_scheduling_scope(
        actor_id=request.actor_id,
        **_ownership(request),
        capability_code=capability,
        requested_fields=fields,
        authorizer=authorizer,
        lock=lock,
    )


def _audit(
    request: SchedulingReadRequest,
    capability: str,
    purpose: str,
    *,
    scope: AuthorizedSchedulingScope | None,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code=capability,
            operation=f"scheduling.query.{purpose}",
            target_type="events.edition",
            target_id=request.edition_id if scope else None,
            outcome="allow" if scope else "deny",
            reason_code=scope.decision.reason_code
            if scope
            else "scheduling_read_denied",
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="scheduling-planning",
            obligations=tuple(
                sorted(
                    (scope.decision.obligations if scope else frozenset())
                    | {"audit_sensitive_read"}
                )
            ),
            safe_metadata={"policy_version": POLICY_VERSION, "access_purpose": purpose},
            retention_class="programme-restricted",
        )
    )


def _lock_edition(request: SchedulingReadRequest) -> None:
    if resolve_scheduling_edition_reference(**_ownership(request), lock=True) is None:
        raise SchedulingAuthorizationDeniedError


def _read[ResultT](
    request: SchedulingReadRequest,
    *,
    capability: str,
    fields: frozenset[str],
    purpose: str,
    authorizer: SchedulingAuthorizer,
    loader: Callable[[AuthorizedSchedulingScope], ResultT],
) -> ResultT:
    for value in (
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    ):
        require_identifier(value)
    try:
        with transaction.atomic():
            # Match commands: edition mutex, then any complete owner-resolved
            # person set, then the actor-only final recheck. Locking the actor
            # first would invert Programme's multi-host canonical lock order.
            _lock_edition(request)
            scope = _authorize(request, capability, fields, authorizer)
            result = loader(scope)
            scope = _authorize(request, capability, fields, authorizer, lock=True)
            _audit(request, capability, purpose, scope=scope)
            return result
    except SchedulingAuthorizationDeniedError:
        # Never release data if the final policy or required audit fails.
        # Denial audit is best effort after the successful-read attempt rolls back.
        try:
            with transaction.atomic():
                _audit(request, capability, purpose, scope=None)
        except (DatabaseError, RuntimeError):
            pass
        raise
    except DatabaseError as error:
        raise SchedulingUnavailableError from error


def _bounded[RowT](rows: Sequence[RowT], maximum: int) -> tuple[RowT, ...]:
    if len(rows) > maximum:
        raise SchedulingLimitError
    return tuple(rows)


def _placements(revision: SchedulingCandidateRevision) -> tuple[PlanningPlacement, ...]:
    manifest = _load_manifest(revision)
    rows = tuple(
        SchedulingPlacementRevision.objects.filter(
            organization_id=revision.organization_id,
            edition_id=revision.edition_id,
            id__in=[placement for _, placement in manifest],
        )
        .select_related("occurrence_revision")
        .order_by("effective_starts_at", "id")[: MAX_OCCURRENCES + 1]
    )
    actual = {(row.occurrence_revision.occurrence_id, row.id) for row in rows}
    if actual != set(manifest) or len(rows) != len(manifest):
        raise SchedulingUnavailableError
    return tuple(
        PlanningPlacement(
            row.id,
            row.occurrence_revision.occurrence_id,
            row.occurrence_revision_id,
            row.day_revision_id,
            row.space_selection_id,
            row.capacity_mode,
            row.expected_attendance,
            SchedulingEnvelope(
                row.setup_starts_at,
                row.effective_starts_at,
                row.effective_ends_at,
                row.teardown_ends_at,
            ),
        )
        for row in rows
    )


def _snapshot(
    request: SchedulingReadRequest,
    candidate_id: UUID | None,
    scope: AuthorizedSchedulingScope,
) -> SchedulingPlanningSnapshot:
    ownership = _ownership(request)
    days = _bounded(
        list(
            SchedulingServiceDayRevision.objects.filter(
                **ownership, sequence=F("day__aggregate_version")
            )
            .only(
                "day_id",
                "sequence",
                "label",
                "lifecycle",
                "starts_at",
                "ends_at",
                "precision_minutes",
            )
            .order_by("starts_at", "day_id")[: MAX_RETAINED_SERVICE_DAYS + 1]
        ),
        MAX_RETAINED_SERVICE_DAYS,
    )
    occurrences = _bounded(
        list(
            SchedulingOccurrenceRevision.objects.filter(
                **ownership, sequence=F("occurrence__aggregate_version")
            )
            .select_related("occurrence")
            .only(
                "occurrence_id",
                "sequence",
                "lifecycle",
                "group_key",
                "group_sequence",
                "occurrence__programme_item_id",
            )
            .order_by("occurrence_id")[: MAX_OCCURRENCES + 1]
        ),
        MAX_OCCURRENCES,
    )
    candidates = _bounded(
        list(
            SchedulingCandidateRevision.objects.filter(
                **ownership, sequence=F("candidate__aggregate_version")
            )
            .select_related("candidate")
            .only(
                "candidate_id",
                "sequence",
                "label",
                "placement_count",
                "manifest_digest",
                "organization_id",
                "edition_id",
                "candidate__lifecycle",
            )
            .order_by("candidate__created_at", "candidate_id")[: MAX_CANDIDATES + 1]
        ),
        MAX_CANDIDATES,
    )
    selected = next(
        (row for row in candidates if row.candidate_id == candidate_id), None
    )
    # A missing current revision is unavailable, not a silently omitted item.
    if (
        SchedulingServiceDay.objects.filter(**ownership).count() != len(days)
        or SchedulingOccurrence.objects.filter(**ownership).count() != len(occurrences)
        or SchedulingCandidate.objects.filter(**ownership).count() != len(candidates)
    ):
        raise SchedulingUnavailableError
    if candidate_id is not None and selected is None:
        raise SchedulingUnavailableError
    control = (
        SchedulingEditionControl.objects.filter(**ownership)
        .values_list("aggregate_version", flat=True)
        .first()
    )
    if control is None and (days or occurrences or candidates):
        raise SchedulingUnavailableError
    return SchedulingPlanningSnapshot(
        control_version=control or 0,
        edition_version=scope.edition_version,
        accepts_writes=scope.accepts_writes,
        days=tuple(
            PlanningDay(
                row.day_id,
                row.id,
                row.sequence,
                row.label,
                row.lifecycle,
                SchedulingWindow(row.starts_at, row.ends_at),
                row.precision_minutes,
            )
            for row in days
        ),
        occurrences=tuple(
            PlanningOccurrence(
                row.occurrence_id,
                row.id,
                row.sequence,
                row.occurrence.programme_item_id,
                row.lifecycle,
                row.group_key,
                row.group_sequence,
            )
            for row in occurrences
        ),
        candidates=tuple(
            PlanningCandidate(
                row.candidate_id,
                row.id,
                row.sequence,
                row.label,
                row.candidate.lifecycle,
                row.placement_count,
            )
            for row in candidates
        ),
        selected_candidate_id=candidate_id,
        placements=_placements(selected) if selected else (),
    )


def load_scheduling_planning(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingPlanningSnapshot:
    """Read current planning under one edition mutex and final field authorization.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope actor and correlation attribution.
    candidate_id : UUID | None, default=None
        Explicit selected candidate; absent means inventory without a manifest.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy, or the existing doubly guarded isolated-test substitute.

    Returns
    -------
    SchedulingPlanningSnapshot
        Complete bounded Scheduling facts only, audited before disclosure.
    """
    if candidate_id is not None:
        require_identifier(candidate_id)
    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=PLANNING_FIELDS,
        purpose="planning",
        authorizer=authorizer,
        loader=lambda scope: _snapshot(request, candidate_id, scope),
    )


def _history_entry(row: SchedulingCandidateRevision) -> PlanningHistoryEntry:
    return PlanningHistoryEntry(
        row.id,
        row.sequence,
        row.label,
        row.operation,
        row.source_revision_id,
        row.placement_count,
        row.actor_id,
        row.reason,
        row.created_at,
    )


def list_scheduling_candidate_history(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    before_version: int | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> PlanningHistoryPage:
    """Page immutable candidate changes with independent history authority.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope actor and correlation attribution.
    candidate_id : UUID
        Exact candidate whose history is requested.
    before_version : int | None, default=None
        Exclusive positive version cursor; none starts at the newest revision.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy, or the existing doubly guarded isolated-test substitute.

    Returns
    -------
    PlanningHistoryPage
        Explicit fifty-row page with a continuation only when older rows exist.
    """
    require_identifier(candidate_id)
    if before_version is not None:
        require_version(before_version)

    def load(_scope: AuthorizedSchedulingScope) -> PlanningHistoryPage:
        query = SchedulingCandidateRevision.objects.filter(
            **_ownership(request), candidate_id=candidate_id
        )
        if not query.exists():
            raise SchedulingUnavailableError
        if before_version is not None:
            query = query.filter(sequence__lt=before_version)
        rows = tuple(query.order_by("-sequence")[: HISTORY_PAGE_SIZE + 1])
        entries = tuple(_history_entry(row) for row in rows[:HISTORY_PAGE_SIZE])
        return PlanningHistoryPage(
            entries,
            entries[-1].version if len(rows) > HISTORY_PAGE_SIZE else None,
        )

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS,
        purpose="candidate_history",
        authorizer=authorizer,
        loader=load,
    )


def load_scheduling_historical_manifest(
    request: SchedulingReadRequest,
    *,
    revision_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> PlanningHistoricalManifest:
    """Read one exact historical manifest without opening any private owner layer.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope actor and correlation attribution.
    revision_id : UUID
        Exact immutable revision for authorized comparison, copy or restore.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy, or the existing doubly guarded isolated-test substitute.

    Returns
    -------
    PlanningHistoricalManifest
        Retained history and complete Scheduling-owned placement geometry.
    """
    require_identifier(revision_id)

    def load(_scope: AuthorizedSchedulingScope) -> PlanningHistoricalManifest:
        row = SchedulingCandidateRevision.objects.filter(
            **_ownership(request), id=revision_id
        ).first()
        if row is None:
            raise SchedulingUnavailableError
        return PlanningHistoricalManifest(
            row.candidate_id, _history_entry(row), _placements(row)
        )

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS,
        purpose="historical_manifest",
        authorizer=authorizer,
        loader=load,
    )
