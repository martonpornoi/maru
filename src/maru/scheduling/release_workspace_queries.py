"""Bounded release-task discovery; retained evidence never grants release authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db.models import F, Q

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HISTORY, VIEW_PLANNING
from .catalogs import MAX_CANDIDATES, MAX_CONFLICTS
from .catalogs import SchedulingOperation as Op
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier, require_version
from .models import (
    SchedulingCandidate,
    SchedulingCandidateRevision,
    SchedulingRelease,
    SchedulingReleaseApproval,
    SchedulingReleasePointer,
    SchedulingReleaseWarningAcknowledgement,
    SchedulingReleaseWithdrawal,
)
from .planning_queries import HISTORY_FIELDS, PlanningCandidate, _bounded, _read
from .release_inputs import ReleaseCandidateSelection
from .release_queries import RELEASE_MANIFEST_FIELDS

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest

RELEASE_HISTORY_PAGE_SIZE: Final = 50
RELEASE_CANDIDATE_FIELDS: Final = frozenset({"candidates"})
_RECEIPT_FIELDS = (
    "command_receipt__organization_id",
    "command_receipt__edition_id",
    "command_receipt__operation",
    "command_receipt__result_object_id",
    "command_receipt__resulting_version",
    "command_receipt__actor_id",
    "command_receipt__reason",
    "command_receipt__occurred_at",
)
_EVIDENCE_FIELDS = (
    "id",
    "organization_id",
    "edition_id",
    "actor_id",
    "reason",
    "occurred_at",
    *_RECEIPT_FIELDS,
)
_CANDIDATE_FIELDS = (
    "candidate_revision__id",
    "candidate_revision__organization_id",
    "candidate_revision__edition_id",
    "candidate_revision__candidate_id",
    "candidate_revision__sequence",
    "candidate_revision__label",
    "candidate_revision__placement_count",
)


@dataclass(frozen=True, slots=True)
class ReleaseWarningChoice:
    """Exact retained warning evidence, not an authenticated current waiver.

    Attributes
    ----------
    id
        Immutable acknowledgement reference.
    fingerprint
        Exact finding inside the selected complete source digest.
    check
        Retained release category.
    code
        Minimized retained finding code.
    actor_id
        Accountable reference, without querying a person directory.
    reason
        Restricted retained rationale, disclosed only with history authority.
    occurred_at
        Immutable command time.
    """

    id: UUID
    fingerprint: str
    check: str
    code: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ReleaseApprovalChoice:
    """Retained independent approval identity, not a promise of current eligibility.

    Attributes
    ----------
    id
        Immutable approval reference.
    candidate
        Original revision label/version; lifecycle is intentionally historical.
    snapshot_digest
        Exact approved source, never replaced with a newly computed digest.
    actor_id
        Accountable approver reference, not a current authority assertion.
    reason
        Restricted immutable approval rationale.
    occurred_at
        Immutable approval time.
    """

    id: UUID
    candidate: PlanningCandidate
    snapshot_digest: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ReleaseApprovalPage:
    """One explicit bounded older page of retained approvals.

    Attributes
    ----------
    entries
        Complete selected page, newest first; no current-source eligibility claim.
    next_before_id
        Exact last displayed anchor for the next older page, or no further page.
    """

    entries: tuple[ReleaseApprovalChoice, ...]
    next_before_id: UUID | None


@dataclass(frozen=True, slots=True)
class ReleasePointerObservation:
    """Source-independent current pointer; never permission to serve its content.

    Attributes
    ----------
    active_release_id
        Exact current pointer target or explicit absence after withdrawal/before first.
    version
        Monotonic edition pointer version, zero only before any publication.
    """

    active_release_id: UUID | None
    version: int


@dataclass(frozen=True, slots=True)
class ReleaseHistoryEntry:
    """One retained publication or withdrawal, without artifact content.

    Attributes
    ----------
    id
        Immutable publication or withdrawal evidence identifier.
    release_id
        Exact affected release, not an instruction to activate it.
    operation
        Publication or withdrawal; history does not imply current availability.
    version
        Monotonic pointer version occupied by this event.
    actor_id
        Accountable actor reference only.
    reason
        Restricted retained rationale.
    occurred_at
        Immutable command time.
    """

    id: UUID
    release_id: UUID
    operation: str
    version: int
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ReleaseHistoryPage:
    """One complete pointer-history window, independently of source validity.

    Attributes
    ----------
    entries
        Newest-first retained events, not current release content.
    next_before_version
        Exclusive older-page boundary, absent when no older events remain.
    """

    entries: tuple[ReleaseHistoryEntry, ...]
    next_before_version: int | None


def _ownership(request: SchedulingReadRequest) -> dict[str, UUID]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _authentic(
    row: SchedulingReleaseApproval
    | SchedulingReleaseWarningAcknowledgement
    | SchedulingRelease
    | SchedulingReleaseWithdrawal,
    operation: Op,
    version: int,
) -> None:
    receipt = row.command_receipt
    if (
        receipt.organization_id,
        receipt.edition_id,
        receipt.operation,
        receipt.result_object_id,
        receipt.resulting_version,
        receipt.actor_id,
        receipt.reason,
        receipt.occurred_at,
    ) != (
        row.organization_id,
        row.edition_id,
        operation,
        row.id,
        version,
        row.actor_id,
        row.reason,
        row.occurred_at,
    ):
        raise SchedulingUnavailableError


def _candidate(row: SchedulingReleaseApproval) -> PlanningCandidate:
    revision = row.candidate_revision
    if (revision.organization_id, revision.edition_id) != (
        row.organization_id,
        row.edition_id,
    ):
        raise SchedulingUnavailableError
    return PlanningCandidate(
        revision.candidate_id,
        revision.id,
        revision.sequence,
        revision.label,
        "historical",
        revision.placement_count,
    )


def list_release_candidates(
    request: SchedulingReadRequest,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> tuple[PlanningCandidate, ...]:
    """Discover all labelled current alternatives without loading owner dependencies.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, exact organization/edition and trace attribution.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary independent Scheduling policy; existing isolated-test seam only.

    Returns
    -------
    tuple[PlanningCandidate, ...]
        Complete bounded current inventory; retired and empty drafts stay explicit.
    """

    def load(_scope: object) -> tuple[PlanningCandidate, ...]:
        rows = _bounded(
            list(
                SchedulingCandidateRevision.objects.filter(
                    **_ownership(request),
                    sequence=F("candidate__aggregate_version"),
                    candidate__organization_id=request.organization_id,
                    candidate__edition_id=request.edition_id,
                )
                .select_related("candidate")
                .only(
                    "id",
                    "candidate_id",
                    "sequence",
                    "label",
                    "placement_count",
                    "candidate__lifecycle",
                )
                .order_by("candidate__created_at", "candidate_id")[: MAX_CANDIDATES + 1]
            ),
            MAX_CANDIDATES,
        )
        if SchedulingCandidate.objects.filter(**_ownership(request)).count() != len(
            rows
        ):
            raise SchedulingUnavailableError
        return tuple(
            PlanningCandidate(
                row.candidate_id,
                row.id,
                row.sequence,
                row.label,
                row.candidate.lifecycle,
                row.placement_count,
            )
            for row in rows
        )

    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=RELEASE_CANDIDATE_FIELDS,
        purpose="release_candidates",
        authorizer=authorizer,
        loader=load,
    )


def list_release_warning_evidence(
    request: SchedulingReadRequest,
    *,
    selection: ReleaseCandidateSelection,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> tuple[ReleaseWarningChoice, ...]:
    """Read complete exact-snapshot acknowledgements under independent history policy.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope reader and audit attribution.
    selection : ReleaseCandidateSelection
        Exact retained candidate revision, version and source fingerprint.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independently required restricted-history authority.

    Returns
    -------
    tuple[ReleaseWarningChoice, ...]
        Receipt-coherent retained evidence; the command rechecks current findings.

    Notes
    -----
    Old versions remain readable as history, not a claim of current eligibility.
    Selection validation follows admission. No broad acknowledgement inventory or
    old planning-warning promotion is performed.
    """

    def load(_scope: object) -> tuple[ReleaseWarningChoice, ...]:
        if type(selection) is not ReleaseCandidateSelection:
            raise SchedulingUnavailableError
        selection.validated()
        if not SchedulingCandidateRevision.objects.filter(
            **_ownership(request),
            id=selection.candidate_revision_id,
            candidate_id=selection.candidate_id,
            sequence=selection.expected_candidate_version,
        ).exists():
            raise SchedulingUnavailableError
        rows = _bounded(
            list(
                SchedulingReleaseWarningAcknowledgement.objects.filter(
                    **_ownership(request),
                    candidate_revision_id=selection.candidate_revision_id,
                    source_snapshot_digest=selection.source_snapshot_digest,
                )
                .select_related("command_receipt")
                .only(
                    *_EVIDENCE_FIELDS,
                    "finding_fingerprint",
                    "check_code",
                    "finding_code",
                )
                .order_by("occurred_at", "id")[: MAX_CONFLICTS + 1]
            ),
            MAX_CONFLICTS,
        )
        for row in rows:
            _authentic(row, Op.RELEASE_WARNING_ACKNOWLEDGE, 1)
        return tuple(
            ReleaseWarningChoice(
                row.id,
                row.finding_fingerprint,
                row.check_code,
                row.finding_code,
                row.actor_id,
                row.reason,
                row.occurred_at,
            )
            for row in rows
        )

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS,
        purpose="release_warning_evidence",
        authorizer=authorizer,
        loader=load,
    )


def list_release_approvals(
    request: SchedulingReadRequest,
    *,
    before_id: UUID | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ReleaseApprovalPage:
    """Page immutable labelled approvals without recollecting current owner sources.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope reader and mandatory audit attribution.
    before_id : UUID | None, default=None
        Exclusive exact retained anchor for an older page, never a foreign cursor.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent restricted-history admission, not publication authority.

    Returns
    -------
    ReleaseApprovalPage
        Retained evidence only. A selected approval must still pass publication.
    """

    def load(_scope: object) -> ReleaseApprovalPage:
        query = SchedulingReleaseApproval.objects.filter(**_ownership(request))
        if before_id is not None:
            require_identifier(before_id)
            anchor = query.only("id", "occurred_at").filter(id=before_id).first()
            if anchor is None:
                raise SchedulingUnavailableError
            query = query.filter(
                Q(occurred_at__lt=anchor.occurred_at)
                | Q(occurred_at=anchor.occurred_at, id__lt=anchor.id)
            )
        rows = tuple(
            query.select_related("command_receipt", "candidate_revision")
            .only(
                *_EVIDENCE_FIELDS,
                *_CANDIDATE_FIELDS,
                "source_snapshot_digest",
            )
            .order_by("-occurred_at", "-id")[: RELEASE_HISTORY_PAGE_SIZE + 1]
        )
        for row in rows:
            _authentic(row, Op.RELEASE_APPROVE, 1)
            _candidate(row)
        entries = tuple(
            ReleaseApprovalChoice(
                row.id,
                _candidate(row),
                row.source_snapshot_digest,
                row.actor_id,
                row.reason,
                row.occurred_at,
            )
            for row in rows[:RELEASE_HISTORY_PAGE_SIZE]
        )
        return ReleaseApprovalPage(
            entries,
            entries[-1].id if len(rows) > RELEASE_HISTORY_PAGE_SIZE else None,
        )

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS,
        purpose="release_approvals",
        authorizer=authorizer,
        loader=load,
    )


def load_release_pointer(
    request: SchedulingReadRequest,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ReleasePointerObservation:
    """Observe exact pointer identity without requiring safe content or owner sources.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted scope and current independently checked reader.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Current manifest-field admission; no withdrawal authority is implied.

    Returns
    -------
    ReleasePointerObservation
        Only pointer identity/version. Serving must use the checked output reader.
    """

    def load(_scope: object) -> ReleasePointerObservation:
        pointer = (
            SchedulingReleasePointer.objects.filter(**_ownership(request))
            .only(
                "version",
                "active_release_id",
                "command_receipt_id",
            )
            .first()
        )
        if pointer is None:
            if (
                SchedulingRelease.objects.filter(**_ownership(request)).exists()
                or SchedulingReleaseWithdrawal.objects.filter(
                    **_ownership(request)
                ).exists()
            ):
                raise SchedulingUnavailableError
            return ReleasePointerObservation(None, 0)
        require_version(pointer.version)
        model = (
            SchedulingRelease
            if pointer.active_release_id
            else SchedulingReleaseWithdrawal
        )
        event = (
            model.objects.filter(
                **_ownership(request),
                pointer_version=pointer.version,
                command_receipt_id=pointer.command_receipt_id,
            )
            .select_related("command_receipt")
            .only(*_EVIDENCE_FIELDS)
            .first()
        )
        if event is None or (
            pointer.active_release_id and event.id != pointer.active_release_id
        ):
            raise SchedulingUnavailableError
        _authentic(
            event,
            Op.RELEASE_PUBLISH if pointer.active_release_id else Op.RELEASE_WITHDRAW,
            pointer.version,
        )
        return ReleasePointerObservation(pointer.active_release_id, pointer.version)

    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=RELEASE_MANIFEST_FIELDS,
        purpose="release_pointer",
        authorizer=authorizer,
        loader=load,
    )


def load_release_approval(
    request: SchedulingReadRequest,
    *,
    approval_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ReleaseApprovalChoice:
    """Read one exact immutable approval without refreshing its original source.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-scope reader and audit attribution.
    approval_id : UUID
        Explicit retained selection, validated only after independent admission.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Current restricted-history authority, not publication permission.

    Returns
    -------
    ReleaseApprovalChoice
        Exact immutable candidate label, rationale and source fingerprint.
    """

    def load(_scope: object) -> ReleaseApprovalChoice:
        require_identifier(approval_id)
        row = (
            SchedulingReleaseApproval.objects.filter(
                **_ownership(request),
                id=approval_id,
            )
            .select_related("command_receipt", "candidate_revision")
            .only(
                *_EVIDENCE_FIELDS,
                *_CANDIDATE_FIELDS,
                "source_snapshot_digest",
            )
            .first()
        )
        if row is None:
            raise SchedulingUnavailableError
        _authentic(row, Op.RELEASE_APPROVE, 1)
        return ReleaseApprovalChoice(
            row.id,
            _candidate(row),
            row.source_snapshot_digest,
            row.actor_id,
            row.reason,
            row.occurred_at,
        )

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS,
        purpose="release_approval",
        authorizer=authorizer,
        loader=load,
    )


def list_release_history(
    request: SchedulingReadRequest,
    *,
    before_version: int | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ReleaseHistoryPage:
    """Read a bounded contiguous release-pointer history window without content.

    Parameters
    ----------
    request : SchedulingReadRequest
        Exact-scope reader and trace attribution.
    before_version : int | None, default=None
        Exclusive monotonic version boundary for an older page.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent history and manifest field authority.

    Returns
    -------
    ReleaseHistoryPage
        Explicit immutable publication/withdrawal history, not serving permission.
    """

    def load(_scope: object) -> ReleaseHistoryPage:
        pointer = (
            SchedulingReleasePointer.objects.filter(**_ownership(request))
            .only("version")
            .first()
        )
        maximum = pointer.version if pointer else 0
        if pointer:
            require_version(maximum)
        elif (
            SchedulingRelease.objects.filter(**_ownership(request)).exists()
            or SchedulingReleaseWithdrawal.objects.filter(
                **_ownership(request)
            ).exists()
        ):
            raise SchedulingUnavailableError
        if before_version is not None:
            require_version(before_version)
            if before_version > maximum + 1:
                raise SchedulingUnavailableError
            maximum = before_version - 1
        minimum = max(1, maximum - RELEASE_HISTORY_PAGE_SIZE + 1)
        entries = []
        for model, operation in (
            (SchedulingRelease, Op.RELEASE_PUBLISH),
            (SchedulingReleaseWithdrawal, Op.RELEASE_WITHDRAW),
        ):
            fields: tuple[str, ...] = (*_EVIDENCE_FIELDS, "pointer_version")
            if model is SchedulingReleaseWithdrawal:
                fields += ("release_id",)
            rows = (
                model.objects.filter(
                    **_ownership(request),
                    pointer_version__gte=minimum,
                    pointer_version__lte=maximum,
                )
                .select_related("command_receipt")
                .only(*fields)
                .order_by("-pointer_version")[: RELEASE_HISTORY_PAGE_SIZE + 1]
            )
            for row in rows:
                _authentic(row, operation, row.pointer_version)
                entries.append(
                    ReleaseHistoryEntry(
                        row.id,
                        row.id
                        if isinstance(row, SchedulingRelease)
                        else row.release_id,
                        operation,
                        row.pointer_version,
                        row.actor_id,
                        row.reason,
                        row.occurred_at,
                    )
                )
        entries.sort(key=lambda row: row.version, reverse=True)
        if tuple(row.version for row in entries) != tuple(
            range(maximum, minimum - 1, -1)
        ):
            raise SchedulingUnavailableError
        return ReleaseHistoryPage(tuple(entries), minimum if minimum > 1 else None)

    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS,
        purpose="release_history",
        authorizer=authorizer,
        loader=load,
    )
