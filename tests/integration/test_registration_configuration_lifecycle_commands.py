from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple
from datetime import date, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.configuration_lifecycle import (
    RegistrationConfigurationActiveConflictError,
    RegistrationConfigurationReviewRequiredError,
    RegistrationConfigurationValidationError,
    activate_registration_configuration,
    preview_registration_configuration,
    review_registration_configuration,
)
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Entitlement,
    GuardianConsent,
    MinorRegistrationPolicy,
    PaymentAttempt,
    PaymentIntent,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    Registration,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateProduct,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupDependencyError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
    start_registration_setup,
)
from maru.registration.setup_content import (
    canonical_digest,
    configuration_content_digest,
)
from maru.registration.setup_definition_commands import (
    create_admission_product,
    create_registration_profile_extension_field,
    create_registration_question,
    set_minor_registration_policy,
)
from maru.registration.setup_section_commands import create_registration_section
from maru.registration.template_lifecycle import publish_registration_template
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
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
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _start(
    actor: Account,
    edition: EventEdition,
    *,
    source_kind: str = RegistrationSetupOrigin.BLANK,
    source_id: UUID | None = None,
    minimum_age: int = 18,
) -> tuple[RegistrationSetupControl, RegistrationConfiguration]:
    opens_at = timezone.now() + timedelta(days=1)
    result = start_registration_setup(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        source_kind=source_kind,
        source_id=source_id,
        name="Synthetic attendee registration",
        opens_at=opens_at,
        closes_at=opens_at + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=minimum_age,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the synthetic lifecycle test setup.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        RegistrationSetupControl.objects.get(pk=result.setup_id),
        RegistrationConfiguration.objects.get(pk=result.configuration_id),
    )


def _add_product(
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    expected_version: int,
    *,
    code: str = "weekend",
) -> int:
    result = create_admission_product(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        code=code,
        name=f"{code.title()} admission",
        description="Synthetic admission for lifecycle tests.",
        price_minor=12_000,
        capacity=400,
        entitlement_code=f"{code}-admission",
        entitlement_name=f"{code.title()} admission",
        sales_open_at=None,
        sales_close_at=None,
        required_capacity_codes=[],
        eligibility_explanation="",
        waitlist_enabled=True,
        payment_window_minutes=None,
        after_product_id=None,
        expected_version=expected_version,
        reason=f"Add the {code} synthetic product.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    configuration.refresh_from_db()
    return result.resulting_version


def _ready_setup(
    *,
    with_questions: bool = False,
    minimum_age: int = 18,
) -> tuple[Account, EventEdition, RegistrationSetupControl, RegistrationConfiguration]:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition, minimum_age=minimum_age)
    version = _add_product(actor, edition, configuration, control.aggregate_version)
    if with_questions:
        source = create_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            key="attending-dinner",
            label="Attend the synthetic dinner?",
            help_text="Controls the conditional meal note.",
            field_type=QuestionFieldType.BOOLEAN,
            required=True,
            options=[],
            purpose="Plan synthetic catering.",
            visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
            classification=QuestionClassification.PERSONAL,
            condition_question_key="",
            condition_value="",
            section_id=None,
            after_question_id=None,
            expected_version=version,
            reason="Add the dinner choice.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        conditional = create_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            key="meal-note",
            label="Synthetic meal note",
            help_text="Visible only when dinner is selected.",
            field_type=QuestionFieldType.SHORT_TEXT,
            required=True,
            options=[],
            purpose="Plan synthetic catering.",
            visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
            classification=QuestionClassification.PERSONAL,
            condition_question_key="attending-dinner",
            condition_value="true",
            section_id=None,
            after_question_id=source.target_id,
            expected_version=source.resulting_version,
            reason="Add the conditional meal note.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        create_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            key="staff-note",
            label="Synthetic staff note",
            help_text="Registration staff input only.",
            field_type=QuestionFieldType.SHORT_TEXT,
            required=False,
            options=[],
            purpose="Record a synthetic operational note.",
            visibility=QuestionVisibility.REGISTRATION_STAFF,
            classification=QuestionClassification.PERSONAL,
            condition_question_key="",
            condition_value="",
            section_id=None,
            after_question_id=conditional.target_id,
            expected_version=conditional.resulting_version,
            reason="Add the synthetic staff note.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    control.refresh_from_db()
    configuration.refresh_from_db()
    return actor, edition, control, configuration


