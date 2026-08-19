from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.registration.models import (
    RegistrationCommandChangeKind,
    RegistrationProvenanceStatus,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationTemplateCatalogCommandReceipt,
    RegistrationTemplateCatalogCommandTarget,
    RegistrationTemplateCatalogControl,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
)
from tests.support.migrations import (
    registration_migration_targets as _migration_targets,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

REGISTRATION_BEFORE = ("registration", "0031_idn011_convention_subject_guards")
REGISTRATION_AFTER = ("registration", "0032_page10_registration_setup_schema")
REGISTRATION_DEFINITION_ACTIONS_BEFORE = (
    "registration",
    "0032_page10_registration_setup_schema",
)
REGISTRATION_DEFINITION_ACTIONS_AFTER = (
    "registration",
    "0033_page10_definition_command_actions",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(_migration_targets(executor, target))
    return executor


def _historical_apps(executor: MigrationExecutor, target: tuple[str, str]) -> object:
    return executor.loader.project_state(_migration_targets(executor, target)).apps


def _legacy_spine(apps: object, *, code: str, starts_on: date) -> tuple[object, object]:
    organization_model = apps.get_model("organizations", "Organization")
    series_model = apps.get_model("organizations", "ConventionSeries")
    edition_model = apps.get_model("events", "EventEdition")
    organization = organization_model.objects.create(
        slug=f"{code}-organizer",
        name=f"{code.title()} Organizer",
    )
    series = series_model.objects.create(
        organization_id=organization.id,
        slug=f"{code}-series",
        name=f"{code.title()} Series",
    )
    edition = edition_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug=f"{code}-edition",
        name=f"{code.title()} Edition",
        time_zone="Europe/Vienna",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=starts_on,
        ends_on=starts_on + timedelta(days=3),
    )
    return organization, edition


def _receipt_action_values(apps: object) -> set[str]:
    receipt_model = apps.get_model(
        "registration",
        "RegistrationSetupCommandReceipt",
    )
    return {
        str(value) for value, _label in receipt_model._meta.get_field("action").choices
    }


def _minor_evidence_blank_flags(apps: object) -> tuple[bool, bool, bool]:
    policy_model = apps.get_model("registration", "MinorRegistrationPolicy")
    return tuple(
        bool(policy_model._meta.get_field(field_name).blank)
        for field_name in (
            "guardian_notice_version",
            "jurisdiction_code",
            "review_reference",
        )
    )


def test_definition_action_schema_is_additive_and_reverses_to_exact_state() -> None:
    before_executor = _migrate(REGISTRATION_DEFINITION_ACTIONS_BEFORE)
    before_apps = _historical_apps(
        before_executor,
        REGISTRATION_DEFINITION_ACTIONS_BEFORE,
    )
    before_actions = _receipt_action_values(before_apps)
    assert "minor_policy_created" not in before_actions
    assert "minor_policy_removed" not in before_actions
    assert "profile_field_moved" not in before_actions
    assert _minor_evidence_blank_flags(before_apps) == (False, False, False)

    after_executor = _migrate(REGISTRATION_DEFINITION_ACTIONS_AFTER)
    after_apps = _historical_apps(
        after_executor,
        REGISTRATION_DEFINITION_ACTIONS_AFTER,
    )
    assert {
        "minor_policy_created",
        "minor_policy_removed",
        "profile_field_moved",
    }.issubset(_receipt_action_values(after_apps))
    assert _minor_evidence_blank_flags(after_apps) == (True, True, True)

    reversed_executor = _migrate(REGISTRATION_DEFINITION_ACTIONS_BEFORE)
    reversed_apps = _historical_apps(
        reversed_executor,
        REGISTRATION_DEFINITION_ACTIONS_BEFORE,
    )
    assert _receipt_action_values(reversed_apps) == before_actions
    assert _minor_evidence_blank_flags(reversed_apps) == (False, False, False)


def test_populated_migration_backfills_only_observable_legacy_evidence(  # noqa: PLR0915
) -> None:
    executor = _migrate(REGISTRATION_BEFORE)
    legacy_apps = _historical_apps(executor, REGISTRATION_BEFORE)
    account_model = legacy_apps.get_model("identity", "Account")
    template_model = legacy_apps.get_model("registration", "RegistrationTemplate")
    template_section_model = legacy_apps.get_model(
        "registration", "RegistrationTemplateSection"
    )
    template_question_model = legacy_apps.get_model(
        "registration", "RegistrationTemplateQuestion"
    )
    template_product_model = legacy_apps.get_model(
        "registration", "RegistrationTemplateProduct"
    )
    configuration_model = legacy_apps.get_model(
        "registration", "RegistrationConfiguration"
    )
    section_model = legacy_apps.get_model("registration", "RegistrationSection")
    question_model = legacy_apps.get_model("registration", "RegistrationQuestion")
    product_model = legacy_apps.get_model("registration", "AdmissionProduct")
    minor_policy_model = legacy_apps.get_model(
        "registration", "MinorRegistrationPolicy"
    )

    organization, _source_edition = _legacy_spine(
        legacy_apps,
        code="legacy-source",
        starts_on=date(2036, 7, 1),
    )
    series_model = legacy_apps.get_model("organizations", "ConventionSeries")
    edition_model = legacy_apps.get_model("events", "EventEdition")
    series = series_model.objects.get(organization_id=organization.id)
    target_edition = edition_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-target-edition",
        name="Legacy Target Edition",
        time_zone="Europe/Vienna",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2037, 7, 1),
        ends_on=date(2037, 7, 4),
    )
    empty_edition = edition_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-empty-edition",
        name="Legacy Empty Edition",
        time_zone="Europe/Vienna",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2038, 7, 1),
        ends_on=date(2038, 7, 4),
    )
    actor = account_model.objects.create(
        email="legacy.setup@example.invalid",
        password="!",
        display_name="Legacy Setup Actor",
    )
    template = template_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        code="attendee-registration",
        name="Attendee registration",
        description="Observed reusable form.",
        version=4,
        status="draft",
        created_by_id=actor.id,
    )
    template_section = template_section_model.objects.create(
        template_id=template.id,
        key="profile",
        title="Profile",
        description="Badge details.",
        position=10,
    )
    template_question_model.objects.create(
        template_id=template.id,
        section_id=template_section.id,
        key="badge-name",
        label="Badge name",
        help_text="",
        field_type="short_text",
        required=True,
        position=10,
        options=[],
        purpose="Print the badge.",
        visibility="attendee_and_staff",
        classification="C2",
        condition_question_key="",
        condition_value="",
    )
    template_product_model.objects.create(
        template_id=template.id,
        code="weekend",
        name="Weekend",
        description="",
        price_minor=12_000,
        capacity=200,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    template_model.objects.filter(pk=template.id).update(
        status="published",
        published_at=timezone.now(),
    )
    configuration = configuration_model.objects.create(
        organization_id=organization.id,
        edition_id=target_edition.id,
        name="Target registration",
        version=2,
        source_template_id=template.id,
        review_required=True,
        review_note="",
        opens_at=timezone.now(),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=200,
        currency="EUR",
        created_by_id=actor.id,
    )
    section = section_model.objects.create(
        configuration_id=configuration.id,
        key="profile",
        title="Profile",
        description="Badge details.",
        position=10,
    )
    question_model.objects.create(
        configuration_id=configuration.id,
        section_id=section.id,
        key="badge-name",
        label="Badge name",
        help_text="",
        field_type="short_text",
        required=True,
        position=10,
        options=[],
        purpose="Print the badge.",
        visibility="attendee_and_staff",
        classification="C2",
        condition_question_key="",
        condition_value="",
    )
    product_model.objects.create(
        configuration_id=configuration.id,
        code="weekend",
        name="Weekend",
        description="",
        price_minor=12_000,
        capacity=200,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    minor_policy_model.objects.create(
        configuration_id=configuration.id,
        enabled=False,
        minor_age_threshold=18,
        guardian_notice_version="",
        jurisdiction_code="",
        review_reference="legacy-review",
        reviewed_by_id=actor.id,
        reviewed_at=timezone.now(),
    )

    migrated_executor = _migrate(REGISTRATION_AFTER)
    migrated_apps = _historical_apps(migrated_executor, REGISTRATION_AFTER)
    migrated_template_model = migrated_apps.get_model(
        "registration", "RegistrationTemplate"
    )
    migrated_configuration_model = migrated_apps.get_model(
        "registration", "RegistrationConfiguration"
    )
    setup_control_model = migrated_apps.get_model(
        "registration", "RegistrationSetupControl"
    )
    catalog_control_model = migrated_apps.get_model(
        "registration", "RegistrationTemplateCatalogControl"
    )
    setup_receipt_model = migrated_apps.get_model(
        "registration", "RegistrationSetupCommandReceipt"
    )
    catalog_receipt_model = migrated_apps.get_model(
        "registration", "RegistrationTemplateCatalogCommandReceipt"
    )

    migrated_template = migrated_template_model.objects.get(pk=template.id)
    migrated_configuration = migrated_configuration_model.objects.get(
        pk=configuration.id
    )
    assert len(migrated_template.content_digest) == 64
    assert len(migrated_configuration.content_digest) == 64
    assert migrated_template.provenance_status == "legacy_unknown"
    assert migrated_configuration.provenance_status == "legacy_unknown"
    assert migrated_configuration.origin == "published_template"
    assert migrated_configuration.source_version == 4
    assert (
        migrated_configuration.source_content_digest == migrated_template.content_digest
    )
    assert migrated_configuration.source_configuration_id is None
    assert migrated_configuration.source_imported_at is None
    assert migrated_configuration.source_imported_by_id is None
    assert migrated_configuration.created_in_setup_version is None
    assert migrated_configuration.last_changed_in_setup_version is None
    assert migrated_template.created_in_catalog_version is None
    assert migrated_template.last_changed_in_catalog_version is None

    setup_control = setup_control_model.objects.get(edition_id=target_edition.id)
    assert setup_control.organization_id == organization.id
    assert setup_control.aggregate_version == 1
    assert setup_control.origin == "legacy_existing"
    assert setup_control.provenance_status == "legacy_unknown"
    assert not setup_control_model.objects.filter(edition_id=empty_edition.id).exists()
    catalog_control = catalog_control_model.objects.get(organization_id=organization.id)
    assert catalog_control.aggregate_version == 1
    assert catalog_control.provenance_status == "legacy_unknown"
    assert setup_receipt_model.objects.count() == 0
    assert catalog_receipt_model.objects.count() == 0

    first_template_digest = migrated_template.content_digest
    first_configuration_digest = migrated_configuration.content_digest
    _migrate(REGISTRATION_BEFORE)
    remigrated_executor = _migrate(REGISTRATION_AFTER)
    remigrated_apps = _historical_apps(remigrated_executor, REGISTRATION_AFTER)
    assert (
        remigrated_apps.get_model("registration", "RegistrationTemplate")
        .objects.get(pk=template.id)
        .content_digest
        == first_template_digest
    )
    assert (
        remigrated_apps.get_model("registration", "RegistrationConfiguration")
        .objects.get(pk=configuration.id)
        .content_digest
        == first_configuration_digest
    )


def test_setup_controls_receipts_and_targets_are_exact_and_append_only() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()
    actor = AccountFactory()
    with pytest.raises(ValidationError, match="edition scope"):
        RegistrationSetupControl(
            organization=other.organization,
            edition=edition,
            origin=RegistrationSetupOrigin.BLANK,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            aggregate_version=1,
        ).full_clean()

    with transaction.atomic(), pytest.raises(IntegrityError):
        RegistrationSetupControl.objects.bulk_create(
            [
                RegistrationSetupControl(
                    organization=edition.organization,
                    edition=edition,
                    origin=RegistrationSetupOrigin.BLANK,
                    aggregate_version=0,
                )
            ]
        )

    control = RegistrationSetupControl.objects.create(
        organization=edition.organization,
        edition=edition,
        origin=RegistrationSetupOrigin.LEGACY_EXISTING,
        provenance_status=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        aggregate_version=1,
    )
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=control,
        organization=edition.organization,
        edition=edition,
        action=RegistrationSetupCommandReceipt.Action.SETUP_STARTED,
        resulting_version=1,
        actor=actor,
        reason="Start a blank registration setup.",
        correlation_id=uuid4(),
        source_channel="admin_web",
        retry_key=uuid4(),
        request_digest="a" * 64,
    )
    target = RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        target_id=uuid4(),
        change_kind=RegistrationCommandChangeKind.CREATED,
        target_schema_version=1,
        content_digest="b" * 64,
    )
    receipt.reason = "Rewrite evidence."
    with pytest.raises(ValidationError, match="immutable"):
        receipt.save()
    target.change_kind = RegistrationCommandChangeKind.UPDATED
    with pytest.raises(ValidationError, match="immutable"):
        target.save()

    invalid = RegistrationSetupCommandReceipt(
        setup=control,
        organization=other.organization,
        edition=other,
        action=RegistrationSetupCommandReceipt.Action.SECTION_UPDATED,
        resulting_version=2,
        actor=actor,
        reason="Cross scope is forbidden.",
        correlation_id=uuid4(),
        source_channel="admin_web",
    )
    with pytest.raises(ValidationError, match="exact edition scope"):
        invalid.clean()


