"""Independent candidate manifests and reasoned retained copy/restore operations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    MANAGE_CANDIDATES,
    VIEW_HISTORY,
    authorize_scheduling_scope,
)
from .catalogs import (
    MAX_CANDIDATE_REVISIONS,
    MAX_CANDIDATES,
    MAX_OCCURRENCES,
    MAX_TITLE_LENGTH,
    SchedulingOperation,
)
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    _CommandTransaction,
    _execute,
    _require_current_version,
)
from .inputs import (
    SchedulingCommandRequest,
    normalized_text,
    require_identifier,
    require_version,
    scheduling_digest,
)
from .models import (
    SchedulingCandidate,
    SchedulingCandidateMember,
    SchedulingCandidateRevision,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult

type _Manifest = tuple[tuple[UUID, UUID], ...]


def _manifest_digest(members: _Manifest) -> str:
    return scheduling_digest(
        {
            "members": [
                {"occurrence_id": str(occurrence_id), "placement_id": str(placement_id)}
                for occurrence_id, placement_id in sorted(
                    members, key=lambda pair: str(pair[0])
                )
            ]
        }
    )


def _load_manifest(revision: SchedulingCandidateRevision) -> _Manifest:
    members = tuple(
        SchedulingCandidateMember.objects.filter(
            organization_id=revision.organization_id,
            edition_id=revision.edition_id,
            revision=revision,
        )
        .order_by("occurrence_id")
        .values_list("occurrence_id", "placement_id")[: MAX_OCCURRENCES + 1]
    )
    if (
        len(members) > MAX_OCCURRENCES
        or len(members) != revision.placement_count
        or _manifest_digest(members) != revision.manifest_digest
    ):
        raise SchedulingUnavailableError
    return members


def _locked_candidate(
    context: _CommandTransaction,
    candidate_id: UUID,
    expected_version: int,
    *,
    terminal: bool = False,
) -> SchedulingCandidate:
    candidate = (
        SchedulingCandidate.objects.select_for_update()
        .filter(
            **context.ownership(),
            id=candidate_id,
        )
        .first()
    )
    if candidate is None:
        raise SchedulingUnavailableError
    _require_current_version(candidate.aggregate_version, expected_version)
    if candidate.lifecycle != "draft":
        raise SchedulingLifecycleConflictError
    if not terminal and candidate.aggregate_version >= MAX_CANDIDATE_REVISIONS:
        raise SchedulingLimitError
    return candidate


def _current_revision(candidate: SchedulingCandidate) -> SchedulingCandidateRevision:
    revision = SchedulingCandidateRevision.objects.filter(
        organization_id=candidate.organization_id,
        edition_id=candidate.edition_id,
        candidate=candidate,
        sequence=candidate.aggregate_version,
    ).first()
    if revision is None:
        raise SchedulingUnavailableError
    return revision


def _append_revision(
    context: _CommandTransaction,
    candidate: SchedulingCandidate,
    *,
    operation: SchedulingOperation,
    label: str,
    members: _Manifest,
    source: SchedulingCandidateRevision | None = None,
    introduce: Callable[[SchedulingCandidateRevision], None] | None = None,
) -> SchedulingCandidateRevision:
    if len(members) > MAX_OCCURRENCES or len({item for item, _ in members}) != len(
        members
    ):
        raise SchedulingLimitError
    revision = SchedulingCandidateRevision.objects.create(
        **context.evidence(),
        candidate=candidate,
        sequence=candidate.aggregate_version,
        label=label,
        operation=operation.value,
        source_revision=source,
        placement_count=len(members),
        manifest_digest=_manifest_digest(members),
    )
    if introduce is not None:
        introduce(revision)
    SchedulingCandidateMember.objects.bulk_create(
        [
            SchedulingCandidateMember(
                **context.ownership(),
                revision=revision,
                occurrence_id=occurrence_id,
                placement_id=placement_id,
            )
            for occurrence_id, placement_id in members
        ]
    )
    return revision


def _create_candidate(context: _CommandTransaction) -> SchedulingCandidate:
    if (
        SchedulingCandidate.objects.filter(**context.ownership()).count()
        >= MAX_CANDIDATES
    ):
        raise SchedulingLimitError
    return SchedulingCandidate.objects.create(
        **context.ownership(),
        aggregate_version=1,
        created_by_id=context.request.actor_id,
    )


def _advance(candidate: SchedulingCandidate, *, archive: bool = False) -> None:
    candidate.aggregate_version += 1
    if archive:
        candidate.lifecycle = "archived"
    candidate.save(update_fields=("aggregate_version", "lifecycle", "updated_at"))


def _historical_source(
    request: SchedulingCommandRequest,
    revision_id: UUID,
    authorizer: SchedulingAuthorizer,
) -> tuple[SchedulingCandidateRevision, _Manifest]:
    authorize_scheduling_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=VIEW_HISTORY,
        requested_fields=frozenset({"planning_history"}),
        authorizer=authorizer,
    )
    revision = SchedulingCandidateRevision.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        id=revision_id,
    ).first()
    if revision is None:
        raise SchedulingUnavailableError
    members = _load_manifest(revision)
    scope = authorize_scheduling_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=VIEW_HISTORY,
        requested_fields=frozenset({"planning_history"}),
        authorizer=authorizer,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code=VIEW_HISTORY,
            operation="scheduling.query.history_source",
            target_type="scheduling.candidate_revision",
            target_id=revision.id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel=request.source_channel,
            obligations=tuple(
                sorted(scope.decision.obligations | {"audit_sensitive_read"})
            ),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": "candidate_history_copy_or_restore",
            },
            retention_class="programme-restricted",
        )
    )
    return revision, members


def create_scheduling_candidate(
    request: SchedulingCommandRequest,
    *,
    label: str,
    expected_control_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Create an empty private candidate with no reservation or public state.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution, inspectable action reason and exact retry key.
    label : str
        Explicit bounded private candidate label.
    expected_control_version : int
        Current Scheduling edition control, or zero before its first command.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        New candidate identifier and immutable empty first manifest.
    """

    def normalize() -> str:
        require_version(expected_control_version, initial=True)
        return normalized_text(label, maximum=MAX_TITLE_LENGTH)

    def write(
        context: _CommandTransaction, title: str, _prepared: None
    ) -> tuple[UUID, int]:
        _require_current_version(
            context.prior_control_version, expected_control_version
        )
        candidate = _create_candidate(context)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.CANDIDATE_CREATE,
            label=title,
            members=(),
        )
        return candidate.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.CANDIDATE_CREATE,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda title: {
            "label": title,
            "expected_control_version": expected_control_version,
        },
        prepare=lambda _intent: None,
        write=write,
        authorizer=authorizer,
    )