def _review_values(
    *,
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    expected_version: int,
    retry_key=None,
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "content_digest": configuration.content_digest,
        "review_note": "",
        "expected_version": expected_version,
        "reason": "Review the exact synthetic registration generation.",
        "retry_key": retry_key or uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _activation_values(
    *,
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    expected_version: int,
    retry_key=None,
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "content_digest": configuration.content_digest,
        "edition_name_confirmation": edition.name,
        "expected_version": expected_version,
        "reason": "Activate the reviewed synthetic configuration.",
        "retry_key": retry_key or uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _active_prior_source() -> tuple[Account, EventEdition, RegistrationConfiguration]:
    actor, edition, control, configuration = _ready_setup()
    review_values = _review_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=control.aggregate_version,
    )
    review_values["review_note"] = "Reviewed against the exact prior-edition source."
    reviewed = review_registration_configuration(**review_values)  # type: ignore[arg-type]
    activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
        )
    )
    configuration.refresh_from_db()
    return actor, edition, configuration


def _prior_target_setup(
    *,
    actor: Account,
    source_edition: EventEdition,
    source_configuration: RegistrationConfiguration,
    year: int,
) -> tuple[EventEdition, RegistrationSetupControl, RegistrationConfiguration]:
    edition = EventEditionFactory(
        organization=source_edition.organization,
        series=source_edition.series,
        starts_on=date(year, 8, 1),
        ends_on=date(year, 8, 4),
    )
    _grant(actor, edition)
    control, configuration = _start(
        actor,
        edition,
        source_kind=RegistrationSetupOrigin.PRIOR_EDITION,
        source_id=source_configuration.id,
    )
    return edition, control, configuration


def _fresh_digest(configuration: RegistrationConfiguration) -> str:
    sections = tuple(configuration.sections.order_by("position", "key", "id"))
    questions = tuple(configuration.questions.order_by("position", "key", "id"))
    products = tuple(configuration.products.order_by("position", "code", "id"))
    policy = MinorRegistrationPolicy.objects.filter(configuration=configuration).first()
    return configuration_content_digest(
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


def _published_template_setup() -> tuple[
    Account,
    EventEdition,
    RegistrationSetupControl,
    RegistrationConfiguration,
    RegistrationTemplate,
]:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        created_by_id=actor.id,
    )
    RegistrationTemplateProduct.objects.create(
        template=template,
        code="weekend",
        name="Weekend admission",
        description="Synthetic admission copied from a published template.",
        price_minor=12_000,
        capacity=400,
        position=10,
        entitlement_code="weekend-admission",
        entitlement_name="Weekend admission",
        waitlist_enabled=True,
    )
    publish_registration_template(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=template.id,
        expected_version=0,
        reason="Publish the exact registration configuration template.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    template.refresh_from_db()
    control, configuration = _start(
        actor,
        edition,
        source_kind=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        source_id=template.id,
    )
    return actor, edition, control, configuration, template


def test_preview_visibility_and_answer_contract_has_no_domain_writes() -> None:
    actor, edition, control, configuration = _ready_setup(with_questions=True)
    section = RegistrationSection.objects.create(
        configuration=configuration,
        key="meal",
        title="Synthetic meal",
        description="A grouped preview section.",
        position=10,
    )
    RegistrationQuestion.objects.filter(
        configuration=configuration,
        key="meal-note",
    ).update(section=section)
    digest = _fresh_digest(configuration)
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        content_digest=digest
    )
    configuration.refresh_from_db()
    before = {
        "accounts": Account.objects.count(),
        "configurations": RegistrationConfiguration.objects.count(),
        "registrations": Registration.objects.count(),
        "submissions": RegistrationSubmission.objects.count(),
        "payments": PaymentAttempt.objects.count(),
        "payment_intents": PaymentIntent.objects.count(),
        "entitlements": Entitlement.objects.count(),
        "consents": GuardianConsent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
        "audit": AuditEvent.objects.count(),
    }
    configuration_state = (
        configuration.status,
        configuration.content_digest,
        configuration.last_changed_in_setup_version,
    )
    setup_version = control.aggregate_version

    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        attendee_answers={"attending-dinner": True, "meal-note": "Vegan"},
        staff_answers={
            "attending-dinner": True,
            "meal-note": "Vegan",
            "staff-note": "Synthetic operational note",
        },
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert preview.aggregate_version == control.aggregate_version
    assert preview.review_resolved is False
    assert preview.validation_issues == ()
    assert preview.attendee_answers.valid is True
    assert preview.staff_answers.valid is True
    assert preview.attendee_answers.schema_keys == (
        "attending-dinner",
        "meal-note",
    )
    assert preview.staff_answers.schema_keys == (
        "attending-dinner",
        "meal-note",
        "staff-note",
    )
    assert preview.sections[0].title == "Synthetic meal"
    staff_question = next(
        item for item in preview.questions if item.key == "staff-note"
    )
    assert staff_question.attendee_input is False
    assert staff_question.staff_input is True
    assert not any(astuple(preview.forbidden_effects))
    after = {
        "accounts": Account.objects.count(),
        "configurations": RegistrationConfiguration.objects.count(),
        "registrations": Registration.objects.count(),
        "submissions": RegistrationSubmission.objects.count(),
        "payments": PaymentAttempt.objects.count(),
        "payment_intents": PaymentIntent.objects.count(),
        "entitlements": Entitlement.objects.count(),
        "consents": GuardianConsent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
        "audit": AuditEvent.objects.count(),
    }
    assert after == {**before, "audit": before["audit"] + 1}
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert (
        configuration.status,
        configuration.content_digest,
        configuration.last_changed_in_setup_version,
    ) == configuration_state
    assert control.aggregate_version == setup_version
    audit = AuditEvent.objects.latest("created_at")
    assert audit.operation == "registration.setup.preview"
    assert audit.safe_metadata["target_count"] == 6


