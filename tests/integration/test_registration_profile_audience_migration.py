from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tests.factories import AccountFactory, EventEditionFactory
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = ("registration", "0038_governed_registration_commerce")
REGISTRATION_AFTER = (
    "registration",
    "0039_profile_audiences_and_platform_starter",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def _legacy_field(
    field_model: object,
    *,
    edition: object,
    actor: object,
    key: str,
    attendee_visible: bool,
    writer_policy: str,
    active: bool = False,
) -> object:
    return field_model.objects.create(
        id=uuid4(),
        organization_id=edition.organization_id,
        edition_id=edition.id,
        key=key,
        version=1,
        label=f"Legacy {key}",
        help_text="Synthetic migration fixture.",
        field_type="short_text",
        options=[],
        purpose="Verify the exact audience-policy migration.",
        classification="C2",
        attendee_visible=attendee_visible,
        writer_policy=writer_policy,
        required=False,
        position=0,
        review_status="approved" if active else "pending",
        status="active" if active else "draft",
        created_in_setup_version=1,
        last_changed_in_setup_version=1,
        created_by_id=actor.id,
        approved_by_id=actor.id if active else None,
        approved_at=(timezone.now() - timedelta(seconds=1)) if active else None,
    )


def test_profile_audience_backfill_and_compatible_reverse_are_exact() -> None:
    before = _migrate(REGISTRATION_BEFORE)
    edition = EventEditionFactory()
    actor = AccountFactory()
    legacy_field = before.loader.project_state(
        _targets(before, REGISTRATION_BEFORE)
    ).apps.get_model("registration", "RegistrationProfileExtensionField")
    visible = _legacy_field(
        legacy_field,
        edition=edition,
        actor=actor,
        key="legacy-visible",
        attendee_visible=True,
        writer_policy="attendee_and_staff",
    )
    staff = _legacy_field(
        legacy_field,
        edition=edition,
        actor=actor,
        key="legacy-staff",
        attendee_visible=False,
        writer_policy="registration_staff",
    )
    active = _legacy_field(
        legacy_field,
        edition=edition,
        actor=actor,
        key="legacy-active",
        attendee_visible=True,
        writer_policy="attendee_and_staff",
        active=True,
    )

    after = _migrate(REGISTRATION_AFTER)
    audience_field = after.loader.project_state(
        _targets(after, REGISTRATION_AFTER)
    ).apps.get_model("registration", "RegistrationProfileExtensionField")
    assert audience_field.objects.get(pk=visible.pk).audience_policy == "self"
    assert (
        audience_field.objects.get(pk=staff.pk).audience_policy == "registration_staff"
    )
    upgraded_active = audience_field.objects.get(pk=active.pk)
    assert upgraded_active.audience_policy == "self"

    with pytest.raises(IntegrityError), transaction.atomic():
        audience_field.objects.filter(pk=active.pk).update(label="Disallowed mutation")
    upgraded_active.refresh_from_db()
    assert upgraded_active.label == "Legacy legacy-active"

    _migrate(REGISTRATION_BEFORE)
    _migrate(REGISTRATION_AFTER)
