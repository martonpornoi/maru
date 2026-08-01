"""Value-minimized record activity assembled from public module queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from maru.effects.queries import AggregateDomainFact, aggregate_domain_facts
from maru.identity.queries import account_display_labels

_EVENT_LABELS = {
    "organizations.convention_series.created.v1": "Created convention series",
    "organizations.convention_series.updated.v1": "Updated convention series",
    "events.edition.created.v1": "Created event edition",
    "events.edition.details_updated.v1": "Updated event edition",
    "events.edition.lifecycle_transitioned.v1": "Changed edition lifecycle",
}
_ALLOWED_EVENT_NAMES = frozenset(_EVENT_LABELS)
_MAX_ACTIVITY_ITEMS = 20

_FIELD_LABELS = {
    "name": "name",
    "description": "description",
    "website_url": "website",
    "contact_email": "contact email",
    "is_active": "availability",
    "starts_on": "start date",
    "ends_on": "end date",
    "time_zone": "time zone",
    "language_codes": "languages",
    "currency_codes": "currencies",
    "lifecycle": "lifecycle",
}


@dataclass(frozen=True, slots=True)
class RecordActivity:
    action: str
    actor_label: str
    changed_field_labels: tuple[str, ...]
    occurred_at: datetime


def _changed_fields(event: AggregateDomainFact) -> tuple[str, ...]:
    raw_fields = event.payload.get("changed_fields")
    if not isinstance(raw_fields, str):
        return ()
    return tuple(
        _FIELD_LABELS[field_name]
        for field_name in raw_fields.split(",")
        if field_name in _FIELD_LABELS
    )


def record_activity(
    *,
    organization_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    time_zone: str,
    limit: int = 20,
) -> tuple[RecordActivity, ...]:
    """Project allowlisted domain facts without exposing values or audit data."""

    facts = aggregate_domain_facts(
        organization_id=organization_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        allowed_event_names=_ALLOWED_EVENT_NAMES,
        limit=min(max(limit, 1), _MAX_ACTIVITY_ITEMS),
    )
    actor_ids = {fact.actor_id for fact in facts if fact.actor_id is not None}
    actor_names = account_display_labels(actor_ids)
    zone = ZoneInfo(time_zone)
    return tuple(
        RecordActivity(
            action=_EVENT_LABELS[fact.event_name],
            actor_label=(
                actor_names.get(fact.actor_id, "Maru account")
                if fact.actor_id is not None
                else "Maru automation"
            ),
            changed_field_labels=_changed_fields(fact),
            occurred_at=fact.occurred_at.astimezone(zone),
        )
        for fact in facts
    )
