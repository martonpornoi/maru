from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration import setup_queries
from maru.registration.configuration_lifecycle import (
    activate_registration_configuration,
    review_registration_configuration,
)
from maru.registration.models import (
    ConfigurationStatus,
    Registration,
    RegistrationConfiguration,
    RegistrationProvenanceStatus,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    TemplateStatus,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupSourceUnavailableError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
    start_registration_setup,
)
from maru.registration.setup_content import template_content_digest
from maru.registration.setup_definition_commands import (
    create_admission_product,
    create_registration_question,
)
from maru.registration.setup_queries import get_registration_setup_workspace
from maru.registration.setup_section_commands import create_registration_section
from maru.registration.starter_catalog import (
    platform_registration_starter_by_provenance,
    platform_registration_starters,
)
from maru.registration.template_lifecycle import publish_registration_template
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
    RegistrationTemplateFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _grant(actor: Account, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )


def _blank_command_values(
    *, actor: Account, edition: EventEdition, retry_key=None
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "source_kind": RegistrationSetupOrigin.BLANK,
        "source_id": None,
        "name": "Attendee registration",
        "opens_at": timezone.now() + timedelta(days=1),
        "closes_at": timezone.now() + timedelta(days=30),
        "capacity": 500,
        "currency": "EUR",
        "minimum_age": 18,
        "default_payment_window_minutes": 1_440,
        "waitlist_enabled": True,
        "automatic_waitlist_promotion": True,
        "expected_version": 0,
        "reason": "Start the reviewed attendee registration setup.",
        "retry_key": retry_key or uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _publish_template_with_content(edition: EventEdition, actor: Account):
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        code="attendee-registration",
        name="Attendee registration source",
        version=7,
        created_by_id=actor.id,
    )
    section = RegistrationTemplateSection.objects.create(
        template=template,
        key="profile",
        title="Profile",
        description="Badge details.",
        position=20,
    )
    RegistrationTemplateQuestion.objects.create(
        template=template,
        section=section,
        key="badge-name",
        label="Badge name",
        field_type="short_text",
        required=True,
        position=20,
        purpose="Print the badge.",
    )
    RegistrationTemplateProduct.objects.create(
        template=template,
        code="weekend",
        name="Weekend admission",
        price_minor=12_000,
        capacity=500,
        position=20,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    publish_registration_template(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=template.id,
        expected_version=0,
        reason="Publish the exact reusable registration source.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    template.refresh_from_db()
    return template


def _active_source_configuration(
    edition: EventEdition,
    source_manager: Account,
) -> RegistrationConfiguration:
    _grant(source_manager, edition)
    values = _blank_command_values(actor=source_manager, edition=edition)
    values.update(name="Prior exact registration", capacity=345)
    started = start_registration_setup(**values)
    configuration = RegistrationConfiguration.objects.get(pk=started.configuration_id)
    section = create_registration_section(
        actor=source_manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        key="details",
        title="Details",
        description="",
        after_section_id=None,
        expected_version=started.aggregate_version,
        reason="Add the exact prior section.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    question = create_registration_question(
        actor=source_manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        key="arrival-note",
        label="Arrival note",
        help_text="",
        field_type="short_text",
        required=False,
        options=[],
        purpose="Plan the exact prior arrival.",
        visibility="attendee_and_staff",
        classification="C2",
        condition_question_key="",
        condition_value="",
        section_id=section.section_id,
        after_question_id=None,
        expected_version=section.resulting_version,
        reason="Add the exact prior question.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    product = create_admission_product(
        actor=source_manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        code="prior-weekend",
        name="Prior weekend",
        description="",
        price_minor=12_000,
        capacity=345,
        entitlement_code="prior-weekend-admission",
        entitlement_name="Prior weekend admission",
        sales_open_at=None,
        sales_close_at=None,
        required_capacity_codes=[],
        eligibility_explanation="",
        waitlist_enabled=True,
        payment_window_minutes=None,
        after_product_id=None,
        expected_version=question.resulting_version,
        reason="Add the exact prior product.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    reviewed = review_registration_configuration(
        actor=source_manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        review_note="",
        expected_version=product.resulting_version,
        reason="Review the exact prior configuration.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    activate_registration_configuration(
        actor=source_manager,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        edition_name_confirmation=edition.name,
        expected_version=reviewed.resulting_version,
        reason="Activate the exact prior configuration.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    return configuration


def test_blank_start_creates_one_complete_zero_question_setup_and_projection() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    before = get_registration_setup_workspace(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert before.setup_state == "not_configured"
    assert before.aggregate_version == 0

    result = start_registration_setup(
        **_blank_command_values(actor=actor, edition=edition)
    )

    assert result.aggregate_version == 1
    assert result.configuration_version == 1
    assert result.source_kind == RegistrationSetupOrigin.BLANK
    assert result.question_count == 0
    assert result.section_count == 0
    assert result.product_count == 0
    assert len(result.content_digest) == 64
    configuration = RegistrationConfiguration.objects.get(pk=result.configuration_id)
    assert configuration.provenance_status == RegistrationProvenanceStatus.COMPLETE
    assert configuration.created_in_setup_version == 1
    assert configuration.last_changed_in_setup_version == 1
    assert configuration.source_imported_at is None
    assert (
        RegistrationSetupControl.objects.get(pk=result.setup_id).aggregate_version == 1
    )
    receipt = RegistrationSetupCommandReceipt.objects.get(pk=result.receipt_id)
    assert receipt.resulting_version == 1
    assert receipt.targets.count() == 1
    assert (
        receipt.targets.get().target_kind
        == RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
    )
    audit = AuditEvent.objects.get(correlation_id=receipt.correlation_id)
    assert audit.operation == "registration.setup.started"
    event = DomainEvent.objects.get(correlation_id=receipt.correlation_id)
    assert event.aggregate_type == "registration.setup"
    assert event.payload == {"configuration_version": "1", "source_kind": "blank"}
    assert OutboxMessage.objects.get(event=event).status == OutboxMessage.Status.PENDING

    after = get_registration_setup_workspace(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert after.setup_state == "draft_in_review"
    assert after.aggregate_version == 1
    assert after.current_configuration is not None
    assert after.current_configuration.id == configuration.id


def test_platform_administrator_starts_setup_without_becoming_a_subject() -> None:
    edition = EventEditionFactory()
    platform_actor = AccountFactory(is_staff=True, is_superuser=True)

    result = start_registration_setup(
        **_blank_command_values(actor=platform_actor, edition=edition)
    )

    assert result.replayed is False
    assert platform_actor.account_kind == Account.Kind.PLATFORM_ADMINISTRATOR
    assert not OrganizationMembership.objects.filter(account=platform_actor).exists()
    assert not Participation.objects.filter(account=platform_actor).exists()
    assert not Registration.objects.filter(account=platform_actor).exists()
    assert not edition.participations.filter(account=platform_actor).exists()
    assert (
        RegistrationConfiguration.objects.get(pk=result.configuration_id).created_by_id
        == platform_actor.id
    )


def test_same_retry_replays_and_changed_payload_or_new_key_conflicts() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    retry_key = uuid4()
    values = _blank_command_values(actor=actor, edition=edition, retry_key=retry_key)
    first = start_registration_setup(**values)
    event_count = DomainEvent.objects.count()

    replay_values = {**values, "correlation_id": uuid4()}
    replay = start_registration_setup(**replay_values)
    assert replay.replayed is True
    assert replay.configuration_id == first.configuration_id
    assert replay.receipt_id == first.receipt_id
    assert DomainEvent.objects.count() == event_count

    with pytest.raises(RegistrationSetupRetryConflictError):
        start_registration_setup(**{**replay_values, "name": "Changed retry payload"})
    with pytest.raises(RegistrationSetupVersionConflictError):
        start_registration_setup(**{**replay_values, "retry_key": uuid4()})
    assert RegistrationConfiguration.objects.filter(edition=edition).count() == 1


def test_exact_published_template_is_copied_with_complete_stamps() -> None:
    target = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, target)
    chosen = _publish_template_with_content(target, actor)
    other = RegistrationTemplateFactory(
        organization=target.organization,
        series=target.series,
        code="other-template",
        version=1,
        created_by_id=actor.id,
    )
    other.status = TemplateStatus.PUBLISHED
    other.published_at = timezone.now()
    other.save(update_fields=("status", "published_at", "updated_at"))
    values = _blank_command_values(actor=actor, edition=target)
    values.update(
        source_kind=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        source_id=chosen.id,
    )

    result = start_registration_setup(**values)

    copied = RegistrationConfiguration.objects.get(pk=result.configuration_id)
    assert copied.source_template_id == chosen.id
    assert copied.source_version == 7
    assert copied.source_configuration_id is None
    assert copied.source_imported_by_id == actor.id
    assert len(copied.source_content_digest) == 64
    assert copied.questions.get().key == "badge-name"
    assert copied.products.get().code == "weekend"
    assert copied.sections.get().created_in_setup_version == 1
    assert copied.questions.get().last_changed_in_setup_version == 1
    assert copied.products.get().created_in_setup_version == 1
    copied.questions.update(label="Target-only wording")
    assert chosen.questions.get().label == "Badge name"
    assert not copied.questions.filter(key__startswith="other").exists()


def test_platform_starter_is_explicit_copy_on_write_versioned_and_replay_safe() -> None:
    starter = platform_registration_starters()[0]
    target = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, target)
    retry_key = uuid4()
    values = _blank_command_values(
        actor=actor,
        edition=target,
        retry_key=retry_key,
    )
    values.update(
        source_kind=RegistrationSetupOrigin.PLATFORM_STARTER,
        source_id=starter.source_id,
        capacity=1_000,
    )

    first = start_registration_setup(**values)
    replay = start_registration_setup(**{**values, "correlation_id": uuid4()})

    assert replay.replayed is True
    assert replay.receipt_id == first.receipt_id
    copied = RegistrationConfiguration.objects.get(pk=first.configuration_id)
    assert copied.origin == RegistrationSetupOrigin.PLATFORM_STARTER
    assert copied.source_version == starter.version
    assert copied.source_content_digest == starter.content_digest
    assert copied.source_imported_by_id == actor.id
    assert copied.source_imported_at is not None
    assert copied.source_template_id is None
    assert copied.source_configuration_id is None
    assert copied.source_edition_id is None
    assert copied.review_required is True
    assert copied.sections.get().id != starter.sections[0].id
    assert copied.products.get().id != starter.products[0].id
    assert copied.products.get().name == starter.products[0].name
    copied.products.update(name="Organizer-owned admission")
    assert starter.products[0].name == "Standard admission"
    assert (
        platform_registration_starter_by_provenance(
            version=copied.source_version,
            content_digest=copied.source_content_digest,
        )
        == starter
    )
    assert (
        platform_registration_starter_by_provenance(
            version=starter.version + 1,
            content_digest=starter.content_digest,
        )
        is None
    )

    foreign = EventEditionFactory()
    foreign_actor = AccountFactory()
    _grant(foreign_actor, foreign)
    foreign_values = _blank_command_values(actor=foreign_actor, edition=foreign)
    foreign_values.update(
        source_kind=RegistrationSetupOrigin.PLATFORM_STARTER,
        source_id=starter.source_id,
        capacity=1_000,
    )
    foreign_result = start_registration_setup(**foreign_values)
    foreign_copy = RegistrationConfiguration.objects.get(
        pk=foreign_result.configuration_id
    )
    assert foreign_copy.organization_id == foreign.organization_id
    assert foreign_copy.id != copied.id
    assert foreign_copy.products.get().id != copied.products.get().id
    assert foreign_copy.products.get().name == starter.products[0].name


def test_prior_source_requires_exact_active_authorized_earlier_configuration() -> None:
    source = EventEditionFactory(starts_on=date(2030, 8, 1), ends_on=date(2030, 8, 4))
    target = EventEditionFactory(
        organization=source.organization,
        series=source.series,
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    source_configuration = _active_source_configuration(source, AccountFactory())
    actor = AccountFactory()
    _grant(actor, target)
    values = _blank_command_values(actor=actor, edition=target)
    values.update(
        source_kind=RegistrationSetupOrigin.PRIOR_EDITION,
        source_id=source_configuration.id,
        opens_at=None,
        closes_at=None,
        capacity=None,
        currency=None,
        minimum_age=None,
        default_payment_window_minutes=None,
        waitlist_enabled=None,
        automatic_waitlist_promotion=None,
    )

    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        start_registration_setup(**values)
    assert not RegistrationSetupControl.objects.filter(edition=target).exists()

    _grant(actor, source)
    result = start_registration_setup(**values)
    copied = RegistrationConfiguration.objects.get(pk=result.configuration_id)
    assert copied.source_configuration_id == source_configuration.id
    assert copied.source_edition_id == source.id
    assert copied.source_version == source_configuration.version
    assert copied.capacity == 345
    assert copied.questions.get().key == "arrival-note"
    assert copied.products.get().code == "prior-weekend"


def test_query_lists_only_exact_eligible_and_authorized_sources() -> None:
    source = EventEditionFactory(starts_on=date(2030, 8, 1), ends_on=date(2030, 8, 4))
    target = EventEditionFactory(
        organization=source.organization,
        series=source.series,
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    actor = AccountFactory()
    _grant(actor, target)
    template = _publish_template_with_content(target, actor)
    source_configuration = _active_source_configuration(source, AccountFactory())
    legacy_template = RegistrationTemplateFactory(
        organization=target.organization,
        series=target.series,
        code="legacy-template",
        created_by_id=actor.id,
    )
    legacy_template_digest = template_content_digest(
        template=legacy_template,
        sections=(),
        questions=(),
        products=(),
    )
    type(legacy_template).objects.filter(pk=legacy_template.id).update(
        status=TemplateStatus.PUBLISHED,
        published_at=timezone.now(),
        content_digest=legacy_template_digest,
    )
    legacy_source = EventEditionFactory(
        organization=source.organization,
        series=source.series,
        starts_on=date(2029, 8, 1),
        ends_on=date(2029, 8, 4),
    )
    legacy_configuration = RegistrationConfigurationFactory(
        edition=legacy_source,
        status=ConfigurationStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    _grant(actor, legacy_source)

    first = get_registration_setup_workspace(
        actor=actor,
        organization_id=target.organization_id,
        series_id=target.series_id,
        edition_id=target.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert [option.source_id for option in first.published_templates] == [template.id]
    assert legacy_template.id not in {
        option.source_id for option in first.published_templates
    }
    assert first.prior_configurations == ()

    _grant(actor, source)
    second = get_registration_setup_workspace(
        actor=actor,
        organization_id=target.organization_id,
        series_id=target.series_id,
        edition_id=target.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert [option.source_id for option in second.prior_configurations] == [
        source_configuration.id
    ]
    assert legacy_configuration.id not in {
        option.source_id for option in second.prior_configurations
    }


def test_source_listing_rejects_complete_looking_template_without_effect_graph() -> (
    None
):
    target = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, target)
    published = _publish_template_with_content(target, actor)
    forged = RegistrationTemplateFactory(
        organization=target.organization,
        series=target.series,
        code="forged-complete-template",
        created_by_id=actor.id,
    )
    digest = template_content_digest(
        template=forged,
        sections=(),
        questions=(),
        products=(),
    )
    with transaction.atomic():
        type(forged).objects.filter(pk=forged.id).update(
            status=TemplateStatus.PUBLISHED,
            published_at=timezone.now(),
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            content_digest=digest,
            created_in_catalog_version=1,
            last_changed_in_catalog_version=1,
        )
        workspace = get_registration_setup_workspace(
            actor=actor,
            organization_id=target.organization_id,
            series_id=target.series_id,
            edition_id=target.id,
            correlation_id=uuid4(),
            source_channel="test",
        )
        assert [item.source_id for item in workspace.published_templates] == [
            published.id
        ]
        transaction.set_rollback(True)


def test_prior_source_listing_rejects_raw_active_state_without_lifecycle_graph() -> (
    None
):
    source = EventEditionFactory(
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
    )
    target = EventEditionFactory(
        organization=source.organization,
        series=source.series,
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    actor = AccountFactory()
    _grant(actor, source)
    started = start_registration_setup(
        **_blank_command_values(actor=actor, edition=source)
    )
    source_configuration = RegistrationConfiguration.objects.get(
        pk=started.configuration_id
    )
    _grant(actor, target)
    with transaction.atomic():
        RegistrationConfiguration.objects.filter(pk=source_configuration.id).update(
            status=ConfigurationStatus.ACTIVE,
            activated_at=timezone.now(),
            review_required=False,
        )
        command = _blank_command_values(actor=actor, edition=target)
        command.update(
            source_kind=RegistrationSetupOrigin.PRIOR_EDITION,
            source_id=source_configuration.id,
        )
        with pytest.raises(RegistrationSetupSourceUnavailableError):
            start_registration_setup(**command)
        workspace = get_registration_setup_workspace(
            actor=actor,
            organization_id=target.organization_id,
            series_id=target.series_id,
            edition_id=target.id,
            correlation_id=uuid4(),
            source_channel="test",
        )
        assert source_configuration.id not in {
            item.source_id for item in workspace.prior_configurations
        }
        transaction.set_rollback(True)


def test_query_retries_one_projection_movement_then_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    movement = iter((("a", None), ("b", None), ("c", None), ("d", None)))
    monkeypatch.setattr(
        setup_queries,
        "_projection_generation",
        lambda **_kwargs: next(movement),
    )

    with pytest.raises(RegistrationSetupStateConflictError):
        get_registration_setup_workspace(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert not AuditEvent.objects.filter(operation="registration.setup.read").exists()


def test_cross_tenant_or_nonpublished_source_fails_without_partial_state() -> None:
    target = EventEditionFactory()
    foreign = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, target)
    draft_template = RegistrationTemplateFactory(
        organization=target.organization,
        series=target.series,
        created_by_id=actor.id,
    )
    foreign_actor = AccountFactory()
    _grant(foreign_actor, foreign)
    foreign_template = _publish_template_with_content(foreign, foreign_actor)
    values = _blank_command_values(actor=actor, edition=target)
    values.update(
        source_kind=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        source_id=draft_template.id,
    )

    with pytest.raises(RegistrationSetupSourceUnavailableError):
        start_registration_setup(**values)
    with pytest.raises(RegistrationSetupSourceUnavailableError):
        start_registration_setup(**{**values, "source_id": foreign_template.id})
    assert not RegistrationConfiguration.objects.filter(edition=target).exists()
    assert not RegistrationSetupControl.objects.filter(edition=target).exists()
    assert not RegistrationSetupCommandReceipt.objects.filter(edition=target).exists()


def test_published_legacy_unknown_template_is_not_an_eligible_source() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    _grant(actor, edition)
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        created_by_id=actor.id,
    )
    digest = template_content_digest(
        template=template,
        sections=(),
        questions=(),
        products=(),
    )
    type(template).objects.filter(pk=template.id).update(
        status=TemplateStatus.PUBLISHED,
        published_at=timezone.now(),
        content_digest=digest,
    )
    assert template.provenance_status == RegistrationProvenanceStatus.LEGACY_UNKNOWN
    values = _blank_command_values(actor=actor, edition=edition)
    values["source_kind"] = RegistrationSetupOrigin.PUBLISHED_TEMPLATE
    values["source_id"] = template.id

    with pytest.raises(RegistrationSetupSourceUnavailableError):
        start_registration_setup(**values)  # type: ignore[arg-type]
    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()
    assert not RegistrationSetupControl.objects.filter(edition=edition).exists()


def test_audit_failure_rolls_back_configuration_control_receipt_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic audit dependency failure")

    monkeypatch.setattr(
        "maru.registration.setup_commands.append_audit",
        fail_audit,
    )
    with pytest.raises(RuntimeError, match="audit dependency"):
        start_registration_setup(**_blank_command_values(actor=actor, edition=edition))

    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()
    assert not RegistrationSetupControl.objects.filter(edition=edition).exists()
    assert not RegistrationSetupCommandReceipt.objects.filter(edition=edition).exists()
    assert not DomainEvent.objects.filter(event_edition_id=edition.id).exists()
    assert not OutboxMessage.objects.filter(event__event_edition_id=edition.id).exists()


def test_mismatched_target_route_fails_closed_before_creating_state() -> None:
    target = EventEditionFactory()
    foreign = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, target)
    values = _blank_command_values(actor=actor, edition=target)

    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        get_registration_setup_workspace(
            actor=actor,
            organization_id=target.organization_id,
            series_id=foreign.series_id,
            edition_id=target.id,
            correlation_id=uuid4(),
            source_channel="test",
        )
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        start_registration_setup(
            **{
                **values,
                "organization_id": foreign.organization_id,
                "series_id": foreign.series_id,
            }
        )

    assert not RegistrationConfiguration.objects.filter(edition=target).exists()
    assert not RegistrationSetupControl.objects.filter(edition=target).exists()


def test_outbox_failure_rolls_back_domain_audit_and_command_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)

    def fail_effect(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic outbox dependency failure")

    monkeypatch.setattr(
        "maru.registration.setup_commands.publish_domain_event",
        fail_effect,
    )
    with pytest.raises(RuntimeError, match="outbox dependency"):
        start_registration_setup(**_blank_command_values(actor=actor, edition=edition))

    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()
    assert not RegistrationSetupControl.objects.filter(edition=edition).exists()
    assert not RegistrationSetupCommandReceipt.objects.filter(edition=edition).exists()
    assert not AuditEvent.objects.filter(event_edition_id=edition.id).exists()
    assert not DomainEvent.objects.filter(event_edition_id=edition.id).exists()
