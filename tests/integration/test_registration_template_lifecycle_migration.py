import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.registration.models import (
    ConfigurationStatus,
    RegistrationConfiguration,
    RegistrationProvenanceStatus,
    TemplateStatus,
)
from maru.registration.setup_content import template_content_digest
from maru.registration.template_lifecycle import publish_registration_template
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration import (
    test_registration_configuration_lifecycle_commands as lifecycle_tests,
)
from tests.integration import (
    test_registration_template_lifecycle_commands as command_tests,
)
from tests.support.migrations import registration_migration_targets as _targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = ("registration", "0036_profile_extension_value_commands")
REGISTRATION_AFTER = (
    "registration",
    "0037_template_catalog_and_activation_evidence",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, target))
    return executor


def test_template_lifecycle_generation_cleanly_reverses_and_reapplies() -> None:
    _migrate(REGISTRATION_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                       'public.maru_assert_registration_template_publication_v1(uuid)'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_template_catalog_v2()'
                   ),
                   to_regprocedure(
                       'public.maru_guard_registration_configuration_activation_v2()'
                   )
            """
        )
        assert cursor.fetchone() == (None, None, None)

    _migrate(REGISTRATION_AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname, tgdeferrable, tginitdeferred
              FROM pg_catalog.pg_trigger
             WHERE NOT tgisinternal
               AND tgname IN (
                    'registration_template_catalog_control_v2_exact',
                    'registration_template_publication_v2_exact',
                    'registration_template_catalog_receipt_v2_exact',
                    'registration_template_catalog_target_v2_exact',
                    'registration_configuration_activation_v2_exact'
               )
             ORDER BY tgname
            """
        )
        rows = cursor.fetchall()
    assert len(rows) == 5
    assert all(
        deferrable and initially_deferred
        for _name, deferrable, initially_deferred in rows
    )

    _migrate(REGISTRATION_BEFORE)
    _migrate(REGISTRATION_AFTER)


def test_template_publication_evidence_is_a_populated_downgrade_fence() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )
    template = command_tests._draft_template(edition, actor)
    publish_registration_template(
        **command_tests._values(actor, edition, template)  # type: ignore[arg-type]
    )
    _migrate(REGISTRATION_AFTER)

    with pytest.raises(DatabaseError, match="fix-forward recovery"):
        _migrate(REGISTRATION_BEFORE)

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'on'")
        cursor.execute(
            "TRUNCATE registration_registrationtemplatecatalogcontrol, "
            "registration_registrationtemplate CASCADE"
        )
    _migrate(REGISTRATION_BEFORE)
    _migrate(REGISTRATION_AFTER)


def test_populated_unproven_template_fails_closed_on_forward() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    executor = _migrate(REGISTRATION_BEFORE)
    historical_apps = executor.loader.project_state(
        _targets(executor, REGISTRATION_BEFORE)
    ).apps
    template_model = historical_apps.get_model("registration", "RegistrationTemplate")
    product_model = historical_apps.get_model(
        "registration", "RegistrationTemplateProduct"
    )
    catalog_model = historical_apps.get_model(
        "registration", "RegistrationTemplateCatalogControl"
    )
    template = template_model.objects.create(
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        code="synthetic-unproven-template",
        name="Synthetic unproven template",
        version=1,
        created_by_id=actor.id,
    )
    product = product_model.objects.create(
        template_id=template.id,
        code="weekend",
        name="Synthetic weekend admission",
        description="Bounded synthetic reusable admission.",
        price_minor=12_000,
        capacity=400,
        position=10,
        entitlement_code="weekend-admission",
        entitlement_name="Weekend admission",
    )
    product.capacity_ceiling = None
    digest = template_content_digest(
        template=template,
        sections=(),
        questions=(),
        products=(product,),
    )
    product_model.objects.filter(pk=product.id).update(
        created_in_catalog_version=1,
        last_changed_in_catalog_version=1,
    )
    template_model.objects.filter(pk=template.id).update(
        status=TemplateStatus.PUBLISHED,
        published_at=timezone.now(),
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
        content_digest=digest,
        created_in_catalog_version=1,
        last_changed_in_catalog_version=1,
    )
    catalog_model.objects.create(
        organization_id=edition.organization_id,
        aggregate_version=1,
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
    )

    with pytest.raises(DatabaseError, match="publication evidence is incomplete"):
        _migrate(REGISTRATION_AFTER)

    assert template_model.objects.filter(
        pk=template.id,
        status=TemplateStatus.PUBLISHED,
    ).exists()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'on'")
        cursor.execute(
            "TRUNCATE registration_registrationtemplatecatalogcontrol, "
            "registration_registrationtemplate CASCADE"
        )
    _migrate(REGISTRATION_AFTER)


def test_populated_unproven_activation_fails_closed_on_forward() -> None:
    _actor, _edition, control, configuration = lifecycle_tests._ready_setup()
    _migrate(REGISTRATION_BEFORE)
    activated_at = timezone.now()
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        status=ConfigurationStatus.ACTIVE,
        activated_at=activated_at,
        review_required=False,
        review_note="",
        last_changed_in_setup_version=control.aggregate_version + 2,
    )
    type(control).objects.filter(pk=control.id).update(
        aggregate_version=control.aggregate_version + 2,
    )

    with pytest.raises(DatabaseError, match="activation evidence is incomplete"):
        _migrate(REGISTRATION_AFTER)

    assert RegistrationConfiguration.objects.filter(
        pk=configuration.id,
        status=ConfigurationStatus.ACTIVE,
    ).exists()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'on'")
        cursor.execute(
            "TRUNCATE registration_registrationsetupcontrol, "
            "registration_registrationconfiguration CASCADE"
        )
    _migrate(REGISTRATION_AFTER)