def test_preview_audit_failure_releases_no_projection_or_state_change() -> None:
    actor, edition, control, configuration = _ready_setup(with_questions=True)
    before_counts = {
        "registrations": Registration.objects.count(),
        "submissions": RegistrationSubmission.objects.count(),
        "payment_attempts": PaymentAttempt.objects.count(),
        "payment_intents": PaymentIntent.objects.count(),
        "entitlements": Entitlement.objects.count(),
        "consents": GuardianConsent.objects.count(),
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }
    configuration_state = (
        configuration.status,
        configuration.content_digest,
        configuration.review_required,
        configuration.review_note,
        configuration.last_changed_in_setup_version,
    )
    setup_version = control.aggregate_version
    with (
        patch(
            "maru.registration.configuration_lifecycle.append_audit",
            side_effect=RuntimeError("synthetic preview audit failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic preview audit failure"),
    ):
        preview_registration_configuration(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            attendee_answers={"attending-dinner": True, "meal-note": "Vegan"},
            staff_answers={},
            correlation_id=uuid4(),
            source_channel="test",
        )
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert (
        configuration.status,
        configuration.content_digest,
        configuration.review_required,
        configuration.review_note,
        configuration.last_changed_in_setup_version,
    ) == configuration_state
    assert control.aggregate_version == setup_version
    assert {
        "registrations": Registration.objects.count(),
        "submissions": RegistrationSubmission.objects.count(),
        "payment_attempts": PaymentAttempt.objects.count(),
        "payment_intents": PaymentIntent.objects.count(),
        "entitlements": Entitlement.objects.count(),
        "consents": GuardianConsent.objects.count(),
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before_counts


def test_zero_question_review_and_activation_are_separate_replayable_commands() -> None:
    actor, edition, control, configuration = _ready_setup()
    review_retry = uuid4()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
            retry_key=review_retry,
        )
    )
    assert reviewed.resulting_version == control.aggregate_version + 1
    assert reviewed.status == ConfigurationStatus.DRAFT
    assert reviewed.review_resolved is True
    assert reviewed.replayed is False
    configuration.refresh_from_db()
    assert configuration.review_required is False
    assert configuration.status == ConfigurationStatus.DRAFT
    review_receipt = RegistrationSetupCommandReceipt.objects.get(pk=reviewed.receipt_id)
    assert review_receipt.action == review_receipt.Action.CONFIGURATION_REVIEWED
    assert review_receipt.targets.get().change_kind == "reviewed"

    activation_retry = uuid4()
    activated = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
            retry_key=activation_retry,
        )
    )
    assert activated.resulting_version == reviewed.resulting_version + 1
    assert activated.status == ConfigurationStatus.ACTIVE
    assert activated.review_resolved is True
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.ACTIVE
    assert configuration.review_note == ""
    assert (
        RegistrationSetupCommandReceipt.objects.filter(
            setup_id=reviewed.setup_id,
            action__in=(
                RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
                RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
            ),
        ).count()
        == 2
    )
    assert (
        DomainEvent.objects.filter(
            aggregate_id=reviewed.setup_id,
            event_name="registration.configuration.draft_changed.v1",
            payload__action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
        ).count()
        == 1
    )
    assert (
        DomainEvent.objects.filter(
            aggregate_id=reviewed.setup_id,
            event_name="registration.configuration.activated.v1",
        ).count()
        == 1
    )
    assert (
        OutboxMessage.objects.filter(event__aggregate_id=reviewed.setup_id).count() >= 2
    )

    replay = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
            retry_key=activation_retry,
        )
    )
    assert replay.receipt_id == activated.receipt_id
    assert replay.replayed is True
    historical_review = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
            retry_key=review_retry,
        )
    )
    assert historical_review.receipt_id == reviewed.receipt_id
    assert historical_review.status == ConfigurationStatus.DRAFT
    assert historical_review.replayed is True
    changed = _activation_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=reviewed.resulting_version,
        retry_key=activation_retry,
    )
    changed["reason"] = "A different activation reason conflicts."
    with pytest.raises(RegistrationSetupRetryConflictError):
        activate_registration_configuration(**changed)  # type: ignore[arg-type]

    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert preview.review_resolved is True


