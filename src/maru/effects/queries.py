"""Read-only public queries over durable domain-event envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.effects.models import DomainEvent

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


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
