"""Value-minimized record activity assembled from public module queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from maru.effects.queries import AggregateDomainFact, aggregate_domain_facts
from maru.identity.queries import account_display_labels

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

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
    """Describe record activity.

    Attributes
    ----------
    action
        The stable action code describing the requested transition.
    actor_label
        The human-readable actor label shown to authorized readers.
    changed_field_labels
        The changed field labels retained in this immutable projection.
    occurred_at
        The timezone-aware timestamp for occurred.
    """

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
    """Project allowlisted domain facts without exposing values or audit data.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    aggregate_type : str
        The stable domain type of the target aggregate.
    aggregate_id : UUID
        The aggregate identifier whose state is being read or changed.
    time_zone : str
        The IANA time-zone name used for localized presentation.
    limit : int, default=20
        The maximum number of records to return.

    Returns
    -------
    tuple[RecordActivity, ...]
        The matching record activity records in deterministic order.
    """
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