@pytest.mark.parametrize(
    "mutation_kind",
    ["section", "question", "product", "minor_policy", "configuration"],
)
def test_every_content_mutation_invalidates_receipt_derived_review(
    mutation_kind: str,
) -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    current_version = reviewed.resulting_version
    if mutation_kind == "section":
        result = create_registration_section(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            key="details",
            title="Synthetic details",
            description="",
            after_section_id=None,
            expected_version=current_version,
            reason="Add a section after review.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        current_version = result.resulting_version
    elif mutation_kind == "question":
        result = create_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            key="note",
            label="Synthetic note",
            help_text="",
            field_type=QuestionFieldType.SHORT_TEXT,
            required=False,
            options=[],
            purpose="Exercise review invalidation.",
            visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
            classification=QuestionClassification.PERSONAL,
            condition_question_key="",
            condition_value="",
            section_id=None,
            after_question_id=None,
            expected_version=current_version,
            reason="Add a question after review.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        current_version = result.resulting_version
    elif mutation_kind == "product":
        current_version = _add_product(
            actor,
            edition,
            configuration,
            current_version,
            code="day",
        )
    elif mutation_kind == "minor_policy":
        result = set_minor_registration_policy(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            enabled=True,
            minor_age_threshold=19,
            guardian_notice_version="synthetic-v1",
            jurisdiction_code="XX-SYNTHETIC",
            review_reference="synthetic-review",
            expected_version=current_version,
            reason="Add a minor policy after review.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        current_version = result.resulting_version
    else:
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            name="Changed synthetic registration"
        )
        configuration.refresh_from_db()
        digest = _fresh_digest(configuration)
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            content_digest=digest
        )
    configuration.refresh_from_db()
    assert configuration.review_required is False
    with pytest.raises(RegistrationConfigurationReviewRequiredError):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=current_version,
            )
        )


def test_preview_reports_complete_semantic_failures_without_partial_activation() -> (
    None
):
    actor, edition, control, configuration = _ready_setup()
    product = AdmissionProduct.objects.get(configuration=configuration)
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        waitlist_enabled=False,
        automatic_waitlist_promotion=False,
    )
    AdmissionProduct.objects.filter(pk=product.id).update(
        capacity=configuration.capacity + 1,
        waitlist_enabled=True,
        sales_open_at=configuration.opens_at - timedelta(minutes=1),
        payment_window_minutes=14,
        required_capacity_codes=["unavailable-capacity"],
        eligibility_explanation="Synthetic restricted offer.",
    )
    configuration.refresh_from_db()
    digest = _fresh_digest(configuration)
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        content_digest=digest
    )
    configuration.refresh_from_db()

    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    codes = {issue.code for issue in preview.validation_issues}
    assert {
        "product_capacity_exceeds_configuration",
        "product_waitlist_exceeds_configuration",
        "product_sales_before_registration",
        "product_payment_window_invalid",
        "product_capacity_code_unavailable",
    } <= codes
    with pytest.raises(RegistrationConfigurationValidationError) as captured:
        review_registration_configuration(
            **_review_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=control.aggregate_version,
            )
        )
    assert codes <= {issue.code for issue in captured.value.issues}
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.DRAFT


def test_missing_or_forged_review_evidence_never_activates() -> None:
    actor, edition, control, configuration = _ready_setup()
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        review_required=False
    )
    with pytest.raises(RegistrationConfigurationReviewRequiredError):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=control.aggregate_version,
            )
        )

    forged_version = control.aggregate_version + 1
    forged_retry_key = uuid4()
    forged_reason = "Forge otherwise matching synthetic review evidence."
    RegistrationSetupControl.objects.filter(pk=control.id).update(
        aggregate_version=forged_version
    )
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        last_changed_in_setup_version=forged_version,
    )
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=control,
        organization=edition.organization,
        edition=edition,
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
        resulting_version=forged_version,
        actor=actor,
        reason=forged_reason,
        correlation_id=uuid4(),
        source_channel="test",
        retry_key=forged_retry_key,
        request_digest=canonical_digest(
            {
                "action": RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
                "actor_id": str(actor.id),
                "organization_id": str(edition.organization_id),
                "series_id": str(edition.series_id),
                "edition_id": str(edition.id),
                "configuration_id": str(configuration.id),
                "content_digest": configuration.content_digest,
                "review_note": "",
                "expected_version": forged_version - 1,
                "reason": forged_reason,
            }
        ),
    )
    RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        target_id=configuration.id,
        change_kind="reviewed",
        target_schema_version=configuration.version,
        content_digest=configuration.content_digest,
    )
    with pytest.raises(RegistrationConfigurationReviewRequiredError):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=forged_version,
            )
        )


