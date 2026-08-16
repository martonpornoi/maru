from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.configuration_lifecycle import (
    activate_registration_configuration,
    review_registration_configuration,
)
from maru.registration.models import (
    MinorRegistrationPolicy,
    RegistrationCommandChangeKind,
    RegistrationConfiguration,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupVersionConflictError,
    start_registration_setup,
)
from maru.registration.setup_content import configuration_content_digest
from maru.registration.setup_definition_commands import create_admission_product
from maru.registration.setup_section_commands import (
    RegistrationSetupConfigurationUnavailableError,
    RegistrationSetupSectionDependencyError,
    create_registration_section,
    delete_registration_section,
    move_registration_section,
    update_registration_section,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationQuestionFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _grant(actor: Account, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )


def _start_blank(
    *,
    actor: Account,
    edition: EventEdition,
) -> tuple[RegistrationSetupControl, RegistrationConfiguration]:
    result = start_registration_setup(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        source_kind=RegistrationSetupOrigin.BLANK,
        source_id=None,
        name="Attendee registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the registration setup.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        RegistrationSetupControl.objects.get(pk=result.setup_id),
        RegistrationConfiguration.objects.get(pk=result.configuration_id),
    )


def _create_values(
    *,
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    key: str,
    expected_version: int,
    after_section_id: UUID | None = None,
    retry_key: UUID | None = None,
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "key": key,
        "title": key.replace("-", " ").title(),
        "description": f"Details for {key}.",
        "after_section_id": after_section_id,
        "expected_version": expected_version,
        "reason": f"Add the {key} section.",
        "retry_key": retry_key or uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _synchronize_configuration_digest(
    configuration: RegistrationConfiguration,
) -> str:
    sections = tuple(configuration.sections.order_by("position", "key", "id"))
    questions = tuple(configuration.questions.order_by("position", "key", "id"))
    products = tuple(configuration.products.order_by("position", "code", "id"))
    policy = MinorRegistrationPolicy.objects.filter(configuration=configuration).first()
    digest = configuration_content_digest(
        name=configuration.name,
        schema_version=configuration.version,
        opens_at=configuration.opens_at,
        closes_at=configuration.closes_at,
        capacity=configuration.capacity,
        capacity_ceiling=configuration.capacity_ceiling,
        currency=configuration.currency,
        minimum_age=configuration.minimum_age,
        default_payment_window_minutes=configuration.default_payment_window_minutes,
        waitlist_enabled=configuration.waitlist_enabled,
        automatic_waitlist_promotion=configuration.automatic_waitlist_promotion,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=policy,
    )
    RegistrationConfiguration.objects.filter(pk=configuration.pk).update(
        content_digest=digest
    )
    configuration.refresh_from_db()
    return digest


def test_authorization_and_route_scope_are_resolved_before_input_parsing() -> None:
    target = EventEditionFactory()
    foreign = EventEditionFactory()
    actor = AccountFactory()
    unauthorized = AccountFactory()
    _grant(actor, target)
    _grant(actor, foreign)
    target_control, target_configuration = _start_blank(
        actor=actor,
        edition=target,
    )
    _, foreign_configuration = _start_blank(actor=actor, edition=foreign)

    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        create_registration_section(
            actor=unauthorized,
            organization_id=target.organization_id,
            series_id=target.series_id,
            edition_id=target.id,
            configuration_id=object(),  # type: ignore[arg-type]
            key=object(),  # type: ignore[arg-type]
            title=object(),  # type: ignore[arg-type]
            description=object(),  # type: ignore[arg-type]
            after_section_id=None,
            expected_version="invalid",  # type: ignore[arg-type]
            reason=object(),  # type: ignore[arg-type]
            retry_key=object(),  # type: ignore[arg-type]
            correlation_id=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        create_registration_section(
            actor=actor,
            organization_id=foreign.organization_id,
            series_id=foreign.series_id,
            edition_id=target.id,
            configuration_id=object(),  # type: ignore[arg-type]
            key=object(),  # type: ignore[arg-type]
            title=object(),  # type: ignore[arg-type]
            description=object(),  # type: ignore[arg-type]
            after_section_id=None,
            expected_version="invalid",  # type: ignore[arg-type]
            reason=object(),  # type: ignore[arg-type]
            retry_key=object(),  # type: ignore[arg-type]
            correlation_id=object(),  # type: ignore[arg-type]
        )
    foreign_values = _create_values(
        actor=actor,
        edition=target,
        configuration=foreign_configuration,
        key="foreign",
        expected_version=1,
    )
    with pytest.raises(RegistrationSetupConfigurationUnavailableError):
        create_registration_section(**foreign_values)

    target_control.refresh_from_db()
    assert target_control.aggregate_version == 1
    assert not RegistrationSection.objects.filter(
        configuration=target_configuration
    ).exists()


def test_create_records_stamps_evidence_and_exact_idempotent_replay() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start_blank(actor=actor, edition=edition)
    retry_key = uuid4()
    values = _create_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        key="profile",
        expected_version=1,
        retry_key=retry_key,
    )

    result = create_registration_section(**values)

    section = RegistrationSection.objects.get(pk=result.section_id)
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert result.resulting_version == 2
    assert result.replayed is False
    assert section.position == 10
    assert section.created_in_setup_version == 2
    assert section.last_changed_in_setup_version == 2
    assert control.aggregate_version == 2
    assert configuration.last_changed_in_setup_version == 2
    assert configuration.content_digest == result.configuration_content_digest
    receipt = RegistrationSetupCommandReceipt.objects.get(pk=result.receipt_id)
    assert receipt.action == RegistrationSetupCommandReceipt.Action.SECTION_CREATED
    assert receipt.resulting_version == 2
    assert receipt.targets.count() == 2
    assert (
        receipt.targets.get(
            target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION
        ).change_kind
        == RegistrationCommandChangeKind.CREATED
    )
    event = DomainEvent.objects.get(correlation_id=receipt.correlation_id)
    assert event.event_name == "registration.configuration.draft_changed.v1"
    assert event.payload == {
        "action": "section_created",
        "configuration_version": "1",
    }
    assert OutboxMessage.objects.get(event=event).status == OutboxMessage.Status.PENDING
    audit = AuditEvent.objects.get(correlation_id=receipt.correlation_id)
    assert audit.operation == "registration.setup.section.changed"
    event_count = DomainEvent.objects.count()

    replay = create_registration_section(**{**values, "correlation_id": uuid4()})
    assert replay.replayed is True
    assert replay.receipt_id == result.receipt_id
    assert replay.section_id == result.section_id
    assert replay.configuration_content_digest == result.configuration_content_digest
    assert DomainEvent.objects.count() == event_count

    with pytest.raises(RegistrationSetupRetryConflictError):
        create_registration_section(
            **{**values, "title": "Changed retry payload", "correlation_id": uuid4()}
        )
    with pytest.raises(RegistrationSetupVersionConflictError):
        create_registration_section(
            **{**values, "retry_key": uuid4(), "correlation_id": uuid4()}
        )
    assert RegistrationSection.objects.filter(configuration=configuration).count() == 1


def test_complete_update_renames_section_and_rejects_stale_or_active_writes() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    _, configuration = _start_blank(actor=actor, edition=edition)
    created = create_registration_section(
        **_create_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="profile",
            expected_version=1,
        )
    )

    updated = update_registration_section(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        section_id=created.section_id,
        key="attendee-profile",
        title="Attendee profile",
        description="Current badge-facing details.",
        expected_version=2,
        reason="Rename and completely refresh the section.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    section = RegistrationSection.objects.get(pk=created.section_id)
    assert updated.resulting_version == 3
    assert section.key == "attendee-profile"
    assert section.title == "Attendee profile"
    assert section.description == "Current badge-facing details."
    assert section.position == 10
    assert section.last_changed_in_setup_version == 3
    with pytest.raises(RegistrationSetupVersionConflictError):
        update_registration_section(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            section_id=section.id,
            key="stale-name",
            title="Stale name",
            description="Must not persist.",
            expected_version=2,
            reason="Attempt a stale update.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    product = create_admission_product(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        code="weekend",
        name="Weekend admission",
        description="Synthetic admission for the active-write boundary.",
        price_minor=12_000,
        capacity=400,
        entitlement_code="weekend-admission",
        entitlement_name="Weekend admission",
        sales_open_at=None,
        sales_close_at=None,
        required_capacity_codes=[],
        eligibility_explanation="",
        waitlist_enabled=True,
        payment_window_minutes=None,
        after_product_id=None,
        expected_version=updated.resulting_version,
        reason="Complete the synthetic configuration before activation.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    reviewed = review_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        review_note="",
        expected_version=product.resulting_version,
        reason="Review the exact synthetic configuration.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    activate_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        content_digest=configuration.content_digest,
        edition_name_confirmation=edition.name,
        expected_version=reviewed.resulting_version,
        reason="Activate the reviewed synthetic configuration.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(RegistrationSetupLifecycleConflictError):
        update_registration_section(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            section_id=section.id,
            key="active-name",
            title="Active name",
            description="Must remain immutable.",
            expected_version=3,
            reason="Attempt to change an active form.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    section.refresh_from_db()
    assert section.key == "attendee-profile"


def test_move_uses_exact_anchor_and_completely_renumbers_stable_positions() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start_blank(actor=actor, edition=edition)
    first = create_registration_section(
        **_create_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="first",
            expected_version=1,
        )
    )
    second = create_registration_section(
        **_create_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="second",
            expected_version=2,
            after_section_id=first.section_id,
        )
    )
    third = create_registration_section(
        **_create_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="third",
            expected_version=3,
            after_section_id=second.section_id,
        )
    )

    moved = move_registration_section(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        section_id=third.section_id,
        after_section_id=None,
        expected_version=4,
        reason="Move the third section to the beginning.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    ordered = tuple(
        RegistrationSection.objects.filter(configuration=configuration)
        .order_by("position", "key", "id")
        .values_list("id", "position", "last_changed_in_setup_version")
    )
    assert ordered == (
        (third.section_id, 10, 5),
        (first.section_id, 20, 5),
        (second.section_id, 30, 5),
    )
    assert moved.resulting_version == 5
    control.refresh_from_db()
    assert control.aggregate_version == 5
    move_receipt = RegistrationSetupCommandReceipt.objects.get(pk=moved.receipt_id)
    assert (
        move_receipt.targets.filter(
            target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION
        ).count()
        == 3
    )
    target = move_receipt.targets.get(
        target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION,
        target_id=third.section_id,
    )
    assert target.change_kind == RegistrationCommandChangeKind.MOVED


def test_create_rejects_the_sixty_fifth_section_without_partial_state() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start_blank(actor=actor, edition=edition)
    RegistrationSection.objects.bulk_create(
        [
            RegistrationSection(
                configuration=configuration,
                key=f"section-{index}",
                title=f"Section {index}",
                position=index * 10,
                created_in_setup_version=1,
                last_changed_in_setup_version=1,
            )
            for index in range(1, 65)
        ]
    )
    original_digest = _synchronize_configuration_digest(configuration)
    receipt_count = RegistrationSetupCommandReceipt.objects.filter(
        edition=edition
    ).count()

    with pytest.raises(RegistrationSetupLimitExceededError):
        create_registration_section(
            **_create_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                key="overflow",
                expected_version=1,
            )
        )

    control.refresh_from_db()
    configuration.refresh_from_db()
    assert control.aggregate_version == 1
    assert configuration.content_digest == original_digest
    assert RegistrationSection.objects.filter(configuration=configuration).count() == 64
    assert (
        RegistrationSetupCommandReceipt.objects.filter(edition=edition).count()
        == receipt_count
    )


