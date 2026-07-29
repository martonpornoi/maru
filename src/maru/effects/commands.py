"""Authorized operator commands for durable effect delivery."""

from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import OutboxMessage
from maru.effects.services import replay_quarantined_effect
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


def replay_effect(
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
    """Replay one tenant-owned quarantined effect with authorization and audit."""

    decision = decide(
        principal=actor,
        capability_code=REPLAY_CAPABILITY,
        resource=ResourceScope(organization_id=organization_id),
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

    normalized_reason = reason.strip()
    if not normalized_reason:
        _append_replay_audit(
            actor=actor,
            organization_id=organization_id,
            message_id=message_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="reason_required",
            obligations=obligations,
        )
        raise ValidationError(
            {"reason": "A replay reason is required."},
            code="reason_required",
        )

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
        reason_code = error.code or "effect_replay_invalid"
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
