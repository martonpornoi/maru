"""Governed exact notices: independent review, manual handoff and genuine self ack."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import connection

from .authorization import (
    ACKNOWLEDGE_CHANGE_SELF,
    DEFAULT_SCHEDULING_AUTHORIZER,
    HANDOFF_CHANGE_NOTICES,
    PREPARE_CHANGE_NOTICES,
    REVIEW_CHANGE_NOTICES,
)
from .catalogs import MAX_RELEASE_DEPENDENCY_USES, SchedulingOperation
from .change_catalogs import MAX_CHANGE_NOTICES, ChangeNoticeAction
from .change_lifecycle import advance_change_notice
from .change_notice_queries import (
    load_personal_programme_change_notice,
    load_programme_change_notice,
    preview_programme_change_notice,
)
from .change_notice_records import _record
from .change_notice_sources import _approval_ids, _generation_digest
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
    _CommandTransaction,
    _execute,
)
from .inputs import SchedulingCommandRequest
from .models import (
    SchedulingChangeNotice,
    SchedulingChangeNoticeEvidence,
    SchedulingCommandReceipt,
    SchedulingRelease,
    SchedulingReleaseApprovalDependency,
    SchedulingReleaseDependencyKey,
)
from .planning_queries import SchedulingReadRequest
from .writer_boundary import require_scheduling_writer

if TYPE_CHECKING:
    from .change_inputs import ChangeNoticeDecisionIntent, PrepareChangeNoticeIntent
    from .change_notice_sources import ProgrammeChangeNoticePreview
    from .command_support import SchedulingCommandResult


_ACKNOWLEDGEMENT_REASON = "Exact recipient acknowledged this Programme change."
_OPERATIONS = {
    ChangeNoticeAction.APPROVE: (
        SchedulingOperation.CHANGE_APPROVE,
        REVIEW_CHANGE_NOTICES,
    ),
    ChangeNoticeAction.REJECT: (
        SchedulingOperation.CHANGE_REJECT,
        REVIEW_CHANGE_NOTICES,
    ),
    ChangeNoticeAction.HANDOFF: (
        SchedulingOperation.CHANGE_HANDOFF,
        HANDOFF_CHANGE_NOTICES,
    ),
    ChangeNoticeAction.ACKNOWLEDGE: (
        SchedulingOperation.CHANGE_ACKNOWLEDGE,
        ACKNOWLEDGE_CHANGE_SELF,
    ),
}


def _read_request(request: SchedulingCommandRequest) -> SchedulingReadRequest:
    return SchedulingReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    )


def _freeze_sources(
    request: SchedulingReadRequest, preview: ProgrammeChangeNoticePreview
) -> None:
    # All owner/person reads and their canonical locks must precede this function.
    # After key locks, perform no further owner reads/locks. Source writers may
    # wait on these keys; a key-holder must not then wait on their source rows.
    require_scheduling_writer()
    if not connection.in_atomic_block:
        raise SchedulingUnavailableError
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone() != ("read committed",):
            raise SchedulingUnavailableError
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    release = SchedulingRelease.objects.filter(
        **ownership, id=preview.release_id
    ).first()
    if release is None:
        raise SchedulingUnavailableError
    ids = tuple(
        SchedulingReleaseApprovalDependency.objects.filter(
            **ownership, approval_id__in=_approval_ids(request, release)
        )
        .order_by("dependency_id")
        .values_list("dependency_id", flat=True)[: 2 * MAX_RELEASE_DEPENDENCY_USES + 1]
    )
    if not ids or len(ids) > 2 * MAX_RELEASE_DEPENDENCY_USES:
        raise SchedulingUnavailableError
    # Match release capture's kind/source ordering, not encounter/approval order.
    locked = tuple(
        SchedulingReleaseDependencyKey.objects.select_for_update()
        .filter(id__in=set(ids))
        .order_by("kind", "source_id")
        .values_list("id", flat=True)
    )
    if (
        set(locked) != set(ids)
        or _generation_digest(request, release) != preview.dependency_digest
    ):
        raise SchedulingVersionConflictError


def _prepare(
    request: SchedulingCommandRequest, intent: PrepareChangeNoticeIntent
) -> ProgrammeChangeNoticePreview:
    read = _read_request(request)
    preview = preview_programme_change_notice(
        read,
        release_id=intent.release_id,
        occurrence_id=intent.occurrence_id,
        recipient=intent.recipient,
    )
    if (preview.pointer_version, preview.snapshot_digest) != (
        intent.expected_pointer_version,
        intent.snapshot_digest,
    ):
        raise SchedulingVersionConflictError
    _freeze_sources(read, preview)
    return preview


def _write_preparation(
    context: _CommandTransaction,
    _intent: PrepareChangeNoticeIntent,
    preview: ProgrammeChangeNoticePreview,
) -> tuple[UUID, int]:
    selected = SchedulingChangeNotice.objects.filter(**context.ownership())
    if selected.count() >= MAX_CHANGE_NOTICES:
        raise SchedulingLimitError
    if selected.filter(
        recipient_id=preview.recipient_id,
        recipient_purpose=preview.recipient.purpose.value,
        recipient_target_id=preview.recipient.target_id,
        release_id=preview.release_id,
        snapshot_digest=preview.snapshot_digest,
    ).exists():
        raise SchedulingLifecycleConflictError
    notice = SchedulingChangeNotice.objects.create(
        **context.evidence(),
        id=uuid4(),
        command_receipt_id=context.receipt_id,
        release_id=preview.release_id,
        occurrence_id=preview.occurrence_id,
        recipient_id=preview.recipient_id,
        recipient_purpose=preview.recipient.purpose.value,
        recipient_target_id=preview.recipient.target_id,
        pointer_version=preview.pointer_version,
        source_state=preview.source_state.value,
        snapshot_digest=preview.snapshot_digest,
    )
    return notice.id, 1


def prepare_programme_change_notice(
    request: SchedulingCommandRequest, intent: PrepareChangeNoticeIntent
) -> SchedulingCommandResult:
    """Prepare one exact current package with independent sender and owner authority.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Trusted actual actor/scope/retry attribution with explicit preparation reason.
    intent : PrepareChangeNoticeIntent
        Exact fresh preview fingerprint, publication sequence and recipient purpose.

    Returns
    -------
    SchedulingCommandResult
        Identifier-only preparation receipt or freshly revalidated exact replay.

    Notes
    -----
    Normal validation, authorization, lifecycle, limit, stale and dependency
    errors propagate. Complete owner/person admission precedes final dependency
    locks. Atomic immutable notice, receipt, audit and dormant event do not send
    a message, approve its contents or imply recipient acknowledgement.
    """

    def replay(
        value: PrepareChangeNoticeIntent, receipt: SchedulingCommandReceipt
    ) -> None:
        detail = load_programme_change_notice(
            _read_request(request),
            notice_id=receipt.result_object_id,
        )
        preview = detail.preview
        record = _record(_read_request(request), receipt.result_object_id)
        if (
            receipt.operation != SchedulingOperation.CHANGE_PREPARE
            or receipt.resulting_version != 1
            or record.notice.command_receipt_id != receipt.id
            or record.notice.actor_id != request.actor_id
            or preview.release_id != value.release_id
            or preview.occurrence_id != value.occurrence_id
            or preview.recipient != value.recipient
            or preview.pointer_version != value.expected_pointer_version
            or preview.snapshot_digest != value.snapshot_digest
        ):
            raise SchedulingUnavailableError
        _freeze_sources(_read_request(request), preview)

    return _execute(
        request,
        operation=SchedulingOperation.CHANGE_PREPARE,
        capability=PREPARE_CHANGE_NOTICES,
        normalize=intent.validated,
        payload=lambda value: value.payload(),
        prepare=lambda value: _prepare(request, value),
        write=_write_preparation,
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        revalidate_replay=replay,
    )


@dataclass(frozen=True, slots=True)
class _Decision:
    notice_id: UUID
    sequence: int
    action: ChangeNoticeAction


def _decision_source(
    request: SchedulingCommandRequest,
    intent: ChangeNoticeDecisionIntent,
    action: ChangeNoticeAction,
) -> ProgrammeChangeNoticePreview:
    read = _read_request(request)
    if action is ChangeNoticeAction.ACKNOWLEDGE:
        preview = load_personal_programme_change_notice(
            read, notice_id=intent.notice_id
        ).preview
    else:
        preview = load_programme_change_notice(read, notice_id=intent.notice_id).preview
    if preview.snapshot_digest != intent.snapshot_digest:
        raise SchedulingVersionConflictError
    return preview


def _decide(
    request: SchedulingCommandRequest,
    intent: ChangeNoticeDecisionIntent,
    action: ChangeNoticeAction,
) -> SchedulingCommandResult:
    operation, capability = _OPERATIONS[action]
    read = _read_request(request)

    def prepare(value: ChangeNoticeDecisionIntent) -> _Decision:
        preview = _decision_source(request, value, action)
        record = _record(
            read, value.notice_id, personal=action is ChangeNoticeAction.ACKNOWLEDGE
        )
        state = advance_change_notice(
            record.state,
            actor_id=request.actor_id,
            action=action,
            expected_version=value.expected_version,
        )
        _freeze_sources(read, preview)
        return _Decision(record.notice.id, state.version, action)

    def write(
        context: _CommandTransaction,
        _value: ChangeNoticeDecisionIntent,
        prepared: _Decision,
    ) -> tuple[UUID, int]:
        fact = SchedulingChangeNoticeEvidence.objects.create(
            **context.evidence(),
            id=uuid4(),
            command_receipt_id=context.receipt_id,
            notice_id=prepared.notice_id,
            action=prepared.action.value,
            sequence=prepared.sequence,
        )
        return fact.id, fact.sequence

    def replay(
        value: ChangeNoticeDecisionIntent, receipt: SchedulingCommandReceipt
    ) -> None:
        preview = _decision_source(request, value, action)
        record = _record(
            read, value.notice_id, personal=action is ChangeNoticeAction.ACKNOWLEDGE
        )
        matching = tuple(
            fact for fact in record.facts if fact.id == receipt.result_object_id
        )
        if (
            receipt.operation != operation
            or len(matching) != 1
            or matching[0].command_receipt_id != receipt.id
            or matching[0].actor_id != request.actor_id
            or matching[0].action != action.value
            or matching[0].sequence != value.expected_version + 1
            or receipt.resulting_version != matching[0].sequence
        ):
            raise SchedulingUnavailableError
        _freeze_sources(read, preview)

    return _execute(
        request,
        operation=operation,
        capability=capability,
        normalize=intent.validated,
        payload=lambda value: value.payload(),
        prepare=prepare,
        write=write,
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        revalidate_replay=replay,
    )


def review_programme_change_notice(
    request: SchedulingCommandRequest,
    intent: ChangeNoticeDecisionIntent,
    *,
    action: ChangeNoticeAction,
) -> SchedulingCommandResult:
    """Independently approve or terminally reject one exact prepared package.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Actual reviewer and explicit restricted review rationale.
    intent : ChangeNoticeDecisionIntent
        Exact notice, source fingerprint and observed evidence version.
    action : ChangeNoticeAction
        Only APPROVE or REJECT; never inferred approval or handoff.

    Returns
    -------
    SchedulingCommandResult
        Immutable review-evidence receipt, not delivery or acknowledgement.

    Raises
    ------
    ValidationError
        If the action is not a closed review choice.

    Notes
    -----
    Shared command errors propagate. The reviewer must differ from the preparer.
    Current owner purpose, exact source and independent read/write authority are
    required again on replay, without trying to append another review.
    """
    if type(action) is not ChangeNoticeAction or action not in {
        ChangeNoticeAction.APPROVE,
        ChangeNoticeAction.REJECT,
    }:
        raise ValidationError("Choose independent approval or rejection.")
    return _decide(request, intent, action)


def handoff_programme_change_notice(
    request: SchedulingCommandRequest,
    intent: ChangeNoticeDecisionIntent,
) -> SchedulingCommandResult:
    """Record one explicit manual handoff claim for a still-current approved notice.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Actual authorized operator with deliberate manual-handoff rationale.
    intent : ChangeNoticeDecisionIntent
        Exact notice/source and current evidence version.

    Returns
    -------
    SchedulingCommandResult
        Immutable handoff fact; not provider delivery or recipient acknowledgement.

    Notes
    -----
    Shared command errors propagate. No provider, contact, general Communications
    record, attendance event or accepted Shift mutation is created.
    """
    return _decide(request, intent, ChangeNoticeAction.HANDOFF)


def acknowledge_programme_change_notice(
    request: SchedulingReadRequest,
    intent: ChangeNoticeDecisionIntent,
    *,
    idempotency_key: UUID,
) -> SchedulingCommandResult:
    """Acknowledge one's own exact current approved package without a personal reason.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted authenticated recipient and exact scope/correlation, not a selector.
    intent : ChangeNoticeDecisionIntent
        Exact notice/source and observed evidence version.
    idempotency_key : UUID
        Exact recipient's retry identity for this deliberate action.

    Returns
    -------
    SchedulingCommandResult
        Immutable exact-self acknowledgement, independent of manual handoff.

    Notes
    -----
    Shared validation and command errors propagate. No free-text personal
    explanation is accepted; attribution uses a code-owned bounded reason.
    Approval and current owner purpose remain mandatory on a replay. This does
    not acknowledge a newer material change, accept work or record attendance.
    """
    attribution = SchedulingCommandRequest(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        correlation_id=request.correlation_id,
        idempotency_key=idempotency_key,
        reason=_ACKNOWLEDGEMENT_REASON,
        source_channel="programme-change-self",
    )
    return _decide(attribution, intent, ChangeNoticeAction.ACKNOWLEDGE)
