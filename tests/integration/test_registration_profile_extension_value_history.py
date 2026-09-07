"""Serial Registration history with shared setup and isolated real migrations."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from django.apps import apps as current_apps
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from tests.factories import AccountFactory, EventEditionFactory, ParticipationFactory
from tests.support.migrations import (
    flush_then_restore_current_migration_graph,
    migrate_test_targets,
    migration_project_state,
    rollback_migration_case,
)
from tests.support.migrations import (
    registration_migration_targets as _targets,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from pytest_django.fixtures import DjangoDbBlocker

pytestmark = pytest.mark.integration

REGISTRATION_BEFORE = ("registration", "0035_configuration_source_binding_guards")
REGISTRATION_AFTER = ("registration", "0036_profile_extension_value_commands")


@pytest.fixture(scope="module")
def historical_baseline(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[tuple[UUID, UUID, UUID]]:
    """Commit compatible parents before downgrading, then restore every current leaf."""

    del django_db_setup
    with django_db_blocker.unblock():
        try:
            owner = AccountFactory()
            edition = EventEditionFactory()
            participation = ParticipationFactory(
                account=owner,
                organization=edition.organization,
                edition=edition,
            )
            _migrate(REGISTRATION_BEFORE)
            yield owner.id, edition.id, participation.id
        finally:
            flush_then_restore_current_migration_graph()
            _assert_current_schema()


@pytest.fixture
def isolated_historical_case(
    historical_baseline: tuple[UUID, UUID, UUID],
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Keep each original case's input, schema, recorder, and callbacks independent."""

    del historical_baseline
    with django_db_blocker.unblock(), rollback_migration_case():
        yield


def _assert_current_schema() -> None:
    """Inspect the final schema and recorder without executing a repair migration."""

    executor = MigrationExecutor(connection)
    assert not executor.migration_plan(executor.loader.graph.leaf_nodes())
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        for model in current_apps.get_models():
            if not model._meta.managed or model._meta.proxy:
                continue
            table = model._meta.db_table
            assert table in tables, table
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, table
                )
            }
            assert {
                field.column for field in model._meta.local_concrete_fields
            } <= columns, table
        cursor.execute("SELECT to_regclass('registration_history_case_sentinel')")
        assert cursor.fetchone() == (None,)
        cursor.execute(
            "SELECT to_regprocedure("
            "'public.maru_guard_registration_profile_value_control()') IS NOT NULL, "
            "to_regprocedure("
            "'public.maru_guard_registration_profile_value_receipt()') IS NOT NULL"
        )
        assert cursor.fetchone() == (True, True)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    # Original cases committed their input before DDL. Validate that same input
    # boundary without committing the isolated case or disabling any constraint.
    if connection.in_atomic_block:
        connection.check_constraints()
    executor = MigrationExecutor(connection)
    migrate_test_targets(executor, list(_targets(executor, target)))
    return executor


def _historical_apps(executor: MigrationExecutor, target: tuple[str, str]) -> Any:
    return migration_project_state(executor, _targets(executor, target)).apps


def _historical_registration_world(
    parent_ids: tuple[UUID, UUID, UUID],
    *,
    key: str | None,
    writer_policy: str = "attendee_and_staff",
    attendee_visible: bool = True,
    field_type: str = "short_text",
    options: list[str] | None = None,
    required: bool = False,
) -> tuple[Any, Any, Any, Any | None]:
    """Build case-local history using parents committed before the downgrade."""

    executor = _migrate(REGISTRATION_BEFORE)
    apps = _historical_apps(executor, REGISTRATION_BEFORE)
    owner = apps.get_model("identity", "Account").objects.get(pk=parent_ids[0])
    edition = apps.get_model("events", "EventEdition").objects.get(pk=parent_ids[1])
    participation = apps.get_model("participation", "Participation").objects.get(
        pk=parent_ids[2]
    )
    configuration_model = apps.get_model("registration", "RegistrationConfiguration")
    product_model = apps.get_model("registration", "AdmissionProduct")
    registration_model = apps.get_model("registration", "Registration")

    configuration = configuration_model.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        name="Synthetic historical attendee registration",
        version=1,
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=100,
        currency="EUR",
        created_by_id=owner.id,
    )
    product = product_model.objects.create(
        configuration_id=configuration.id,
        code=f"historical-admission-{uuid4().hex[:12]}",
        name="Historical weekend admission",
        price_minor=10_000,
        capacity=100,
        position=10,
    )
    configuration_model.objects.filter(pk=configuration.pk).update(
        status="active",
        activated_at=timezone.now(),
    )
    configuration.refresh_from_db()
    registration = registration_model.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        participation_id=participation.id,
        account_id=owner.id,
        configuration_id=configuration.id,
        product_id=product.id,
        reference=f"PV-HIST-{uuid4().hex[:12]}",
        state="confirmed",
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=timezone.now(),
        confirmed_at=timezone.now(),
        confirmation_basis="provider",
    )
    field = (
        _historical_field(
            apps,
            registration=registration,
            owner=owner,
            key=key,
            writer_policy=writer_policy,
            attendee_visible=attendee_visible,
            field_type=field_type,
            options=options,
            required=required,
        )
        if key is not None
        else None
    )
    return apps, registration, owner, field