def test_review_outbox_failure_rolls_back_review_state_and_evidence() -> None:
    actor, edition, control, configuration = _ready_setup()
    before_counts = {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }
    configuration_state = (
        configuration.status,
        configuration.review_required,
        configuration.review_note,
        configuration.last_changed_in_setup_version,
    )
    setup_version = control.aggregate_version
    with (
        patch(
            "maru.effects.services.OutboxMessage.objects.create",
            side_effect=RuntimeError("synthetic review outbox failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic review outbox failure"),
    ):
        review_registration_configuration(
            **_review_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=setup_version,
            )
        )
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert (
        configuration.status,
        configuration.review_required,
        configuration.review_note,
        configuration.last_changed_in_setup_version,
    ) == configuration_state
    assert control.aggregate_version == setup_version
    assert {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before_counts


@pytest.mark.parametrize(
    "failure_target",
    [
        "maru.registration.configuration_lifecycle."
        "RegistrationSetupCommandReceipt.objects.create",
        "maru.registration.configuration_lifecycle."
        "RegistrationSetupCommandTarget.objects.create",
        "maru.registration.configuration_lifecycle.append_audit",
        "maru.effects.services.OutboxMessage.objects.create",
    ],
)
def test_activation_evidence_failure_rolls_back_every_write(
    failure_target: str,
) -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    before = {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }
    with (
        patch(
            failure_target,
            side_effect=RuntimeError("synthetic evidence failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic evidence failure"),
    ):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=reviewed.resulting_version,
            )
        )
    configuration.refresh_from_db()
    control.refresh_from_db()
    assert configuration.status == ConfigurationStatus.DRAFT
    assert configuration.activated_at is None
    assert control.aggregate_version == reviewed.resulting_version
    assert {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "targets": RegistrationSetupCommandTarget.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before


def test_activation_refuses_existing_active_version_without_retiring_it() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    existing = RegistrationConfigurationFactory(
        edition=edition,
        organization=edition.organization,
        version=2,
    )
    RegistrationConfiguration.objects.filter(pk=existing.id).update(
        status=ConfigurationStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    with pytest.raises(RegistrationConfigurationActiveConflictError):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=reviewed.resulting_version,
            )
        )
    existing.refresh_from_db()
    configuration.refresh_from_db()
    assert existing.status == ConfigurationStatus.ACTIVE
    assert configuration.status == ConfigurationStatus.DRAFT


def test_commands_authorize_before_protected_input_parsing() -> None:
    _actor, edition, _control, _configuration = _ready_setup()
    unauthorized = AccountFactory()
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        review_registration_configuration(
            actor=unauthorized,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=object(),  # type: ignore[arg-type]
            content_digest=object(),  # type: ignore[arg-type]
            review_note=object(),  # type: ignore[arg-type]
            expected_version=object(),  # type: ignore[arg-type]
            reason=object(),  # type: ignore[arg-type]
            retry_key=object(),  # type: ignore[arg-type]
            correlation_id=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        preview_registration_configuration(
            actor=unauthorized,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=object(),  # type: ignore[arg-type]
            attendee_answers=object(),
            staff_answers=object(),
            correlation_id=object(),  # type: ignore[arg-type]
        )


def test_stale_digest_confirmation_and_lifecycle_fail_closed() -> None:
    actor, edition, control, configuration = _ready_setup()
    stale = _review_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=control.aggregate_version + 1,
    )
    with pytest.raises(RegistrationSetupVersionConflictError):
        review_registration_configuration(**stale)  # type: ignore[arg-type]
    wrong_digest = _review_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=control.aggregate_version,
    )
    wrong_digest["content_digest"] = "0" * 64
    with pytest.raises(RegistrationSetupVersionConflictError):
        review_registration_configuration(**wrong_digest)  # type: ignore[arg-type]

    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    wrong_name = _activation_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=reviewed.resulting_version,
    )
    wrong_name["edition_name_confirmation"] = edition.name.lower()
    with pytest.raises(ValidationError) as captured:
        activate_registration_configuration(**wrong_name)  # type: ignore[arg-type]
    assert getattr(captured.value, "error_dict", {}).get("edition_name_confirmation")

    EventEdition.objects.filter(pk=edition.id).update(
        lifecycle=EventEdition.Lifecycle.CANCELLED,
        lifecycle_version=F("lifecycle_version") + 1,
        aggregate_version=F("aggregate_version") + 1,
    )
    with pytest.raises(RegistrationSetupLifecycleConflictError):
        activate_registration_configuration(
            **_activation_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=reviewed.resulting_version,
            )
        )