def test_template_catalog_receipts_and_complete_provenance_are_strict() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    catalog = RegistrationTemplateCatalogControl.objects.create(
        organization=edition.organization,
        aggregate_version=1,
        provenance_status=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
    )
    receipt = RegistrationTemplateCatalogCommandReceipt.objects.create(
        catalog=catalog,
        organization=edition.organization,
        action=(RegistrationTemplateCatalogCommandReceipt.Action.TEMPLATE_CREATED),
        resulting_version=1,
        actor=actor,
        reason="Create a reusable draft.",
        correlation_id=uuid4(),
        source_channel="admin_web",
        retry_key=uuid4(),
        request_digest="c" * 64,
    )
    target = RegistrationTemplateCatalogCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationTemplateCatalogCommandTarget.TargetKind.TEMPLATE,
        target_id=uuid4(),
        change_kind=RegistrationCommandChangeKind.CREATED,
        target_schema_version=1,
        content_digest="d" * 64,
    )
    with pytest.raises(ValidationError, match="retention workflow"):
        receipt.delete()
    with pytest.raises(ValidationError, match="retention workflow"):
        target.delete()

    configuration = RegistrationConfigurationFactory()
    configuration.provenance_status = RegistrationProvenanceStatus.COMPLETE
    configuration.origin = RegistrationSetupOrigin.LEGACY_EXISTING
    configuration.content_digest = "e" * 64
    configuration.created_in_setup_version = 1
    configuration.last_changed_in_setup_version = 1
    with pytest.raises(ValidationError, match="cannot claim complete provenance"):
        configuration.full_clean()

    configuration.origin = RegistrationSetupOrigin.BLANK
    configuration.full_clean()
