from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from maru.activity.queries import record_activity
from maru.effects.models import DomainEvent
from tests.factories import AccountFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _event(
    *,
    organization_id: UUID,
    aggregate_id: UUID,
    aggregate_version: int,
    event_name: str = "organizations.convention_series.updated.v1",
    actor_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> DomainEvent:
    return DomainEvent.objects.create(
        event_name=event_name,
        schema_version=1,
        occurred_at=timezone.now() + timedelta(seconds=aggregate_version),
        organization_id=organization_id,
        event_edition_id=None,
        aggregate_type="organizations.convention_series",
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        payload=payload or {"changed_fields": "name"},
        correlation_id=uuid4(),
        causation_id=None,
        actor_kind="account" if actor_id is not None else "system",
        actor_id=actor_id,
    )


def test_record_activity_is_tenant_scoped_allowlisted_and_value_minimized() -> None:
    organization = OrganizationFactory()
    other_organization = OrganizationFactory()
    aggregate_id = uuid4()
    actor = AccountFactory(display_name="Visible operator")
    _event(
        organization_id=organization.id,
        aggregate_id=aggregate_id,
        aggregate_version=1,
        actor_id=actor.id,
        payload={
            "changed_fields": "name,description,private_note",
            "name": "Secret entered value",
        },
    )
    _event(
        organization_id=organization.id,
        aggregate_id=aggregate_id,
        aggregate_version=2,
        event_name="internal.unapproved_fact.v1",
        payload={"changed_fields": "name"},
    )
    _event(
        organization_id=other_organization.id,
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"changed_fields": "website_url"},
    )

    activity = record_activity(
        organization_id=organization.id,
        aggregate_type="organizations.convention_series",
        aggregate_id=aggregate_id,
        time_zone="Europe/Budapest",
    )

    assert len(activity) == 1
    assert activity[0].action == "Updated convention series"
    assert activity[0].actor_label == "Visible operator"
    assert activity[0].changed_field_labels == ("name", "description")
    assert "Secret entered value" not in repr(activity[0])
    assert "private_note" not in repr(activity[0])


def test_record_activity_uses_current_safe_actor_label_and_fallbacks() -> None:
    organization = OrganizationFactory()
    aggregate_id = uuid4()
    actor = AccountFactory(display_name="Old label")
    _event(
        organization_id=organization.id,
        aggregate_id=aggregate_id,
        aggregate_version=1,
        actor_id=actor.id,
    )
    _event(
        organization_id=organization.id,
        aggregate_id=aggregate_id,
        aggregate_version=2,
        actor_id=uuid4(),
    )
    _event(
        organization_id=organization.id,
        aggregate_id=aggregate_id,
        aggregate_version=3,
        actor_id=None,
    )
    actor.display_name = "Current label"
    actor.save(update_fields=("display_name",))

    activity = record_activity(
        organization_id=organization.id,
        aggregate_type="organizations.convention_series",
        aggregate_id=aggregate_id,
        time_zone="UTC",
    )

    assert [item.actor_label for item in activity] == [
        "Maru automation",
        "Maru account",
        "Current label",
    ]


def test_record_activity_enforces_the_twenty_item_ceiling() -> None:
    organization = OrganizationFactory()
    aggregate_id = uuid4()
    for aggregate_version in range(1, 26):
        _event(
            organization_id=organization.id,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
        )

    activity = record_activity(
        organization_id=organization.id,
        aggregate_type="organizations.convention_series",
        aggregate_id=aggregate_id,
        time_zone="UTC",
        limit=100,
    )

    assert len(activity) == 20