def copy_scheduling_candidate(
    request: SchedulingCommandRequest,
    *,
    source_revision_id: UUID,
    label: str,
    expected_control_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Copy one explicitly authorized immutable revision into an independent draft.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution and explicit copy rationale.
    source_revision_id : UUID
        Exact historical manifest requiring independent history-read authority.
    label : str
        Deliberate new candidate label, not a mutation of the source.
    expected_control_version : int
        Current Scheduling edition control.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy proving both candidate management and history-read fields.

    Returns
    -------
    SchedulingCommandResult
        New candidate identity retaining the same stable occurrence placements.
    """

    def normalize() -> str:
        require_identifier(source_revision_id)
        require_version(expected_control_version)
        return normalized_text(label, maximum=MAX_TITLE_LENGTH)

    def write(
        context: _CommandTransaction,
        title: str,
        prepared: tuple[SchedulingCandidateRevision, _Manifest],
    ) -> tuple[UUID, int]:
        _require_current_version(
            context.prior_control_version, expected_control_version
        )
        source, members = prepared
        candidate = _create_candidate(context)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.CANDIDATE_COPY,
            label=title,
            members=members,
            source=source,
        )
        return candidate.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.CANDIDATE_COPY,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda title: {
            "source_revision_id": str(source_revision_id),
            "label": title,
            "expected_control_version": expected_control_version,
        },
        prepare=lambda _intent: _historical_source(
            request, source_revision_id, authorizer
        ),
        write=write,
        authorizer=authorizer,
    )


def restore_scheduling_candidate(
    request: SchedulingCommandRequest,
    *,
    candidate_id: UUID,
    source_revision_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Restore retained intent as a new revision, not as historical approval.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution and explicit human restoration rationale.
    candidate_id : UUID
        Exact current draft being changed.
    source_revision_id : UUID
        Historical revision of this same candidate requiring history-read authority.
    expected_version : int
        Exact current candidate version.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy proving independent history-read and mutation authority.

    Returns
    -------
    SchedulingCommandResult
        Same candidate with a new immutable revision; dependencies need reevaluation.
    """

    def normalize() -> UUID:
        require_identifier(candidate_id)
        require_version(expected_version)
        return require_identifier(source_revision_id)

    def write(
        context: _CommandTransaction,
        _identifier: UUID,
        prepared: tuple[SchedulingCandidateRevision, _Manifest],
    ) -> tuple[UUID, int]:
        candidate = _locked_candidate(context, candidate_id, expected_version)
        source, members = prepared
        if source.candidate_id != candidate.id:
            raise SchedulingUnavailableError
        _advance(candidate)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.CANDIDATE_RESTORE,
            label=source.label,
            members=members,
            source=source,
        )
        return candidate.id, candidate.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.CANDIDATE_RESTORE,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda identifier: {
            "candidate_id": str(candidate_id),
            "source_revision_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda identifier: _historical_source(request, identifier, authorizer),
        write=write,
        authorizer=authorizer,
    )


