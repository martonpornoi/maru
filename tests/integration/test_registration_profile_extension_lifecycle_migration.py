from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tests.factories import AccountFactory, EventEditionFactory
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = (
    "registration",
    "0033_page10_definition_command_actions",
)
REGISTRATION_AFTER = (
    "registration",
    "0034_profile_extension_definition_lifecycle",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def _historical_apps(executor: MigrationExecutor, target: tuple[str, str]) -> Any:
    return executor.loader.project_state(_targets(executor, target)).apps


def _actions(executor: MigrationExecutor, target: tuple[str, str]) -> set[str]:
    apps = _historical_apps(executor, target)
    receipt = apps.get_model("registration", "RegistrationSetupCommandReceipt")
    return {str(value) for value, _label in receipt._meta.get_field("action").choices}


def _active_historical_field(
    apps: Any,
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
) -> Any:
    field_model = apps.get_model(
        "registration",
        "RegistrationProfileExtensionField",
    )
    return field_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        key="diet-note",
        version=1,
        label="Diet note",
        help_text="Record the current synthetic dietary note.",
        field_type="short_text",
        options=[],
        purpose="Maintain one current attendee preference.",
        classification="C2",
        attendee_visible=True,
        writer_policy="attendee_and_staff",
        required=False,
        position=0,
        review_status="approved",
        status="active",
        approved_by_id=actor_id,
        approved_at=timezone.now() - timedelta(minutes=1),
        created_by_id=actor_id,
        created_in_setup_version=1,
        last_changed_in_setup_version=1,
    )


def _historical_successor(
    field_model: Any,
    *,
    active: Any,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    version: int,
) -> Any:
    return field_model(
        organization_id=organization_id,
        edition_id=edition_id,
        key=active.key,
        version=version,
        supersedes_id=active.id,
        label=active.label,
        help_text=active.help_text,
        field_type=active.field_type,
        options=list(active.options),
        purpose=active.purpose,
        classification=active.classification,
        attendee_visible=active.attendee_visible,
        writer_policy=active.writer_policy,
        required=active.required,
        position=active.position,
        review_status="pending",
        status="draft",
        created_by_id=actor_id,
        created_in_setup_version=version,
        last_changed_in_setup_version=version,
    )


def _field_guard_definition() -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_functiondef(
                'maru_guard_registration_profile_extension_field()'::regprocedure
            )
            """
        )
        return str(cursor.fetchone()[0])


def test_lifecycle_action_and_guard_migrate_forward_and_reverse_exactly() -> None:
    before = _migrate(REGISTRATION_BEFORE)
    assert "profile_field_successor_started" not in _actions(
        before,
        REGISTRATION_BEFORE,
    )
    assert "profile extension edit must reset approval" not in (
        _field_guard_definition()
    )

    after = _migrate(REGISTRATION_AFTER)
    assert "profile_field_successor_started" in _actions(after, REGISTRATION_AFTER)
    hardened = _field_guard_definition()
    assert "profile extension edit must reset approval" in hardened
    assert "current_max_version" in hardened
    assert "prior_version >= NEW.version" in hardened
    assert "source binding is immutable" in hardened
    assert "last_changed_in_setup_version" in hardened
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE tgrelid IN (
                'registration_registrationsetupcommandreceipt'::regclass,
                'registration_registrationsetupcommandtarget'::regclass
             )
               AND NOT tgisinternal
               AND tgname LIKE 'registration_setup_%'
             ORDER BY tgname
            """
        )
        assert [str(row[0]) for row in cursor.fetchall()] == [
            "registration_setup_receipt_immutable",
            "registration_setup_receipt_no_truncate",
            "registration_setup_target_immutable",
            "registration_setup_target_no_truncate",
        ]
        cursor.execute(
            """
            SELECT to_regprocedure(
                       'public.maru_authority_provenance_test_reset_allowed()'
                   ) IS NOT NULL,
                   procedure.prosecdef,
                   NOT EXISTS (
                       SELECT 1
                         FROM aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   )
              FROM pg_proc AS procedure
             WHERE procedure.oid = to_regprocedure(
                 'public.maru_guard_registration_setup_evidence_immutable()'
             )
            """
        )
        assert cursor.fetchone() == (True, True, True)

    reversed_executor = _migrate(REGISTRATION_BEFORE)
    assert "profile_field_successor_started" not in _actions(
        reversed_executor,
        REGISTRATION_BEFORE,
    )
    reversed_guard = _field_guard_definition()
    assert "profile extension edit must reset approval" not in reversed_guard
    assert "prior_version >= NEW.version" in reversed_guard
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_guard_registration_setup_evidence_immutable()'
            )
            """
        )
        assert cursor.fetchone()[0] is None


def test_populated_successor_graph_fails_closed_on_reverse() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    actor_id = actor.id
    organization_id = edition.organization_id
    edition_id = edition.id

    after = _migrate(REGISTRATION_AFTER)
    apps = _historical_apps(after, REGISTRATION_AFTER)
    field_model = apps.get_model(
        "registration",
        "RegistrationProfileExtensionField",
    )
    active = _active_historical_field(
        apps,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    successor = _historical_successor(
        field_model,
        active=active,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        version=2,
    )
    successor.save(force_insert=True)

    setup_model = apps.get_model("registration", "RegistrationSetupControl")
    receipt_model = apps.get_model(
        "registration",
        "RegistrationSetupCommandReceipt",
    )
    setup = setup_model.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        origin="legacy_existing",
        provenance_status="legacy_unknown",
        aggregate_version=2,
    )
    receipt = receipt_model.objects.create(
        setup_id=setup.id,
        organization_id=organization_id,
        edition_id=edition_id,
        actor_id=actor_id,
        action="profile_field_successor_started",
        resulting_version=2,
        reason="Create the populated downgrade-fence successor.",
        correlation_id=uuid4(),
        source_channel="test",
        retry_key=uuid4(),
    )

    with pytest.raises(DatabaseError, match="use fix-forward recovery"):
        _migrate(REGISTRATION_BEFORE)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
              FROM registration_registrationsetupcommandreceipt
             WHERE action = 'profile_field_successor_started'
            """
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            """
            SELECT count(*)
              FROM registration_registrationprofileextensionfield
             WHERE supersedes_id IS NOT NULL
            """
        )
        assert cursor.fetchone()[0] == 1
    assert receipt.action == "profile_field_successor_started"
    assert successor.supersedes_id == active.id


def test_populated_multi_open_successor_graph_fails_closed_on_forward() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    actor_id = actor.id
    organization_id = edition.organization_id
    edition_id = edition.id

    before = _migrate(REGISTRATION_BEFORE)
    apps = _historical_apps(before, REGISTRATION_BEFORE)
    field_model = apps.get_model(
        "registration",
        "RegistrationProfileExtensionField",
    )
    active = _active_historical_field(
        apps,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    successors = [
        _historical_successor(
            field_model,
            active=active,
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            version=version,
        )
        for version in (2, 3)
    ]
    field_model.objects.bulk_create(successors)

    with pytest.raises(
        DatabaseError,
        match="registration_one_open_profile_extension_successor",
    ):
        _migrate(REGISTRATION_AFTER)

    field_model.objects.filter(pk__in=[item.pk for item in successors]).update(
        status="retired"
    )
    _migrate(REGISTRATION_AFTER)
