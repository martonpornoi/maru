from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.apps.registry import Apps
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.registration.setup_content import configuration_source_binding_digest
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration import (
    test_registration_configuration_lifecycle_commands as lifecycle_tests,
)
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = (
    "registration",
    "0034_profile_extension_definition_lifecycle",
)
REGISTRATION_AFTER = (
    "registration",
    "0035_configuration_source_binding_guards",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def _historical_apps(
    executor: MigrationExecutor,
    target: tuple[str, str],
) -> Apps:
    return executor.loader.project_state(_targets(executor, target)).apps


def _truncate_setup_binding_tables() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(
            "TRUNCATE registration_registrationsetupcontrol, "
            "registration_registrationconfiguration CASCADE"
        )


def _reset_setup_binding_tables() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'on'")
        cursor.execute(
            "TRUNCATE registration_registrationsetupcontrol, "
            "registration_registrationconfiguration CASCADE"
        )


def _insert_complete_configuration_without_evidence(
    *,
    apps: Apps,
    organization_id: UUID,
    edition_id: UUID,
    actor_id: UUID,
    configuration_id: UUID,
) -> None:
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")
    with transaction.atomic():
        configuration_model.objects.bulk_create(
            [
                configuration_model(
                    id=configuration_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    name="Forged complete configuration",
                    version=1,
                    status="draft",
                    origin="blank",
                    provenance_status="complete",
                    content_digest="a" * 64,
                    created_in_setup_version=1,
                    last_changed_in_setup_version=1,
                    review_required=True,
                    opens_at=timezone.now() + timedelta(days=1),
                    closes_at=timezone.now() + timedelta(days=10),
                    capacity=100,
                    currency="EUR",
                    minimum_age=18,
                    default_payment_window_minutes=1_440,
                    waitlist_enabled=True,
                    automatic_waitlist_promotion=True,
                    created_by_id=actor_id,
                )
            ]
        )
        control_model.objects.bulk_create(
            [
                control_model(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    origin="blank",
                    provenance_status="complete",
                    aggregate_version=1,
                )
            ]
        )


def _insert_complete_configuration_with_receipt_only(
    *,
    apps: Apps,
    organization_id: UUID,
    edition_id: UUID,
    actor_id: UUID,
    configuration_id: UUID,
) -> None:
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")
    receipt_model = apps.get_model("registration", "RegistrationSetupCommandReceipt")
    target_model = apps.get_model("registration", "RegistrationSetupCommandTarget")
    with transaction.atomic():
        configuration = configuration_model(
            id=configuration_id,
            organization_id=organization_id,
            edition_id=edition_id,
            name="Forged receipt-only configuration",
            version=1,
            status="draft",
            origin="blank",
            provenance_status="complete",
            content_digest="a" * 64,
            created_in_setup_version=1,
            last_changed_in_setup_version=1,
            review_required=True,
            opens_at=timezone.now() + timedelta(days=1),
            closes_at=timezone.now() + timedelta(days=10),
            capacity=100,
            currency="EUR",
            minimum_age=18,
            default_payment_window_minutes=1_440,
            waitlist_enabled=True,
            automatic_waitlist_promotion=True,
            created_by_id=actor_id,
        )
        configuration_model.objects.bulk_create([configuration])
        control = control_model(
            organization_id=organization_id,
            edition_id=edition_id,
            origin="blank",
            provenance_status="complete",
            aggregate_version=1,
        )
        control_model.objects.bulk_create([control])
        receipt = receipt_model(
            setup_id=control.id,
            organization_id=organization_id,
            edition_id=edition_id,
            action="setup_started",
            resulting_version=1,
            actor_id=actor_id,
            reason="Fabricated receipt without atomic effect evidence.",
            correlation_id=uuid4(),
            source_channel="test",
            retry_key=uuid4(),
            request_digest="b" * 64,
        )
        receipt_model.objects.bulk_create([receipt])
        target_model.objects.bulk_create(
            [
                target_model(
                    receipt_id=receipt.id,
                    target_kind="configuration",
                    target_id=configuration.id,
                    change_kind="created",
                    target_schema_version=configuration.version,
                    content_digest=configuration_source_binding_digest(configuration),
                )
            ]
        )


def test_binding_guards_migrate_forward_and_reverse_with_closed_acl() -> None:
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                       'public.maru_guard_registration_configuration_binding()'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_setup_control_binding()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None)

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE tgrelid IN (
                'registration_registrationconfiguration'::regclass,
                'registration_registrationsetupcontrol'::regclass
             )
               AND NOT tgisinternal
               AND (
                    tgname LIKE 'registration_configuration_%binding%'
                    OR tgname LIKE 'registration_setup_control_%binding%'
                    OR tgname = 'registration_setup_control_configuration_exact'
               )
             ORDER BY tgname
            """
        )
        assert [str(row[0]) for row in cursor.fetchall()] == [
            "registration_configuration_binding_immutable",
            "registration_configuration_binding_no_truncate",
            "registration_configuration_setup_binding_exact",
            "registration_setup_control_binding_immutable",
            "registration_setup_control_binding_no_truncate",
            "registration_setup_control_configuration_exact",
        ]
        cursor.execute(
            """
            SELECT procedure.proname,
                   procedure.prosecdef,
                   procedure.proconfig,
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
             WHERE procedure.oid IN (
                to_regprocedure(
                    'public.maru_guard_registration_configuration_binding()'
                ),
                to_regprocedure(
                    'public.maru_guard_registration_setup_control_binding()'
                )
             )
             ORDER BY procedure.proname
            """
        )
        functions = cursor.fetchall()
        assert len(functions) == 2
        for name, security_definer, settings, public_execute_revoked in functions:
            assert name in {
                "maru_guard_registration_configuration_binding",
                "maru_guard_registration_setup_control_binding",
            }
            assert security_definer is True
            assert "search_path=pg_catalog, public, pg_temp" in settings
            assert public_execute_revoked is True
        assert "TimeZone=UTC" in functions[0][2]
        cursor.execute(
            """
            SELECT conname
              FROM pg_constraint
             WHERE conname IN (
                'reg_configuration_complete_provenance_shape',
                'reg_setup_complete_origin_nonlegacy'
             )
             ORDER BY conname
            """
        )
        assert [str(row[0]) for row in cursor.fetchall()] == [
            "reg_configuration_complete_provenance_shape",
            "reg_setup_complete_origin_nonlegacy",
        ]

    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                       'public.maru_guard_registration_configuration_binding()'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_setup_control_binding()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None)


def test_raw_binding_updates_delete_and_truncate_roll_back() -> None:
    _actor, _edition, current_control, current_configuration = (
        lifecycle_tests._ready_setup()
    )
    control_id = current_control.id
    configuration_id = current_configuration.id
    executor = _migrate(REGISTRATION_AFTER)
    apps = _historical_apps(executor, REGISTRATION_AFTER)
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")
    configuration = configuration_model.objects.get(pk=configuration_id)
    control = control_model.objects.get(pk=control_id)
    original_configuration = (
        configuration.origin,
        configuration.source_content_digest,
    )
    original_control = (control.origin, control.provenance_status)

    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        configuration_model.objects.filter(pk=configuration.id).update(
            source_content_digest="f" * 64
        )
    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        control_model.objects.filter(pk=control.id).update(origin="published_template")
    with (
        pytest.raises(
            DatabaseError,
            match="use retirement",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM registration_registrationconfiguration WHERE id = %s",
            [configuration.id],
        )
    with (
        pytest.raises(
            DatabaseError,
            match="retained evidence",
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM registration_registrationsetupcontrol WHERE id = %s",
            [control.id],
        )
    with pytest.raises(DatabaseError, match="cannot be truncated"):
        _truncate_setup_binding_tables()

    configuration.refresh_from_db()
    control.refresh_from_db()
    assert (
        configuration.origin,
        configuration.source_content_digest,
    ) == original_configuration
    assert (control.origin, control.provenance_status) == original_control


def test_complete_configuration_without_exact_start_evidence_rolls_back() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    organization_id = edition.organization_id
    edition_id = edition.id
    actor_id = actor.id
    configuration_id = uuid4()
    executor = _migrate(REGISTRATION_AFTER)
    apps = _historical_apps(executor, REGISTRATION_AFTER)
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")
    with pytest.raises(DatabaseError, match="setup binding is incomplete"):
        _insert_complete_configuration_without_evidence(
            apps=apps,
            organization_id=organization_id,
            edition_id=edition_id,
            actor_id=actor_id,
            configuration_id=configuration_id,
        )
    assert not configuration_model.objects.filter(pk=configuration_id).exists()
    assert not control_model.objects.filter(edition_id=edition_id).exists()


def test_receipt_only_binding_without_atomic_effect_evidence_rolls_back() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    organization_id = edition.organization_id
    edition_id = edition.id
    actor_id = actor.id
    configuration_id = uuid4()
    executor = _migrate(REGISTRATION_AFTER)
    apps = _historical_apps(executor, REGISTRATION_AFTER)
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")

    with pytest.raises(DatabaseError, match="setup binding is incomplete"):
        _insert_complete_configuration_with_receipt_only(
            apps=apps,
            organization_id=organization_id,
            edition_id=edition_id,
            actor_id=actor_id,
            configuration_id=configuration_id,
        )

    assert not configuration_model.objects.filter(pk=configuration_id).exists()
    assert not control_model.objects.filter(edition_id=edition_id).exists()


def test_populated_forged_complete_binding_fails_closed_on_forward() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    organization_id = edition.organization_id
    edition_id = edition.id
    actor_id = actor.id
    configuration_id = uuid4()
    executor = _migrate(REGISTRATION_BEFORE)
    apps = _historical_apps(executor, REGISTRATION_BEFORE)
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")
    _insert_complete_configuration_without_evidence(
        apps=apps,
        organization_id=organization_id,
        edition_id=edition_id,
        actor_id=actor_id,
        configuration_id=configuration_id,
    )

    with pytest.raises(DatabaseError, match="setup binding is incomplete"):
        _migrate(REGISTRATION_AFTER)

    assert configuration_model.objects.filter(pk=configuration_id).exists()
    assert control_model.objects.filter(edition_id=edition_id).exists()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_guard_registration_configuration_binding()'
            )
            """
        )
        assert cursor.fetchone()[0] is None

    _reset_setup_binding_tables()
    _migrate(REGISTRATION_AFTER)


def test_populated_complete_binding_fails_closed_on_reverse() -> None:
    _actor, edition, current_control, current_configuration = (
        lifecycle_tests._ready_setup()
    )
    edition_id = edition.id
    control_id = current_control.id
    configuration_id = current_configuration.id
    executor = _migrate(REGISTRATION_AFTER)
    apps = _historical_apps(executor, REGISTRATION_AFTER)
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    control_model = apps.get_model("registration", "RegistrationSetupControl")

    with pytest.raises(DatabaseError, match="use fix-forward recovery"):
        _migrate(REGISTRATION_BEFORE)

    assert configuration_model.objects.filter(pk=configuration_id).exists()
    assert control_model.objects.filter(pk=control_id, edition_id=edition_id).exists()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_guard_registration_configuration_binding()'
            ) IS NOT NULL
            """
        )
        assert cursor.fetchone()[0] is True