def test_delete_refuses_question_dependency_then_preserves_zero_section_state() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start_blank(actor=actor, edition=edition)
    created = create_registration_section(
        **_create_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="profile",
            expected_version=1,
        )
    )
    section = RegistrationSection.objects.get(pk=created.section_id)
    question = RegistrationQuestionFactory(
        configuration=configuration,
        section=section,
        created_in_setup_version=2,
        last_changed_in_setup_version=2,
    )
    _synchronize_configuration_digest(configuration)
    retry_key = uuid4()
    values = {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "section_id": section.id,
        "expected_version": 2,
        "reason": "Remove the unused profile section.",
        "retry_key": retry_key,
        "correlation_id": uuid4(),
        "source_channel": "test",
    }

    with pytest.raises(RegistrationSetupSectionDependencyError):
        delete_registration_section(**values)
    control.refresh_from_db()
    assert control.aggregate_version == 2
    assert RegistrationSection.objects.filter(pk=section.pk).exists()
    assert (
        RegistrationSetupCommandReceipt.objects.filter(
            edition=edition,
            resulting_version=3,
        ).count()
        == 0
    )

    question.delete()
    _synchronize_configuration_digest(configuration)
    deleted = delete_registration_section(**{**values, "correlation_id": uuid4()})

    assert deleted.resulting_version == 3
    assert not RegistrationSection.objects.filter(configuration=configuration).exists()
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert control.aggregate_version == 3
    assert configuration.last_changed_in_setup_version == 3
    target = RegistrationSetupCommandReceipt.objects.get(
        pk=deleted.receipt_id
    ).targets.get(target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION)
    assert target.target_id == section.id
    assert target.change_kind == RegistrationCommandChangeKind.DELETED
    assert len(target.content_digest) == 64
    replay = delete_registration_section(**{**values, "correlation_id": uuid4()})
    assert replay.replayed is True
    assert replay.receipt_id == deleted.receipt_id
    assert replay.section_id == section.id
    assert not RegistrationSection.objects.filter(configuration=configuration).exists()