def test_malformed_minor_review_evidence_is_a_bounded_validation_issue() -> None:
    actor, edition, control, configuration = _ready_setup()
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(minimum_age=16)
    MinorRegistrationPolicy.objects.create(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="synthetic-v1",
        jurisdiction_code="XX-SYNTHETIC",
        review_reference="synthetic-review",
        reviewed_by=actor,
        reviewed_at=timezone.now(),
    )
    configuration.refresh_from_db()
    digest = _fresh_digest(configuration)
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        content_digest=digest
    )
    configuration.refresh_from_db()
    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert "minor_policy_review_invalid" in {
        issue.code for issue in preview.validation_issues
    }
    control.refresh_from_db()
    assert control.aggregate_version >= 1


def test_forged_activation_retry_never_reports_active_for_persisted_draft() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    configuration.refresh_from_db()
    retry_key = uuid4()
    values = _activation_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=reviewed.resulting_version,
        retry_key=retry_key,
    )
    resulting_version = reviewed.resulting_version + 1
    RegistrationSetupControl.objects.filter(pk=control.id).update(
        aggregate_version=resulting_version
    )
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=control,
        organization=edition.organization,
        edition=edition,
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
        resulting_version=resulting_version,
        actor=actor,
        reason=str(values["reason"]),
        correlation_id=values["correlation_id"],
        source_channel="test",
        retry_key=retry_key,
        request_digest=canonical_digest(
            {
                "action": (
                    RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED
                ),
                "actor_id": str(actor.id),
                "organization_id": str(edition.organization_id),
                "series_id": str(edition.series_id),
                "edition_id": str(edition.id),
                "configuration_id": str(configuration.id),
                "content_digest": configuration.content_digest,
                "edition_name_confirmation": edition.name,
                "expected_version": reviewed.resulting_version,
                "reason": values["reason"],
            }
        ),
    )
    RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        target_id=configuration.id,
        change_kind="activated",
        target_schema_version=configuration.version,
        content_digest=configuration.content_digest,
    )

    with pytest.raises(RegistrationSetupStateConflictError):
        activate_registration_configuration(**values)  # type: ignore[arg-type]
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.DRAFT
    assert configuration.last_changed_in_setup_version == reviewed.resulting_version


def test_nested_bounds_and_one_sided_sales_window_block_review() -> None:
    actor, edition, control, configuration = _ready_setup(with_questions=True)
    RegistrationSection.objects.bulk_create(
        [
            RegistrationSection(
                configuration=configuration,
                key="empty-heading",
                title="",
                description="Synthetic invalid section.",
                position=40,
            )
        ]
    )
    RegistrationQuestion.objects.filter(
        configuration=configuration,
        key="attending-dinner",
    ).update(help_text="h" * 2_001)
    AdmissionProduct.objects.filter(configuration=configuration).update(
        description="d" * 2_001,
        sales_open_at=configuration.opens_at,
        sales_close_at=None,
    )
    digest = _fresh_digest(configuration)
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        content_digest=digest
    )
    configuration.refresh_from_db()

    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    issues = {(issue.code, issue.target_kind) for issue in preview.validation_issues}
    assert ("blank", "section") in issues
    assert ("registration_question_help_too_long", "question") in issues
    assert ("registration_product_description_too_long", "product") in issues
    assert ("product_sales_period_incomplete", "product") in issues
    with pytest.raises(RegistrationConfigurationValidationError):
        review_registration_configuration(
            **_review_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                expected_version=control.aggregate_version,
            )
        )


def test_minor_review_remains_durable_after_reviewer_deactivation() -> None:
    reviewer, edition, control, configuration = _ready_setup(minimum_age=16)
    policy_result = set_minor_registration_policy(
        actor=reviewer,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="HU",
        review_reference="review-2026-08-03",
        expected_version=control.aggregate_version,
        reason="Record reviewed minor-registration evidence.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    Account.objects.filter(pk=reviewer.id).update(is_active=False)
    manager = AccountFactory()
    _grant(manager, edition)
    configuration.refresh_from_db()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=manager,
            edition=edition,
            configuration=configuration,
            expected_version=policy_result.resulting_version,
        )
    )
    activated = activate_registration_configuration(
        **_activation_values(
            actor=manager,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
        )
    )
    assert activated.status == ConfigurationStatus.ACTIVE


