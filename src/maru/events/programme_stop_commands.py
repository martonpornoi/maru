"""Accountable terminal Programme stop without full-convention closure side effects."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.scheduling.inputs import SchedulingCommandRequest
from maru.scheduling.release_changes import record_events_release_change
from maru.scheduling.release_inputs import ReleaseWithdrawalIntent
from maru.scheduling.release_publication_commands import withdraw_programme_release

from .models import EditionLifecycleTransition, ProgrammeStopReceipt
from .programme_stop_composition import _collect_locked_preview, _locked_stop_scope
from .programme_stop_inputs import (
    ProgrammeStopInput,
    normalize_programme_stop_input,
    programme_stop_request_digest,
)
from .programme_stop_readiness import programme_stop_command_is_ready
from .programme_stop_writer import _programme_stop_writer

if TYPE_CHECKING:
    from .models import EventEdition


@dataclass(frozen=True, slots=True)
class ProgrammeStopResult:
    """Identify one immutable terminal outcome, not a new operating permission.

    Attributes
    ----------
    receipt_id, edition_id
        Exact retained Events outcome and adoption.
    aggregate_version, lifecycle_version
        Resulting terminal versions; ordinary operation cannot reopen them.
    replayed
        Whether the original authorized identical outcome was returned again.
    """

    receipt_id: UUID
    edition_id: UUID
    aggregate_version: int
    lifecycle_version: int
    replayed: bool


def _result(receipt: ProgrammeStopReceipt, *, replayed: bool) -> ProgrammeStopResult:
    return ProgrammeStopResult(
        receipt.id,
        receipt.edition_id,
        receipt.expected_aggregate_version + 1,
        receipt.expected_lifecycle_version + 1,
        replayed=replayed,
    )


def _validate_trace(correlation_id: UUID, source_channel: str) -> None:
    if (
        type(correlation_id) is not UUID
        or not correlation_id.int
        or type(source_channel) is not str
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", source_channel, re.ASCII) is None
    ):
        raise ValidationError(
            "Use an exact command trace.", code="programme_stop_trace"
        )


def stop_programme(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    details: ProgrammeStopInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-stop",
) -> ProgrammeStopResult:
    """Stop exactly the confirmed adoption and preserve accountable retained work.

    Parameters
    ----------
    actor_id : UUID
        Actual ordinary controller; never a supplied alternate approver.
    organization_id, edition_id : UUID
        Exact adopted tenant and edition.
    details : ProgrammeStopInput
        Original displayed versions, complete preview digest and accountable reason.
    idempotency_key : UUID
        Original non-nil confirmation key, retained for a lost-response retry.
    correlation_id : UUID
        Trusted non-nil trace; a replay may have a new trace.
    source_channel : str, default='programme-stop'
        Bounded trusted transport origin, not part of original intent identity.

    Returns
    -------
    ProgrammeStopResult
        Original immutable outcome after the complete local transaction succeeds.

    Raises
    ------
    ValidationError
        For invalid, changed, stale, terminal or natively unavailable intent.
    AuthorizationDenied
        If actual current stop or necessary withdrawal authority is unavailable.

    Notes
    -----
    Withdrawal uses Scheduling's public command and actual current actor. Any
    failure rolls back withdrawal, terminal transition, audit, event and receipt
    together. There is no Participation snapshot, automatic grant revocation,
    manufactured completion, server shutdown or external notification. Callers
    inside an outer transaction must also commit that transaction before reporting
    success; an in-memory result is never a commit acknowledgement.
    """
    intent = normalize_programme_stop_input(details)
    digest = programme_stop_request_digest(
        intent,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
    )
    _validate_trace(correlation_id, source_channel)
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    key_hash = hashlib.sha256(str(idempotency_key).encode()).hexdigest()

    def record(
        *, outcome: str, reason_code: str, mutation: bool = False
    ) -> AuditRecord:
        return AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="events.transition",
            operation="events.edition.transition"
            if mutation
            else "events.programme_stop.command",
            target_type="events.event_edition",
            target_id=edition_id if outcome == "allow" else None,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            source_channel=source_channel,
            idempotency_key_hash=key_hash,
            obligations=("audit",),
            retention_class="programme-restricted",
            changed_fields=("lifecycle", "lifecycle_version", "aggregate_version")
            if mutation
            else (),
        )

    def execute_locked(edition: EventEdition) -> ProgrammeStopResult:
        if not programme_stop_command_is_ready():
            raise ValidationError(
                "Programme stop is unavailable.", code="programme_stop_source"
            )
        retained = ProgrammeStopReceipt.objects.filter(
            actor_id=actor_id, idempotency_key=idempotency_key
        ).first()
        if retained is not None:
            if (
                retained.organization_id != organization_id
                or retained.edition_id != edition_id
                or retained.request_digest != digest
            ):
                raise ValidationError(
                    "This key belongs to different original intent.",
                    code="programme_stop_idempotency_conflict",
                )
            append_audit(record(outcome="allow", reason_code="programme_stop_replayed"))
            return _result(retained, replayed=True)
        if (
            edition.aggregate_version != intent.expected_aggregate_version
            or edition.lifecycle_version != intent.expected_lifecycle_version
        ):
            raise ValidationError(
                "The edition changed; review a new stop preview.",
                code="programme_stop_version_conflict",
            )
        preview = _collect_locked_preview(
            actor_id=actor_id, edition=edition, correlation_id=correlation_id
        )
        if preview.fingerprint != intent.preview_fingerprint:
            raise ValidationError(
                "Affected work changed; review and confirm a new preview.",
                code="programme_stop_preview_conflict",
            )
        withdrawal = None
        if preview.scheduling.active_release_id is not None:
            if not preview.scheduling.withdrawal_authorized:
                raise AuthorizationDenied(
                    "Current release withdrawal authority is required.",
                    reason_code="programme_stop_withdrawal_required",
                )
            withdrawn = withdraw_programme_release(
                SchedulingCommandRequest(
                    **scope,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    reason=intent.reason,
                    source_channel=source_channel,
                ),
                intent=ReleaseWithdrawalIntent(
                    active_release_id=preview.scheduling.active_release_id,
                    expected_release_version=preview.scheduling.pointer_version,
                ),
            )
            withdrawal = {
                "receipt_id": str(withdrawn.receipt_id),
                "object_id": str(withdrawn.object_id),
                "version": withdrawn.version,
                "control_version": withdrawn.control_version,
            }
        require_programme_stop_controller(**scope)
        previous = edition.lifecycle
        edition.lifecycle = "archived"
        edition.lifecycle_version += 1
        edition.aggregate_version += 1
        edition.save(
            update_fields=(
                "lifecycle",
                "lifecycle_version",
                "aggregate_version",
                "updated_at",
            )
        )
        transition = EditionLifecycleTransition.objects.create(
            edition=edition,
            from_state=previous,
            to_state="archived",
            actor_id=actor_id,
            reason=intent.reason,
        )
        with audited_mutation(
            record(
                outcome="allow",
                reason_code="programme_stop_confirmed",
                mutation=True,
            )
        ) as evidence:
            record_events_release_change(evidence)
            publish_domain_event(
                DomainEventRecord(
                    event_name="events.edition.lifecycle_transitioned.v1",
                    schema_version=1,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    aggregate_type="events.event_edition",
                    aggregate_id=edition_id,
                    aggregate_version=edition.aggregate_version,
                    payload={"from_state": previous, "to_state": "archived"},
                    correlation_id=correlation_id,
                    causation_id=evidence.audit_id,
                    actor_kind="account",
                    actor_id=actor_id,
                ),
                workload_pool="core",
            )
            with _programme_stop_writer():
                receipt = ProgrammeStopReceipt.objects.create(
                    **scope,
                    transition_id=transition.id,
                    source_audit_id=evidence.audit_id,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                    preview_fingerprint=intent.preview_fingerprint,
                    previous_lifecycle=previous,
                    expected_aggregate_version=intent.expected_aggregate_version,
                    expected_lifecycle_version=intent.expected_lifecycle_version,
                    impact_document={
                        "preview": preview.document(),
                        "withdrawal": withdrawal,
                    },
                    reason=intent.reason,
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                )
        return _result(receipt, replayed=False)

    try:
        with _locked_stop_scope(**scope) as edition:
            result = execute_locked(edition)
    except AuthorizationDenied:
        append_audit(record(outcome="deny", reason_code="programme_stop_unavailable"))
        raise
    except ValidationError:
        append_audit(record(outcome="error", reason_code="programme_stop_conflict"))
        raise
    return result