@pytest.mark.parametrize("dependency", ["append_audit", "publish_domain_event"])
def test_audit_or_outbox_failure_rolls_back_section_and_all_evidence(
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start_blank(actor=actor, edition=edition)
    original_digest = configuration.content_digest
    receipt_count = RegistrationSetupCommandReceipt.objects.filter(
        edition=edition
    ).count()
    audit_count = AuditEvent.objects.filter(event_edition_id=edition.id).count()
    event_count = DomainEvent.objects.filter(event_edition_id=edition.id).count()
    outbox_count = OutboxMessage.objects.filter(
        organization_id=edition.organization_id
    ).count()

    def fail_dependency(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("synthetic section dependency failure")

    monkeypatch.setattr(
        f"maru.registration.setup_section_commands.{dependency}",
        fail_dependency,
    )
    with pytest.raises(RuntimeError, match="section dependency"):
        create_registration_section(
            **_create_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                key="rollback",
                expected_version=1,
            )
        )

    control.refresh_from_db()
    configuration.refresh_from_db()
    assert control.aggregate_version == 1
    assert configuration.last_changed_in_setup_version == 1
    assert configuration.content_digest == original_digest
    assert not RegistrationSection.objects.filter(configuration=configuration).exists()
    assert (
        RegistrationSetupCommandReceipt.objects.filter(edition=edition).count()
        == receipt_count
    )
    assert AuditEvent.objects.filter(event_edition_id=edition.id).count() == audit_count
    assert (
        DomainEvent.objects.filter(event_edition_id=edition.id).count() == event_count
    )
    assert (
        OutboxMessage.objects.filter(organization_id=edition.organization_id).count()
        == outbox_count
    )
