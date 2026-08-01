"""Read-only public queries over durable domain-event envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from maru.effects.models import DomainEvent


@dataclass(frozen=True, slots=True)
class AggregateDomainFact:
    event_name: str
    occurred_at: datetime
    actor_id: UUID | None
    payload: dict[str, object]


def aggregate_domain_facts(
    *,
    organization_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    allowed_event_names: frozenset[str],
    limit: int,
) -> tuple[AggregateDomainFact, ...]:
    """Return a bounded, tenant-scoped stream for an allowlisted aggregate."""

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
