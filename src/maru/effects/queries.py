"""Read-only public queries over durable domain-event envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.effects.models import DomainEvent, EffectReplayReceipt

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

MAX_EFFECT_REPLAY_HISTORY_RESULTS = 100


@dataclass(frozen=True, slots=True)
class AggregateDomainFact:
    """Describe aggregate domain fact.

    Attributes
    ----------
    event_name
        The human-readable event name shown to authorized readers.
    occurred_at
        The timezone-aware timestamp for occurred.
    actor_id
        The immutable identifier of the account authorizing the operation.
    payload
        The untrusted payload to validate before domain use.
    """

    event_name: str
    occurred_at: datetime
    actor_id: UUID | None
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class EffectReplayReceiptProjection:
    """Describe one bounded operator-visible replay decision.

    Attributes
    ----------
    actor_id
        Immutable identifier of the active account that authorized the replay.
    reason
        Normalized operator rationale retained with the replay decision.
    additional_attempts
        Number of delivery attempts added by this bounded replay.
    previous_max_attempts
        Attempt ceiling that applied before this replay.
    new_max_attempts
        Attempt ceiling established by this replay.
    replay_count
        Monotonic replay sequence for the outbox message.
    correlation_id
        Correlation identifier shared by the command and retained evidence.
    created_at
        Timezone-aware timestamp when the replay receipt was appended.
    """

    actor_id: UUID
    reason: str
    additional_attempts: int
    previous_max_attempts: int
    new_max_attempts: int
    replay_count: int
    correlation_id: UUID
    created_at: datetime


def effect_replay_history(
    *,
    organization_id: UUID,
    message_id: UUID,
    limit: int = 20,
) -> tuple[EffectReplayReceiptProjection, ...]:
    """Return bounded replay rationale for one tenant-owned delivery.

    Parameters
    ----------
    organization_id : UUID
        Tenant boundary for the operator query.
    message_id : UUID
        Outbox message identifier within that tenant.
    limit : int, default=20
        Maximum number of newest receipts to return, from 1 through 100.

    Returns
    -------
    tuple[EffectReplayReceiptProjection, ...]
        Newest-first immutable replay evidence. A foreign or unknown message
        returns an empty tuple without disclosing its existence.

    Raises
    ------
    ValidationError
        If the result bound is not a supported positive integer.
    """
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_EFFECT_REPLAY_HISTORY_RESULTS
    ):
        raise ValidationError(
            (
                "Effect replay history limit must be between 1 and "
                f"{MAX_EFFECT_REPLAY_HISTORY_RESULTS}."
            ),
            code="invalid_effect_replay_history_limit",
        )
    receipts = EffectReplayReceipt.objects.filter(
        organization_id=organization_id,
        outbox_message_id=message_id,
    ).order_by("-replay_count", "-created_at", "-id")[:limit]
    return tuple(
        EffectReplayReceiptProjection(
            actor_id=receipt.actor_id,
            reason=receipt.reason,
            additional_attempts=receipt.additional_attempts,
            previous_max_attempts=receipt.previous_max_attempts,
            new_max_attempts=receipt.new_max_attempts,
            replay_count=receipt.replay_count,
            correlation_id=receipt.correlation_id,
            created_at=receipt.created_at,
        )
        for receipt in receipts
    )


def aggregate_domain_facts(
    *,
    organization_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    allowed_event_names: frozenset[str],
    limit: int,
) -> tuple[AggregateDomainFact, ...]:
    """Return a bounded, tenant-scoped stream for an allowlisted aggregate.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    aggregate_type : str
        The stable domain type of the target aggregate.
    aggregate_id : UUID
        The aggregate identifier whose state is being read or changed.
    allowed_event_names : frozenset[str]
        The allowed event names used to constrain the tenant-scoped query.
    limit : int
        The maximum number of records to return.

    Returns
    -------
    tuple[AggregateDomainFact, ...]
        The matching aggregate domain facts records in deterministic order.
    """
    events = DomainEvent.objects.filter(
        organization_id=organization_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_name__in=allowed_event_names,
    ).order_by("-occurred_at", "-id")[:limit]
    return tuple(
        AggregateDomainFact(
            event_name=event.event_name,
            occurred_at=event.occurred_at,
            actor_id=event.actor_id,
            payload=event.payload,
        )
        for event in events
    )
