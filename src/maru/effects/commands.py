"""Authorized operator commands for durable effect delivery."""

from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.policy import decide, resolve_organization_target
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import OutboxMessage
from maru.effects.queries import (
    EffectReplayReceiptProjection,
    effect_replay_history,
)
from maru.effects.services import (
    normalize_effect_replay_reason,
    replay_quarantined_effect,
)
from maru.identity.models import Account

REPLAY_CAPABILITY = "effects.replay"


def _raise_unavailable() -> Never:
    raise AuthorizationDenied(
        "The effect is unavailable.",
        reason_code="effect_unavailable",
    )


def _append_replay_audit(
    *,
    actor: Account,
    organization_id: UUID,
    message_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...],
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code=REPLAY_CAPABILITY,
            operation="effects.outbox.replay",
            target_type="effects.outbox_message",
            target_id=message_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            obligations=obligations,
            changed_fields=(
                ("status", "available_at", "max_attempts", "replay_count")
                if outcome == AuditEvent.Outcome.ALLOW
                else ()
            ),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def _append_replay_history_audit(
    *,
    actor: Account,
    organization_id: UUID,
    message_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...],
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code=REPLAY_CAPABILITY,
            operation="effects.outbox.replay_history.read",
            target_type="effects.outbox_message",
            target_id=message_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            obligations=obligations,
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def inspect_effect_replay_history(
    *,
    actor: Account,
    organization_id: UUID,
    message_id: UUID,
    limit: int,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> tuple[EffectReplayReceiptProjection, ...]:
    """Authorize, audit, and return bounded operator replay rationale.

    Parameters
    ----------
    actor : Account
        Authenticated account requesting the sensitive operational history.
    organization_id : UUID
        Explicit tenant boundary for the read.
    message_id : UUID
        Outbox message identifier within the requested tenant.
    limit : int
        Maximum number of newest receipts to return.
    correlation_id : UUID
        Correlation identifier for the administrative read.
    request_id : UUID | None, default=None
        Incoming request identifier, when one exists.
    source_channel : str, default='service'
        Closed source channel for audit evidence.

    Returns
    -------
    tuple[EffectReplayReceiptProjection, ...]
        Tenant-scoped newest-first replay rationale.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the scoped replay capability.
    ValidationError
        If the requested result bound is invalid.
    """
    decision = decide(
        principal=actor,
        capability_code=REPLAY_CAPABILITY,
        resource=resolve_organization_target(organization_id=organization_id),
    )
    obligations = tuple(sorted(require_capability(REPLAY_CAPABILITY).obligations))
    if not decision.allowed:
        _append_replay_history_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=decision.reason_code,
            obligations=obligations,
        )
        raise AuthorizationDenied(
            "Effect replay history is not permitted.",
            reason_code=decision.reason_code,
        )
    try:
        history = effect_replay_history(
            organization_id=organization_id,
            message_id=message_id,
            limit=limit,
        )
    except ValidationError as error:
        _append_replay_history_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code=(
                getattr(error, "code", None) or "effect_replay_history_invalid"
            ),
            obligations=obligations,
        )
        raise
    _append_replay_history_audit(
        actor=actor,
        organization_id=organization_id,
        message_id=message_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        outcome=AuditEvent.Outcome.ALLOW,
        reason_code=decision.reason_code,
        obligations=obligations,
    )
    return history


def replay_effect(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    organization_id: UUID,
    message_id: UUID,
    additional_attempts: int,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> OutboxMessage:
    """Replay one tenant-owned quarantined effect with authorization and audit.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    message_id : UUID
        The message identifier within the requested scope.
    additional_attempts : int
        The additional attempts applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    OutboxMessage
        The resolved OutboxMessage for replay effect.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = decide(
        principal=actor,
        capability_code=REPLAY_CAPABILITY,
        resource=resolve_organization_target(organization_id=organization_id),
    )
    obligations = tuple(sorted(require_capability(REPLAY_CAPABILITY).obligations))
    if not decision.allowed:
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=decision.reason_code,
            obligations=obligations,
        )
        raise AuthorizationDenied(
            "Effect replay is not permitted.",
            reason_code=decision.reason_code,
        )

    try:
        normalized_reason = normalize_effect_replay_reason(reason)
    except ValidationError as error:
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code=error.code or "reason_invalid",
            obligations=obligations,
        )
        raise ValidationError({"reason": error}) from error

    try:
        with transaction.atomic():
            message = (
                OutboxMessage.objects.select_for_update()
                .filter(
                    pk=message_id,
                    organization_id=organization_id,
                )
                .first()
            )
            if message is None:
                _raise_unavailable()
            replayed = replay_quarantined_effect(
                message_id=message.id,
                additional_attempts=additional_attempts,
                actor_id=actor.id,
                reason=normalized_reason,
                correlation_id=correlation_id,
            )
            _append_replay_audit(
                actor=actor,
                organization_id=organization_id,
                message_id=message_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
                obligations=obligations,
            )
            return replayed
    except AuthorizationDenied as error:
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=error.reason_code,
            obligations=obligations,
        )
        raise
    except ValidationError as error:
        reason_code = getattr(error, "code", None) or "effect_replay_invalid"
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code=reason_code,
            obligations=obligations,
        )
        raise
    except Exception:
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="effect_replay_failed",
            obligations=obligations,
        )
        raise