def test_profile_command_does_not_invalidate_active_configuration_review() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    activated = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
        )
    )
    configuration.refresh_from_db()
    configuration_version = configuration.last_changed_in_setup_version
    profile = create_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        key="arrival-note",
        label="Arrival note",
        help_text="Record one synthetic arrival preference.",
        field_type=QuestionFieldType.SHORT_TEXT,
        options=[],
        purpose="Plan synthetic arrivals.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        required=False,
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=activated.resulting_version,
        reason="Create an independent profile definition.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    control.refresh_from_db()
    configuration.refresh_from_db()
    assert control.aggregate_version == profile.resulting_version
    assert configuration.last_changed_in_setup_version == configuration_version
    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert preview.review_resolved is True


def test_historical_policy_version_does_not_invalidate_replay() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    retry_key = uuid4()
    activation_values = _activation_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=reviewed.resulting_version,
        retry_key=retry_key,
    )
    activated = activate_registration_configuration(
        **activation_values  # type: ignore[arg-type]
    )
    with patch(
        "maru.registration.configuration_lifecycle.POLICY_VERSION",
        "2099-12-31.9",
    ):
        replay = activate_registration_configuration(
            **activation_values  # type: ignore[arg-type]
        )
        preview = preview_registration_configuration(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert replay.receipt_id == activated.receipt_id
    assert replay.replayed is True
    assert preview.review_resolved is True


def test_rebinding_to_another_complete_template_is_blocked_by_database() -> None:
    actor, edition, _control, configuration, _template = _published_template_setup()
    rebound = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        code="rebound-template",
        name="Rebound template",
        created_by_id=actor.id,
    )
    RegistrationTemplateProduct.objects.create(
        template=rebound,
        code="rebound-admission",
        name="Rebound admission",
        price_minor=12_000,
        capacity=400,
        position=10,
        entitlement_code="rebound-admission",
        entitlement_name="Rebound admission",
    )
    published = publish_registration_template(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=rebound.id,
        expected_version=1,
        reason="Publish a second exact registration template.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    digest = published.content_digest
    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            source_template=rebound,
            source_version=rebound.version,
            source_content_digest=digest,
        )
    configuration.refresh_from_db()
    preview = preview_registration_configuration(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert preview.source_content_digest == configuration.source_content_digest


def test_concurrent_same_retry_activation_commits_one_transition() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    retry_key = uuid4()

    def run():
        close_old_connections()
        try:
            return activate_registration_configuration(
                **_activation_values(
                    actor=actor,
                    edition=edition,
                    configuration=configuration,
                    expected_version=reviewed.resulting_version,
                    retry_key=retry_key,
                )
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run(), range(2)))
    receipt_ids = {result.receipt_id for result in results}
    assert len(receipt_ids) == 1
    assert sorted(result.replayed for result in results) == [False, True]
    assert (
        RegistrationSetupCommandReceipt.objects.filter(
            setup_id=reviewed.setup_id,
            action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
        ).count()
        == 1
    )


def test_concurrent_different_retry_activation_commits_one_transition() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )

    def run(retry_key: UUID):
        close_old_connections()
        try:
            try:
                result = activate_registration_configuration(
                    **_activation_values(
                        actor=actor,
                        edition=edition,
                        configuration=configuration,
                        expected_version=reviewed.resulting_version,
                        retry_key=retry_key,
                    )
                )
            except RegistrationSetupLifecycleConflictError as error:
                return "conflict", type(error)
            return "activated", result
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (uuid4(), uuid4())))
    assert sorted(kind for kind, _value in results) == ["activated", "conflict"]
    assert (
        RegistrationSetupCommandReceipt.objects.filter(
            setup_id=reviewed.setup_id,
            action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
        ).count()
        == 1
    )
    assert (
        DomainEvent.objects.filter(
            aggregate_id=reviewed.setup_id,
            event_name="registration.configuration.activated.v1",
        ).count()
        == 1
    )
    assert (
        OutboxMessage.objects.filter(
            event__aggregate_id=reviewed.setup_id,
            event__event_name="registration.configuration.activated.v1",
        ).count()
        == 1
    )


def test_exact_prior_edition_source_can_be_reviewed_and_activated() -> None:
    actor, source_edition, source_configuration = _active_prior_source()
    edition, control, configuration = _prior_target_setup(
        actor=actor,
        source_edition=source_edition,
        source_configuration=source_configuration,
        year=2031,
    )
    assert configuration.source_edition_id == source_edition.id
    assert configuration.source_configuration_id == source_configuration.id
    assert configuration.source_version == source_configuration.version
    assert configuration.source_content_digest == source_configuration.content_digest
    review_values = _review_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=control.aggregate_version,
    )
    review_values["review_note"] = "Reviewed against the exact prior-edition source."
    reviewed = review_registration_configuration(**review_values)  # type: ignore[arg-type]
    activated = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
        )
    )
    assert activated.status == ConfigurationStatus.ACTIVE


