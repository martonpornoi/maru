from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.registration.profile_extension_values import append_profile_extension_value
from tests.factories import AccountFactory, EventEditionFactory, ParticipationFactory
from tests.integration import (
    test_registration_profile_extension_value_commands as value_tests,
)
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = (
    "registration",
    "0035_configuration_source_binding_guards",
)
REGISTRATION_AFTER = (
    "registration",
    "0036_profile_extension_value_commands",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def _historical_apps(executor: MigrationExecutor, target: tuple[str, str]) -> Any:
    return executor.loader.project_state(_targets(executor, target)).apps


def _historical_registration_world(
    *,
    key: str | None,
    writer_policy: str = "attendee_and_staff",
    attendee_visible: bool = True,
    field_type: str = "short_text",
    options: list[str] | None = None,
    required: bool = False,
) -> tuple[Any, Any, Any, Any | None]:
    """Create external parents before entering the Registration 0035 state."""

    owner = AccountFactory()
    edition = EventEditionFactory()
    participation = ParticipationFactory(
        account=owner,
        organization=edition.organization,
        edition=edition,
    )
    executor = _migrate(REGISTRATION_BEFORE)
    apps = _historical_apps(executor, REGISTRATION_BEFORE)
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


def test_profile_value_schema_and_closed_helpers_migrate_forward_and_reverse() -> None:
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_value_control()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None, None)

    _migrate(REGISTRATION_AFTER)
    expected_functions = {
        "maru_assert_registration_profile_value_control_complete",
        "maru_assert_registration_profile_value_revision_evidence",
        "maru_guard_registration_profile_value_control",
        "maru_guard_registration_profile_value_immutable",
        "maru_guard_registration_profile_value_receipt",
        "maru_guard_registration_profile_value_revision_v2",
    }
    with connection.cursor() as cursor:
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
                   ) AS public_execute_revoked
              FROM pg_proc AS procedure
             WHERE procedure.proname = ANY(%s)
             ORDER BY procedure.proname
            """,
            [list(expected_functions)],
        )
        functions = cursor.fetchall()
        assert {str(row[0]) for row in functions} == expected_functions
        for _name, security_definer, settings, public_execute_revoked in functions:
            assert security_definer is True
            assert "search_path=pg_catalog, public, pg_temp" in settings
            assert public_execute_revoked is True

        cursor.execute(
            """
            SELECT trigger.tgname,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred
              FROM pg_trigger AS trigger
             WHERE trigger.tgrelid IN (
                'registration_registrationprofileextensionvaluerevision'::regclass,
                'registration_registrationprofileextensionvaluecontrol'::regclass,
                'registration_registrationprofileextensionvaluecommandreceipt'::regclass
             )
               AND NOT trigger.tgisinternal
               AND trigger.tgname LIKE 'registration_profile_value_%'
             ORDER BY trigger.tgname
            """
        )
        triggers = cursor.fetchall()
        assert [str(row[0]) for row in triggers] == [
            "registration_profile_value_control_complete",
            "registration_profile_value_control_guard",
            "registration_profile_value_control_no_truncate",
            "registration_profile_value_receipt_guard",
            "registration_profile_value_receipt_no_truncate",
            "registration_profile_value_revision_evidence",
            "registration_profile_value_revision_no_truncate",
        ]
        for trigger_name in (
            "registration_profile_value_control_complete",
            "registration_profile_value_revision_evidence",
        ):
            deferred = next(row for row in triggers if row[0] == trigger_name)
            assert deferred[1:] == (True, True)
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE tgrelid = (
                'registration_registrationprofileextensionvaluerevision'::regclass
             )
               AND NOT tgisinternal
               AND tgname = 'registration_profile_extension_value_guard'
            """
        )
        assert cursor.fetchone() == ("registration_profile_extension_value_guard",)

    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_value_control()'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_profile_extension_value()'
                   ) IS NOT NULL
            """
        )
        assert cursor.fetchone() == (None, None, None, True)

    _migrate(REGISTRATION_AFTER)


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


def test_forward_backfills_exact_latest_control_from_legacy_revisions() -> None:
    apps, registration, owner, field = _historical_registration_world(
        key="legacy-current"
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


def test_forward_rejects_a_noncontiguous_legacy_revision_sequence() -> None:
    apps, registration, owner, field = _historical_registration_world(
        key="legacy-sequence-gap"
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


def test_forward_rejects_legacy_value_that_violates_writer_policy() -> None:
    apps, registration, owner, field = _historical_registration_world(
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


def test_forward_rejects_legacy_value_with_blank_source_channel() -> None:
    apps, registration, owner, field = _historical_registration_world(
        key="legacy-blank-source"
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


def test_forward_rejects_legacy_value_against_a_draft_field() -> None:
    apps, registration, owner, _field = _historical_registration_world(key=None)
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


def test_forward_rejects_legacy_value_incompatible_with_field_definition() -> None:
    apps, registration, owner, field = _historical_registration_world(
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
def test_forward_rejects_representative_noncanonical_legacy_values(
    key: str,
    field_type: str,
    options: list[str],
    required: bool,
    value: object,
) -> None:
    apps, registration, owner, field = _historical_registration_world(
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


def test_empty_reverse_and_reapply_are_exact() -> None:
    _migrate(REGISTRATION_AFTER)
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ),
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ),
                   to_regprocedure(
                       'public.maru_assert_registration_profile_value_revision_evidence()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None, None)

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass(
                       'registration_registrationprofileextensionvaluecontrol'
                   ) IS NOT NULL,
                   to_regclass(
                       'registration_registrationprofileextensionvaluecommandreceipt'
                   ) IS NOT NULL,
                   to_regprocedure(
                       'public.maru_assert_registration_profile_value_revision_evidence()'
                   ) IS NOT NULL
            """
        )
        assert cursor.fetchone() == (True, True, True)


def test_durable_command_receipt_fences_populated_reverse() -> None:
    registration, owner = value_tests._registration_world()
    field = value_tests._field(registration, actor=owner, key="durable-command")
    result = append_profile_extension_value(
        **value_tests._append_values(
            actor=owner,
            registration=registration,
            field=field,
        )
    )
    _migrate(REGISTRATION_AFTER)

    with pytest.raises(DatabaseError, match="use fix-forward recovery"):
        _migrate(REGISTRATION_BEFORE)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*), min(result_sequence), max(result_sequence)
              FROM registration_registrationprofileextensionvaluecommandreceipt
             WHERE id = %s
            """,
            [result.receipt_id],
        )
        assert cursor.fetchone() == (1, 1, 1)
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_guard_registration_profile_value_receipt()'
            ) IS NOT NULL
            """
        )
        assert cursor.fetchone()[0] is True