def archive_scheduling_candidate(
    request: SchedulingCommandRequest,
    *,
    candidate_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Archive a draft while retaining its complete last manifest and history.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution and explicit human archival rationale.
    candidate_id : UUID
        Exact draft to archive; this does not cancel any independent room hold.
    expected_version : int
        Exact current candidate version, including its last permitted draft revision.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        Retained candidate and final archival revision, never a deletion.
    """

    def normalize() -> UUID:
        require_version(expected_version)
        return require_identifier(candidate_id)

    def write(
        context: _CommandTransaction, identifier: UUID, _prepared: None
    ) -> tuple[UUID, int]:
        candidate = _locked_candidate(
            context, identifier, expected_version, terminal=True
        )
        current = _current_revision(candidate)
        members = _load_manifest(current)
        _advance(candidate, archive=True)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.CANDIDATE_ARCHIVE,
            label=current.label,
            members=members,
        )
        return candidate.id, candidate.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.CANDIDATE_ARCHIVE,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda identifier: {
            "candidate_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda _intent: None,
        write=write,
        authorizer=authorizer,
    )


def remove_scheduling_placement(
    request: SchedulingCommandRequest,
    *,
    candidate_id: UUID,
    occurrence_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Unplace an occurrence from only this draft's new manifest.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution and inspectable removal reason.
    candidate_id : UUID
        Exact draft whose membership will change.
    occurrence_id : UUID
        Stable occurrence currently placed in this candidate.
    expected_version : int
        Exact current candidate version.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        New candidate revision; occurrence, old placements and other drafts survive.
    """

    def normalize() -> UUID:
        require_identifier(candidate_id)
        require_version(expected_version)
        return require_identifier(occurrence_id)

    def write(
        context: _CommandTransaction, identifier: UUID, _prepared: None
    ) -> tuple[UUID, int]:
        candidate = _locked_candidate(context, candidate_id, expected_version)
        current = _current_revision(candidate)
        members = _load_manifest(current)
        remaining = tuple(pair for pair in members if pair[0] != identifier)
        if len(remaining) == len(members):
            raise SchedulingUnavailableError
        _advance(candidate)
        _append_revision(
            context,
            candidate,
            operation=SchedulingOperation.PLACEMENT_REMOVE,
            label=current.label,
            members=remaining,
        )
        return candidate.id, candidate.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.PLACEMENT_REMOVE,
        capability=MANAGE_CANDIDATES,
        normalize=normalize,
        payload=lambda identifier: {
            "candidate_id": str(candidate_id),
            "occurrence_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda _intent: None,
        write=write,
        authorizer=authorizer,
    )