def _historical_field(
    apps: Any,
    *,
    registration: Any,
    owner: Any,
    key: str,
    writer_policy: str = "attendee_and_staff",
    attendee_visible: bool = True,
    field_type: str = "short_text",
    options: list[str] | None = None,
    required: bool = False,
    review_status: str = "approved",
    status: str = "active",
) -> Any:
    field_model = apps.get_model("registration", "RegistrationProfileExtensionField")
    active = status == "active"
    return field_model.objects.create(
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        key=key,
        version=1,
        label=f"Synthetic historical {key}",
        help_text="Provide one historical synthetic profile detail.",
        field_type=field_type,
        options=options or [],
        purpose="Exercise the profile-value migration boundary.",
        classification="C2",
        attendee_visible=attendee_visible,
        writer_policy=writer_policy,
        required=required,
        position=0,
        review_status=review_status,
        status=status,
        created_by_id=owner.id,
        approved_by_id=owner.id if active else None,
        approved_at=(timezone.now() - timedelta(minutes=1)) if active else None,
    )


def _truncate_legacy_value_revisions() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE registration_registrationprofileextensionvaluerevision CASCADE"
        )


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_retires_the_legacy_public_execute_guard_function() -> None:
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.prosecdef,
                   procedure.proconfig,
                   EXISTS (
                       SELECT 1
                         FROM aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   ) AS public_execute
              FROM pg_proc AS procedure
             WHERE procedure.oid = to_regprocedure(
                 'public.maru_guard_registration_profile_extension_value()'
             )
            """
        )
        assert cursor.fetchone() == (False, None, True)

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.oid::regprocedure::text
              FROM pg_proc AS procedure
             WHERE procedure.oid = to_regprocedure(
                 'public.maru_guard_registration_profile_extension_value()'
             )
            """
        )
        assert cursor.fetchone() is None


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_backfills_exact_latest_control_from_legacy_revisions(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline, key="legacy-current"
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    first = revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=1,
        value="legacy first",
        actor_id=owner.id,
        source_channel="test",
    )
    second = revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=2,
        value="legacy current",
        actor_id=owner.id,
        source_channel="test",
    )

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT registration_id,
                   organization_id,
                   edition_id,
                   field_key,
                   current_sequence,
                   latest_revision_id,
                   created_at,
                   updated_at
              FROM registration_registrationprofileextensionvaluecontrol
            """
        )
        row = cursor.fetchone()
    assert row is not None
    assert row[:6] == (
        registration.id,
        registration.organization_id,
        registration.edition_id,
        field.key,
        2,
        second.id,
    )
    first.refresh_from_db()
    second.refresh_from_db()
    assert row[6] == first.created_at
    assert row[7] == second.created_at
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
              FROM registration_registrationprofileextensionvaluecommandreceipt
            """
        )
        assert cursor.fetchone()[0] == 0


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_a_noncontiguous_legacy_revision_sequence(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline, key="legacy-sequence-gap"
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=2,
        value="legacy sequence two without sequence one",
        actor_id=owner.id,
        source_channel="test",
    )

    with pytest.raises(
        DatabaseError,
        match="noncontiguous profile-value revision history",
    ):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_legacy_value_that_violates_writer_policy(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline,
        key="legacy-internal-owner-write",
        writer_policy="registration_staff",
        attendee_visible=False,
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=1,
        value="owner forged an internal-only legacy value",
        actor_id=owner.id,
        source_channel="test",
        reason="",
    )

    with pytest.raises(DatabaseError, match="writer policy"):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_legacy_value_with_blank_source_channel(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline, key="legacy-blank-source"
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.bulk_create(
        [
            revision_model(
                registration_id=registration.id,
                organization_id=registration.organization_id,
                edition_id=registration.edition_id,
                field_id=field.id,
                field_key=field.key,
                sequence=1,
                value="legacy value without source provenance",
                actor_id=owner.id,
                source_channel="",
                reason="",
            )
        ]
    )

    with pytest.raises(DatabaseError, match="source channel"):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_legacy_value_against_a_draft_field(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, _field = _historical_registration_world(
        historical_baseline, key=None
    )
    field = _historical_field(
        apps,
        registration=registration,
        owner=owner,
        key="legacy-draft-field",
        writer_policy="attendee",
        review_status="pending",
        status="draft",
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=1,
        value="a draft field must not have a value",
        actor_id=owner.id,
        source_channel="test",
        reason="",
    )

    with pytest.raises(DatabaseError, match="draft profile field"):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_legacy_value_incompatible_with_field_definition(
    historical_baseline: tuple[UUID, UUID, UUID],
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline,
        key="legacy-invalid-boolean",
        field_type="boolean",
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.create(
        registration_id=registration.id,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        field_id=field.id,
        field_key=field.key,
        sequence=1,
        value="yes",
        actor_id=owner.id,
        source_channel="test",
        reason="",
    )

    with pytest.raises(DatabaseError, match="field definition"):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.parametrize(
    ("key", "field_type", "options", "required", "value"),
    [
        ("legacy-padded-text", "short_text", [], False, " padded "),
        ("legacy-required-empty", "short_text", [], True, ""),
        ("legacy-wide-integer", "integer", [], False, 2**31),
        (
            "legacy-duplicate-multiple",
            "multiple_choice",
            ["alpha", "beta"],
            False,
            ["alpha", "alpha"],
        ),
        (
            "legacy-unknown-multiple",
            "multiple_choice",
            ["alpha", "beta"],
            False,
            ["alpha", "gamma"],
        ),
    ],
)
@pytest.mark.usefixtures("isolated_historical_case")
def test_forward_rejects_representative_noncanonical_legacy_values(
    historical_baseline: tuple[UUID, UUID, UUID],
    key: str,
    field_type: str,
    options: list[str],
    required: bool,
    value: object,
) -> None:
    apps, registration, owner, field = _historical_registration_world(
        historical_baseline,
        key=key,
        field_type=field_type,
        options=options,
        required=required,
    )
    revision_model = apps.get_model(
        "registration", "RegistrationProfileExtensionValueRevision"
    )
    revision_model.objects.bulk_create(
        [
            revision_model(
                registration_id=registration.id,
                organization_id=registration.organization_id,
                edition_id=registration.edition_id,
                field_id=field.id,
                field_key=field.key,
                sequence=1,
                value=value,
                actor_id=owner.id,
                source_channel="test",
                reason="",
            )
        ]
    )

    with pytest.raises(DatabaseError, match="field definition"):
        _migrate(REGISTRATION_AFTER)

    _truncate_legacy_value_revisions()
    _migrate(REGISTRATION_AFTER)


@pytest.mark.parametrize("fail", [False, True])
def test_real_forward_case_leaves_no_history_schema_recorder_or_callbacks(
    historical_baseline: tuple[UUID, UUID, UUID],
    django_db_blocker: DjangoDbBlocker,
    fail: bool,
) -> None:
    """Prove real forward DDL and backfill roll back on both case outcomes."""

    callbacks: list[str] = []
    with django_db_blocker.unblock():
        before = set(MigrationRecorder(connection).applied_migrations())
        with (
            pytest.raises(ValueError, match="synthetic historical failure")
            if fail
            else nullcontext(),
            rollback_migration_case(),
        ):
            apps, registration, owner, field = _historical_registration_world(
                historical_baseline, key="case-isolation"
            )
            revision_model = apps.get_model(
                "registration", "RegistrationProfileExtensionValueRevision"
            )
            revision_model.objects.create(
                registration_id=registration.id,
                organization_id=registration.organization_id,
                edition_id=registration.edition_id,
                field_id=field.id,
                field_key=field.key,
                sequence=1,
                value="synthetic retained input",
                actor_id=owner.id,
                source_channel="test",
            )
            _migrate(REGISTRATION_AFTER)
            assert (
                REGISTRATION_AFTER in MigrationRecorder(connection).applied_migrations()
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_sequence FROM "
                    "registration_registrationprofileextensionvaluecontrol"
                )
                assert cursor.fetchall() == [(1,)]
                cursor.execute(
                    "CREATE TABLE registration_history_case_sentinel (value integer)"
                )
            transaction.on_commit(lambda: callbacks.append("committed"))
            if fail:
                raise ValueError("synthetic historical failure")

        assert callbacks == []
        assert set(MigrationRecorder(connection).applied_migrations()) == before
        # Inspect from another independent case; do not repair a leaked state.
        with rollback_migration_case(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('registration_history_case_sentinel'), "
                "to_regclass('registration_registrationprofileextensionvaluecontrol'), "
                "to_regclass('registration_registrationprofileextensionvaluecommandreceipt')"
            )
            assert cursor.fetchone() == (None, None, None)
            cursor.execute(
                "SELECT count(*) FROM "
                "registration_registrationprofileextensionvaluerevision"
            )
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM registration_registration")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT account_id, edition_id FROM participation_participation "
                "WHERE id = %s",
                [historical_baseline[2]],
            )
            assert cursor.fetchone() == historical_baseline[:2]


def test_forward_boundary_rejects_invalid_deferred_data(
    historical_baseline: tuple[UUID, UUID, UUID],
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """Reject a deferred violation before DDL, not merely at eventual case cleanup."""

    del historical_baseline

    def migrate_invalid_history() -> None:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE registration_history_deferred "
                    "(value integer UNIQUE DEFERRABLE INITIALLY DEFERRED)"
                )
                cursor.execute(
                    "INSERT INTO registration_history_deferred VALUES (1), (1)"
                )
            _migrate(REGISTRATION_AFTER)

    with django_db_blocker.unblock(), rollback_migration_case():
        before = set(MigrationRecorder(connection).applied_migrations())
        with pytest.raises(
            IntegrityError, match="registration_history_deferred_value_key"
        ):
            migrate_invalid_history()
        assert set(MigrationRecorder(connection).applied_migrations()) == before
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('registration_history_deferred'), "
                "to_regclass('registration_registrationprofileextensionvaluecontrol')"
            )
            assert cursor.fetchone() == (None, None)