def test_imported_prior_source_survives_later_authorized_date_changes() -> None:
    actor, source_edition, source_configuration = _active_prior_source()
    edition, control, configuration = _prior_target_setup(
        actor=actor,
        source_edition=source_edition,
        source_configuration=source_configuration,
        year=2031,
    )
    EventEdition.objects.filter(pk=source_edition.id).update(
        starts_on=date(2035, 8, 1),
        ends_on=date(2035, 8, 4),
        aggregate_version=F("aggregate_version") + 1,
    )
    review_values = _review_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=control.aggregate_version,
    )
    review_values["review_note"] = (
        "Retain eligibility proved when this copy was imported."
    )
    reviewed = review_registration_configuration(**review_values)  # type: ignore[arg-type]
    activated = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=reviewed.resulting_version,
        )
    )
    assert activated.status == ConfigurationStatus.ACTIVE


def test_cross_series_prior_minor_policy_retains_exact_source_evidence() -> None:
    actor, source_edition, control, source_configuration = _ready_setup(minimum_age=16)
    policy = set_minor_registration_policy(
        actor=actor,
        organization_id=source_edition.organization_id,
        series_id=source_edition.series_id,
        edition_id=source_edition.id,
        configuration_id=source_configuration.id,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-cross-series-v1",
        jurisdiction_code="HU",
        review_reference="cross-series-review-2026-08-03",
        expected_version=control.aggregate_version,
        reason="Record exact reusable minor-policy review evidence.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    source_configuration.refresh_from_db()
    reviewed_source = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=source_edition,
            configuration=source_configuration,
            expected_version=policy.resulting_version,
        )
    )
    activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=source_edition,
            configuration=source_configuration,
            expected_version=reviewed_source.resulting_version,
        )
    )
    source_configuration.refresh_from_db()

    target_series = ConventionSeriesFactory(organization=source_edition.organization)
    target_edition = EventEditionFactory(
        organization=source_edition.organization,
        series=target_series,
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    _grant(actor, target_edition)
    target_control, target_configuration = _start(
        actor,
        target_edition,
        source_kind=RegistrationSetupOrigin.PRIOR_EDITION,
        source_id=source_configuration.id,
        minimum_age=16,
    )
    target_review = _review_values(
        actor=actor,
        edition=target_edition,
        configuration=target_configuration,
        expected_version=target_control.aggregate_version,
    )
    target_review["review_note"] = "Review the exact cross-series imported source."
    reviewed_target = review_registration_configuration(
        **target_review  # type: ignore[arg-type]
    )
    activated_target = activate_registration_configuration(
        **_activation_values(
            actor=actor,
            edition=target_edition,
            configuration=target_configuration,
            expected_version=reviewed_target.resulting_version,
        )
    )
    assert activated_target.status == ConfigurationStatus.ACTIVE


def test_exact_activation_replay_survives_later_edition_rename() -> None:
    actor, edition, control, configuration = _ready_setup()
    reviewed = review_registration_configuration(
        **_review_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            expected_version=control.aggregate_version,
        )
    )
    retry_key = uuid4()
    activation_values = _activation_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        expected_version=reviewed.resulting_version,
        retry_key=retry_key,
    )
    activated = activate_registration_configuration(
        **activation_values  # type: ignore[arg-type]
    )
    EventEdition.objects.filter(pk=edition.id).update(
        name="Renamed after exact activation",
        aggregate_version=F("aggregate_version") + 1,
    )
    replay = activate_registration_configuration(
        **{**activation_values, "correlation_id": uuid4()}  # type: ignore[arg-type]
    )
    assert replay.replayed is True
    assert replay.receipt_id == activated.receipt_id


def test_prior_edition_source_version_and_digest_mismatch_fail_closed() -> None:
    actor, source_edition, source_configuration = _active_prior_source()
    _edition, _control, configuration = _prior_target_setup(
        actor=actor,
        source_edition=source_edition,
        source_configuration=source_configuration,
        year=2031,
    )
    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            source_version=source_configuration.version + 1
        )
    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            source_content_digest="f" * 64,
        )


def test_current_digest_tamper_fails_before_projection() -> None:
    actor, edition, _control, configuration = _ready_setup()
    RegistrationConfiguration.objects.filter(pk=configuration.id).update(
        content_digest="f" * 64
    )
    with pytest.raises(RegistrationSetupDependencyError):
        preview_registration_configuration(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_source_digest_tamper_fails_before_projection() -> None:
    _actor, _edition, _control, configuration, _template = _published_template_setup()
    with (
        pytest.raises(
            DatabaseError,
            match="source binding is immutable",
        ),
        transaction.atomic(),
    ):
        RegistrationConfiguration.objects.filter(pk=configuration.id).update(
            source_content_digest="f" * 64
        )
