from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.events.services import EventEditionDetails, update_event_edition
from maru.identity.models import Account
from maru.registration import setup_definition_commands
from maru.registration.models import (
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    Registration,
    RegistrationCommandChangeKind,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationProfileExtensionValueRevision,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
)
from maru.registration.profile_extension_values import (
    append_profile_extension_value,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
    start_registration_setup,
)
from maru.registration.setup_content import (
    canonical_digest,
    profile_extension_payload,
    target_content_digest,
)
from maru.registration.setup_definition_commands import (
    RegistrationSetupProfileFieldDependencyError,
    RegistrationSetupProfileFieldImmutableError,
    RegistrationSetupProfileFieldReviewRequiredError,
    RegistrationSetupProfileFieldSuccessorConflictError,
    RegistrationSetupProfileFieldUnavailableError,
    activate_registration_profile_extension_field,
    approve_registration_profile_extension_field,
    create_registration_profile_extension_field,
    retire_registration_profile_extension_field,
    start_registration_profile_extension_field_successor,
    update_registration_profile_extension_field,
)
from tests.factories import (
    AccountFactory,
    AdmissionProductFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
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
) -> tuple[RegistrationSetupControl, RegistrationConfiguration]:
    result = start_registration_setup(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        source_kind=RegistrationSetupOrigin.BLANK,
        source_id=None,
        name="Synthetic lifecycle registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start a synthetic profile-definition lifecycle.",
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
    expected_version: int,
    key: str = "diet-note",
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "key": key,
        "label": "Diet note",
        "help_text": "Record the current synthetic dietary note.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "options": [],
        "purpose": "Maintain one current attendee preference.",
        "classification": QuestionClassification.PERSONAL,
        "attendee_visible": True,
        "writer_policy": ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        "required": False,
        "source_template_id": None,
        "source_prior_edition_id": None,
        "after_field_id": None,
        "expected_version": expected_version,
        "reason": "Create the synthetic current-profile definition.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _lifecycle_values(
    *,
    actor: Account,
    edition: EventEdition,
    field_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID | None = None,
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "field_id": field_id,
        "expected_version": expected_version,
        "reason": reason,
        "retry_key": retry_key or uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def _draft_world() -> tuple[
    Account,
    EventEdition,
    RegistrationSetupControl,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
]:
    actor = AccountFactory()
    edition = EventEditionFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    created = create_registration_profile_extension_field(
        **_create_values(actor=actor, edition=edition, expected_version=1)
    )
    return (
        actor,
        edition,
        control,
        configuration,
        RegistrationProfileExtensionField.objects.get(pk=created.target_id),
    )


def _active_world() -> tuple[
    Account,
    EventEdition,
    RegistrationSetupControl,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
]:
    actor, edition, control, configuration, field = _draft_world()
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Approve the synthetic profile definition.",
        )
    )
    activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=approved.resulting_version,
            reason="Activate the reviewed synthetic profile definition.",
        )
    )
    control.refresh_from_db()
    field.refresh_from_db()
    return actor, edition, control, configuration, field


def _legacy_template_field(
    *,
    actor: Account,
    edition: EventEdition,
    control: RegistrationSetupControl,
    template: object,
) -> RegistrationProfileExtensionField:
    return RegistrationProfileExtensionField.objects.create(
        organization=edition.organization,
        edition=edition,
        key="diet-note",
        version=1,
        label="Diet note",
        help_text="Preserve a synthetic historical template source.",
        field_type=QuestionFieldType.SHORT_TEXT,
        options=[],
        purpose="Maintain one current attendee preference.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        required=False,
        position=0,
        source_template=template,
        review_status=ProfileExtensionReviewStatus.PENDING,
        status=ProfileExtensionStatus.DRAFT,
        created_by=actor,
        created_in_setup_version=control.aggregate_version,
        last_changed_in_setup_version=control.aggregate_version,
    )


def _value_revision(
    *,
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    field: RegistrationProfileExtensionField,
) -> RegistrationProfileExtensionValueRevision:
    attendee = AccountFactory()
    participation = ParticipationFactory(
        account=attendee,
        organization=edition.organization,
        edition=edition,
    )
    # This value-lifecycle fixture needs a historical registration subject,
    # not a raw activation of the complete Page 10 setup aggregate.
    registration_configuration = RegistrationConfigurationFactory(
        organization=edition.organization,
        edition=edition,
        version=2,
    )
    product = AdmissionProductFactory(configuration=registration_configuration)
    RegistrationConfiguration.objects.filter(
        pk=registration_configuration.id,
    ).update(status="active", activated_at=timezone.now())
    registration_configuration.refresh_from_db()
    submitted_at = timezone.now()
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=participation,
        account=attendee,
        configuration=registration_configuration,
        product=product,
        reference="MARU-LIFE-001",
        state=Registration.State.CONFIRMED,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=submitted_at,
        confirmed_at=submitted_at,
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
    )
    result = append_profile_extension_value(
        actor=attendee,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        field_id=field.id,
        value="synthetic gluten-free meal",
        expected_sequence=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        request_id=None,
        source_channel="test",
    )
    return RegistrationProfileExtensionValueRevision.objects.get(pk=result.revision_id)


def test_approve_activate_and_historical_replay_use_exact_receipt_evidence() -> None:
    actor, edition, control, _configuration, field = _draft_world()
    approval_retry = uuid4()
    approval_values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=field.id,
        expected_version=2,
        reason="Approve the exact synthetic definition.",
        retry_key=approval_retry,
    )
    approved = approve_registration_profile_extension_field(**approval_values)
    field.refresh_from_db()
    assert field.review_status == ProfileExtensionReviewStatus.APPROVED
    assert field.approved_by_id == actor.id
    assert field.approved_at is not None
    review_receipt = RegistrationSetupCommandReceipt.objects.get(pk=approved.receipt_id)
    assert review_receipt.action == review_receipt.Action.PROFILE_FIELD_REVIEWED
    review_target = review_receipt.targets.get()
    assert review_target.change_kind == "reviewed"
    assert review_target.target_schema_version == 1
    assert review_target.content_digest

    activation_retry = uuid4()
    activation_values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=field.id,
        expected_version=approved.resulting_version,
        reason="Activate the exact reviewed definition.",
        retry_key=activation_retry,
    )
    activated = activate_registration_profile_extension_field(**activation_values)
    field.refresh_from_db()
    control.refresh_from_db()
    assert field.status == ProfileExtensionStatus.ACTIVE
    assert control.aggregate_version == activated.resulting_version
    assert (
        AuditEvent.objects.filter(
            target_id=field.id,
            operation="registration.setup.profile_field.changed",
        ).count()
        == 3
    )
    assert DomainEvent.objects.filter(aggregate_id=control.id).count() == 4
    assert OutboxMessage.objects.filter(event__aggregate_id=control.id).count() == 4

    historical_review = approve_registration_profile_extension_field(
        **{**approval_values, "correlation_id": uuid4()}
    )
    historical_activation = activate_registration_profile_extension_field(
        **{**activation_values, "correlation_id": uuid4()}
    )
    assert historical_review.receipt_id == approved.receipt_id
    assert historical_review.replayed is True
    assert historical_activation.receipt_id == activated.receipt_id
    assert historical_activation.replayed is True
    with pytest.raises(RegistrationSetupRetryConflictError):
        approve_registration_profile_extension_field(
            **{
                **approval_values,
                "reason": "Changed retry intent.",
                "correlation_id": uuid4(),
            }
        )


def test_historical_replay_survives_later_policy_catalog_version() -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=field.id,
        expected_version=2,
        reason="Approve under a synthetic future policy catalog.",
    )
    with patch.object(
        setup_definition_commands,
        "POLICY_VERSION",
        "2099-01-01.1",
    ):
        approved = approve_registration_profile_extension_field(**values)
    audit = AuditEvent.objects.get(
        correlation_id=RegistrationSetupCommandReceipt.objects.get(
            pk=approved.receipt_id
        ).correlation_id
    )
    assert audit.safe_metadata["policy_version"] == "2099-01-01.1"

    replay = approve_registration_profile_extension_field(
        **{**values, "correlation_id": uuid4()}
    )
    assert replay.replayed is True
    assert replay.receipt_id == approved.receipt_id


def test_successor_edit_resets_review_and_activation_retires_exact_source() -> None:
    actor, edition, control, configuration, active = _active_world()
    revision = _value_revision(
        actor=actor,
        edition=edition,
        configuration=configuration,
        field=active,
    )
    value_state = (revision.id, revision.field_id, revision.value, revision.updated_at)
    successor_values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=active.id,
        expected_version=control.aggregate_version,
        reason="Start the next synthetic definition version.",
    )
    successor_result = start_registration_profile_extension_field_successor(
        **successor_values
    )
    successor = RegistrationProfileExtensionField.objects.get(
        pk=successor_result.target_id
    )
    assert successor.key == active.key
    assert successor.version == active.version + 1
    assert successor.supersedes_id == active.id
    assert successor.review_status == ProfileExtensionReviewStatus.PENDING
    assert successor.status == ProfileExtensionStatus.DRAFT

    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.id,
            expected_version=successor_result.resulting_version,
            reason="Approve the copied successor before editing it.",
        )
    )
    successor.refresh_from_db()
    updated = update_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        field_id=successor.id,
        key=successor.key,
        label="Updated diet note",
        help_text=successor.help_text,
        field_type=successor.field_type,
        options=list(successor.options),
        purpose=successor.purpose,
        classification=successor.classification,
        attendee_visible=successor.attendee_visible,
        writer_policy=successor.writer_policy,
        required=successor.required,
        expected_version=approved.resulting_version,
        reason="Clarify the successor definition.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    successor.refresh_from_db()
    assert successor.review_status == ProfileExtensionReviewStatus.PENDING
    assert successor.approved_by_id is None
    assert successor.approved_at is None
    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=successor.id,
                expected_version=updated.resulting_version,
                reason="Do not activate an invalidated review.",
            )
        )

    reapproved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.id,
            expected_version=updated.resulting_version,
            reason="Approve the edited successor definition.",
        )
    )
    activation_values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=successor.id,
        expected_version=reapproved.resulting_version,
        reason="Activate the reviewed successor definition.",
    )
    with CaptureQueriesContext(connection) as captured:
        activated = activate_registration_profile_extension_field(**activation_values)
    assert not any(
        "registration_registrationprofileextensionvaluerevision" in item["sql"]
        for item in captured.captured_queries
    )
    active.refresh_from_db()
    successor.refresh_from_db()
    assert active.status == ProfileExtensionStatus.RETIRED
    assert successor.status == ProfileExtensionStatus.ACTIVE
    activation_receipt = RegistrationSetupCommandReceipt.objects.get(
        pk=activated.receipt_id
    )
    assert set(activation_receipt.targets.values_list("change_kind", flat=True)) == {
        "activated",
        "retired",
    }
    revision.refresh_from_db()
    assert (revision.id, revision.field_id, revision.value, revision.updated_at) == (
        value_state
    )
    successor_replay = start_registration_profile_extension_field_successor(
        **{**successor_values, "correlation_id": uuid4()}
    )
    assert successor_replay.receipt_id == successor_result.receipt_id
    assert successor_replay.replayed is True
    retired = retire_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.id,
            expected_version=activated.resulting_version,
            reason="Retire the successor after preserving activation evidence.",
        )
    )
    activation_replay = activate_registration_profile_extension_field(
        **{**activation_values, "correlation_id": uuid4()}
    )
    assert activation_replay.receipt_id == activated.receipt_id
    assert activation_replay.replayed is True
    assert retired.resulting_version == activated.resulting_version + 1


def test_direct_retirement_is_the_single_preserving_retirement_semantics() -> None:
    actor, edition, control, configuration, active = _active_world()
    revision = _value_revision(
        actor=actor,
        edition=edition,
        configuration=configuration,
        field=active,
    )
    with CaptureQueriesContext(connection) as captured:
        retired = retire_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=active.id,
                expected_version=control.aggregate_version,
                reason="Retire the exact active definition without deleting history.",
            )
        )
    assert (
        retired.action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_RETIRED
    )
    assert not any(
        "registration_registrationprofileextensionvaluerevision" in item["sql"]
        for item in captured.captured_queries
    )
    active.refresh_from_db()
    revision.refresh_from_db()
    assert active.status == ProfileExtensionStatus.RETIRED
    assert revision.field_id == active.id
    assert revision.value == "synthetic gluten-free meal"


def test_active_retirement_refuses_to_strand_an_open_successor_draft() -> None:
    actor, edition, control, _configuration, active = _active_world()
    successor = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=control.aggregate_version,
            reason="Start a successor that must be resolved before direct retirement.",
        )
    )
    with pytest.raises(RegistrationSetupProfileFieldDependencyError):
        retire_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=active.id,
                expected_version=successor.resulting_version,
                reason="Do not strand the open successor draft.",
            )
        )
    active.refresh_from_db()
    successor_field = RegistrationProfileExtensionField.objects.get(
        pk=successor.target_id
    )
    control.refresh_from_db()
    assert active.status == ProfileExtensionStatus.ACTIVE
    assert successor_field.status == ProfileExtensionStatus.DRAFT
    assert control.aggregate_version == successor.resulting_version

    retired_draft = retire_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=successor.resulting_version,
            reason="Explicitly end the unused successor draft.",
        )
    )
    retired_active = retire_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=retired_draft.resulting_version,
            reason="Retire the active definition after resolving its successor.",
        )
    )
    active.refresh_from_db()
    successor_field.refresh_from_db()
    assert active.status == ProfileExtensionStatus.RETIRED
    assert successor_field.status == ProfileExtensionStatus.RETIRED
    assert retired_active.resulting_version == retired_draft.resulting_version + 1


def test_retired_abandoned_successor_does_not_exhaust_definition_lineage() -> None:
    actor, edition, control, _configuration, active = _active_world()
    first = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=control.aggregate_version,
            reason="Start the first synthetic correction draft.",
        )
    )
    retired_first = retire_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=first.target_id,
            expected_version=first.resulting_version,
            reason="Retire the abandoned first correction draft.",
        )
    )
    first_field = RegistrationProfileExtensionField.objects.get(pk=first.target_id)
    first_field.label = "Forbidden retired rewrite"
    with pytest.raises(ValidationError, match="Retired profile field"):
        first_field.save()
    with (
        pytest.raises(IntegrityError, match="retired profile extension"),
        transaction.atomic(),
    ):
        RegistrationProfileExtensionField.objects.filter(pk=first.target_id).update(
            label="Forbidden raw retired rewrite"
        )

    replacement = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=retired_first.resulting_version,
            reason="Start a later correction without rewriting abandoned history.",
        )
    )
    first_field.refresh_from_db()
    replacement_field = RegistrationProfileExtensionField.objects.get(
        pk=replacement.target_id
    )
    assert first_field.status == ProfileExtensionStatus.RETIRED
    assert first_field.version == 2
    assert replacement_field.status == ProfileExtensionStatus.DRAFT
    assert replacement_field.version == 3
    assert replacement_field.supersedes_id == active.id

    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=replacement_field.id,
            expected_version=replacement.resulting_version,
            reason="Approve the later synthetic correction.",
        )
    )
    activated = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=replacement_field.id,
            expected_version=approved.resulting_version,
            reason="Activate the later synthetic correction.",
        )
    )
    active.refresh_from_db()
    replacement_field.refresh_from_db()
    assert active.status == ProfileExtensionStatus.RETIRED
    assert replacement_field.status == ProfileExtensionStatus.ACTIVE
    assert activated.resulting_version == approved.resulting_version + 1


def test_profile_source_binding_is_immutable_after_initial_insert() -> None:
    _actor, edition, _control, _configuration, field = _draft_world()
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        status="published",
        published_at=timezone.now() - timedelta(minutes=1),
    )
    field.source_template = template
    with pytest.raises(ValidationError, match="source provenance is immutable"):
        field.save(update_fields=("source_template", "updated_at"))
    field.refresh_from_db()
    assert field.source_template_id is None

    with (
        pytest.raises(IntegrityError, match="source binding is immutable"),
        transaction.atomic(),
    ):
        RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
            source_template=template
        )
    field.refresh_from_db()
    assert field.source_template_id is None
    assert field.source_prior_edition_id is None


def test_historical_prior_edition_source_survives_later_date_correction() -> None:
    actor, edition, control, _configuration, _active = _active_world()
    prior = EventEditionFactory(
        organization=edition.organization,
        series=edition.series,
        starts_on=edition.starts_on - timedelta(days=30),
        ends_on=edition.starts_on - timedelta(days=28),
    )
    legacy = RegistrationProfileExtensionField.objects.create(
        organization=edition.organization,
        edition=edition,
        key="legacy-prior-note",
        version=1,
        label="Legacy prior note",
        help_text="Preserve a synthetic historical source binding.",
        field_type=QuestionFieldType.SHORT_TEXT,
        options=[],
        purpose="Verify stable historical source eligibility.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        required=False,
        position=1,
        source_prior_edition=prior,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        status=ProfileExtensionStatus.ACTIVE,
        created_by=actor,
        approved_by=actor,
        approved_at=timezone.now() - timedelta(minutes=1),
        created_in_setup_version=control.aggregate_version,
        last_changed_in_setup_version=control.aggregate_version,
    )
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.change_profile",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    changed = update_event_edition(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        expected_aggregate_version=edition.aggregate_version,
        details=EventEditionDetails(
            name=edition.name,
            time_zone=edition.time_zone,
            language_codes=tuple(edition.language_codes),
            currency_codes=tuple(edition.currency_codes),
            starts_on=prior.starts_on - timedelta(days=5),
            ends_on=prior.starts_on - timedelta(days=3),
        ),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert changed.changed_fields == ("starts_on", "ends_on")

    successor = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=legacy.id,
            expected_version=control.aggregate_version,
            reason="Correct a definition after an ordinary edition-date change.",
        )
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=successor.resulting_version,
            reason="Approve the date-drift regression successor.",
        )
    )
    activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=approved.resulting_version,
            reason="Activate without reinterpreting historical provenance.",
        )
    )
    legacy.refresh_from_db()
    successor_field = RegistrationProfileExtensionField.objects.get(
        pk=successor.target_id
    )
    assert legacy.status == ProfileExtensionStatus.RETIRED
    assert legacy.source_prior_edition_id == prior.id
    assert successor_field.status == ProfileExtensionStatus.ACTIVE


def test_missing_forged_stale_and_historical_review_evidence_is_exact() -> None:
    actor, edition, control, _configuration, field = _draft_world()
    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=2,
                reason="Reject activation without review.",
            )
        )
    RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
        review_status=ProfileExtensionReviewStatus.APPROVED,
        approved_by=actor,
        approved_at=timezone.now() - timedelta(seconds=1),
    )
    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=2,
                reason="Reject forged columns without a receipt.",
            )
        )
    RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
        review_status=ProfileExtensionReviewStatus.PENDING,
        approved_by=None,
        approved_at=None,
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Record valid current review evidence.",
        )
    )
    with pytest.raises(RegistrationSetupVersionConflictError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=approved.resulting_version + 1,
                reason="Reject a stale aggregate generation.",
            )
        )
    current_activator = AccountFactory()
    _grant(current_activator, edition)
    Account.objects.filter(pk=actor.id).update(is_active=False)
    activated = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=current_activator,
            edition=edition,
            field_id=field.id,
            expected_version=approved.resulting_version,
            reason="Honor durable review while authorizing the current activator.",
        )
    )
    control.refresh_from_db()
    field.refresh_from_db()
    assert control.aggregate_version == activated.resulting_version
    assert field.approved_by_id == actor.id
    assert field.status == ProfileExtensionStatus.ACTIVE


def test_malformed_forged_review_receipt_cannot_activate() -> None:
    actor, edition, control, _configuration, field = _draft_world()
    reviewed_at = timezone.now() - timedelta(seconds=1)
    RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
        review_status=ProfileExtensionReviewStatus.APPROVED,
        approved_by=actor,
        approved_at=reviewed_at,
        last_changed_in_setup_version=3,
    )
    RegistrationSetupControl.objects.filter(pk=control.id).update(aggregate_version=3)
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=control,
        organization=edition.organization,
        edition=edition,
        action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
        resulting_version=3,
        actor=actor,
        reason="Fabricate malformed synthetic review evidence.",
        correlation_id=uuid4(),
        source_channel="test",
        retry_key=uuid4(),
        request_digest="a" * 64,
    )
    RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
        target_id=uuid4(),
        change_kind=RegistrationCommandChangeKind.REVIEWED,
        target_schema_version=field.version,
        content_digest="b" * 64,
    )
    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=3,
                reason="Reject malformed forged review evidence.",
            )
        )


def _forge_exact_review_evidence(
    *,
    stage: str,
) -> tuple[
    Account,
    EventEdition,
    RegistrationProfileExtensionField,
    RegistrationSetupCommandReceipt,
    str,
]:
    actor, edition, control, _configuration, field = _draft_world()
    reviewed_at = timezone.now() - timedelta(seconds=1)
    reason = "Forge an exact-looking synthetic review receipt."
    retry_key = uuid4()
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
            "actor_id": str(actor.id),
            "organization_id": str(edition.organization_id),
            "series_id": str(edition.series_id),
            "edition_id": str(edition.id),
            "field_id": str(field.id),
            "source_template_id": None,
            "source_prior_edition_id": None,
            "after_field_id": None,
            "expected_version": 2,
            "reason": reason,
        }
    )
    RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
        review_status=ProfileExtensionReviewStatus.APPROVED,
        approved_by=actor,
        approved_at=reviewed_at,
        last_changed_in_setup_version=3,
    )
    RegistrationSetupControl.objects.filter(pk=control.id).update(aggregate_version=3)
    field.refresh_from_db()
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=control,
        organization=edition.organization,
        edition=edition,
        action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
        resulting_version=3,
        actor=actor,
        reason=reason,
        correlation_id=uuid4(),
        source_channel="test",
        retry_key=None if stage == "missing_retry" else retry_key,
        request_digest=(
            ""
            if stage == "missing_retry"
            else ("f" * 64 if stage == "bad_request" else request_digest)
        ),
    )
    RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
        target_id=field.id,
        change_kind=RegistrationCommandChangeKind.REVIEWED,
        target_schema_version=field.version,
        content_digest=target_content_digest(
            kind="profile_field",
            payload=profile_extension_payload(field),
        ),
    )
    if stage in {
        "missing_retry",
        "missing_event",
        "missing_outbox",
        "bad_outbox",
        "bad_request",
        "bad_audit",
    }:
        audit = AuditEvent.objects.create(
            schema_version=1,
            occurred_at=reviewed_at,
            principal_kind="account",
            principal_id=actor.id,
            organization_id=edition.organization_id,
            event_edition_id=edition.id,
            capability_code="registration.manage_configuration",
            operation="registration.setup.profile_field.changed",
            target_type="registration.profile_field",
            target_id=field.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="synthetic_authorized_review",
            obligations=[],
            changed_fields=(
                ["status"]
                if stage == "bad_audit"
                else ["review_status", "approved_by", "approved_at"]
            ),
            correlation_id=receipt.correlation_id,
            request_id=receipt.correlation_id,
            idempotency_key_hash=(
                canonical_digest({"retry_key": str(retry_key)})
                if stage != "missing_retry"
                else ""
            ),
            source_channel="test",
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "contract_version": "registration-definition-command-v1",
                "target_count": 1,
            },
            retention_class="registration-restricted",
        )
        if stage in {"missing_outbox", "bad_outbox", "bad_request", "bad_audit"}:
            event = DomainEvent.objects.create(
                event_name="registration.configuration.draft_changed.v1",
                schema_version=1,
                occurred_at=reviewed_at,
                organization_id=edition.organization_id,
                event_edition_id=edition.id,
                aggregate_type="registration.setup",
                aggregate_id=control.id,
                aggregate_version=3,
                payload={
                    "action": receipt.action,
                    "configuration_version": "profile-extensions",
                },
                correlation_id=receipt.correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-restricted",
            )
            if stage in {"bad_outbox", "bad_request", "bad_audit"}:
                OutboxMessage.objects.create(
                    event=event,
                    organization_id=edition.organization_id,
                    destination="internal",
                    workload_pool=(
                        "wrong-pool" if stage == "bad_outbox" else "default"
                    ),
                    available_at=reviewed_at,
                )
    return actor, edition, field, receipt, reason


@pytest.mark.parametrize(
    "stage",
    [
        "missing_retry",
        "bad_request",
        "missing_audit",
        "bad_audit",
        "missing_event",
        "missing_outbox",
        "bad_outbox",
    ],
)
def test_exact_looking_forged_review_requires_complete_command_evidence(
    stage: str,
) -> None:
    actor, edition, field, _receipt, _reason = _forge_exact_review_evidence(stage=stage)
    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=3,
                reason="Reject incomplete forged command evidence.",
            )
        )


def test_historical_replay_rejects_exact_forged_receipt_without_effect_chain() -> None:
    actor, edition, field, receipt, reason = _forge_exact_review_evidence(
        stage="missing_audit"
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        approve_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=2,
                reason=reason,
                retry_key=receipt.retry_key,
            )
        )


def test_unrelated_definition_change_does_not_invalidate_exact_field_review() -> None:
    actor, edition, _control, _configuration, first = _draft_world()
    second_result = create_registration_profile_extension_field(
        **_create_values(
            actor=actor,
            edition=edition,
            expected_version=2,
            key="arrival-note",
        )
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=first.id,
            expected_version=second_result.resulting_version,
            reason="Approve only the unchanged diet definition.",
        )
    )
    second = RegistrationProfileExtensionField.objects.get(pk=second_result.target_id)
    changed = update_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        field_id=second.id,
        key=second.key,
        label="Updated arrival note",
        help_text=second.help_text,
        field_type=second.field_type,
        options=list(second.options),
        purpose=second.purpose,
        classification=second.classification,
        attendee_visible=second.attendee_visible,
        writer_policy=second.writer_policy,
        required=second.required,
        expected_version=approved.resulting_version,
        reason="Change only the unrelated arrival definition.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    activated = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=first.id,
            expected_version=changed.resulting_version,
            reason="Activate the still-exact reviewed diet definition.",
        )
    )
    first.refresh_from_db()
    assert first.status == ProfileExtensionStatus.ACTIVE
    assert activated.resulting_version == changed.resulting_version + 1


def test_successor_lineage_does_not_depend_on_original_template_lifecycle() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    _grant(actor, edition)
    control, _configuration = _start(actor, edition)
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        status="published",
        published_at=timezone.now(),
    )
    field = _legacy_template_field(
        actor=actor,
        edition=edition,
        control=control,
        template=template,
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=control.aggregate_version,
            reason="Approve the template-sourced definition.",
        )
    )
    activated = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=approved.resulting_version,
            reason="Activate the template-sourced definition.",
        )
    )
    type(template).objects.filter(pk=template.id).update(
        status="retired",
        published_at=template.published_at,
    )
    successor = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=activated.resulting_version,
            reason="Use predecessor lineage after template retirement.",
        )
    )
    successor_field = RegistrationProfileExtensionField.objects.get(
        pk=successor.target_id
    )
    assert successor_field.supersedes_id == field.id
    assert successor_field.source_template_id is None
    assert successor_field.source_prior_edition_id is None
    successor_review = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=successor.resulting_version,
            reason="Approve the independent successor after source retirement.",
        )
    )
    successor_activation = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=successor_review.resulting_version,
            reason="Activate the independent successor after source retirement.",
        )
    )
    predecessor = RegistrationProfileExtensionField.objects.get(pk=field.id)
    successor_field.refresh_from_db()
    assert predecessor.status == ProfileExtensionStatus.RETIRED
    assert successor_field.status == ProfileExtensionStatus.ACTIVE
    control.refresh_from_db()
    assert control.aggregate_version == successor_activation.resulting_version


def test_retired_historical_template_does_not_block_direct_retirement() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    _grant(actor, edition)
    control, _configuration = _start(actor, edition)
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        status="published",
        published_at=timezone.now(),
    )
    field = _legacy_template_field(
        actor=actor,
        edition=edition,
        control=control,
        template=template,
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=control.aggregate_version,
            reason="Approve historical source-linked synthetic definition.",
        )
    )
    activated = activate_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=approved.resulting_version,
            reason="Activate historical source-linked synthetic definition.",
        )
    )
    type(template).objects.filter(pk=template.id).update(
        status="retired",
        published_at=template.published_at,
    )

    retired = retire_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=activated.resulting_version,
            reason="Retire historical source-linked synthetic definition.",
        )
    )

    active = RegistrationProfileExtensionField.objects.get(pk=field.id)
    active.refresh_from_db()
    control.refresh_from_db()
    assert active.status == ProfileExtensionStatus.RETIRED
    assert control.aggregate_version == retired.resulting_version


def test_canonical_creation_rejects_unpinned_source_containers_without_writes() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    _grant(actor, edition)
    control, _configuration = _start(actor, edition)
    template = RegistrationTemplateFactory(
        organization=edition.organization,
        series=edition.series,
        status="published",
        published_at=timezone.now(),
    )
    prior = EventEditionFactory(
        organization=edition.organization,
        series=edition.series,
        starts_on=edition.starts_on - timedelta(days=365),
        ends_on=edition.ends_on - timedelta(days=365),
    )
    foreign = EventEditionFactory(
        starts_on=edition.starts_on - timedelta(days=365),
        ends_on=edition.ends_on - timedelta(days=365),
    )
    before = {
        "fields": RegistrationProfileExtensionField.objects.count(),
        "receipts": RegistrationSetupCommandReceipt.objects.filter(
            setup=control
        ).count(),
        "audits": AuditEvent.objects.filter(event_edition_id=edition.id).count(),
        "events": DomainEvent.objects.filter(aggregate_id=control.id).count(),
        "outbox": OutboxMessage.objects.filter(event__aggregate_id=control.id).count(),
    }

    for source_field, source_id in (
        ("source_template_id", template.id),
        ("source_prior_edition_id", prior.id),
        ("source_prior_edition_id", foreign.id),
    ):
        values = _create_values(actor=actor, edition=edition, expected_version=1)
        values[source_field] = source_id
        with pytest.raises(ValidationError) as captured:
            create_registration_profile_extension_field(**values)
        errors = captured.value.error_dict[source_field]
        assert errors[0].code == "registration_setup_profile_field_source_unsupported"

    control.refresh_from_db()
    assert control.aggregate_version == 1
    assert {
        "fields": RegistrationProfileExtensionField.objects.count(),
        "receipts": RegistrationSetupCommandReceipt.objects.filter(
            setup=control
        ).count(),
        "audits": AuditEvent.objects.filter(event_edition_id=edition.id).count(),
        "events": DomainEvent.objects.filter(aggregate_id=control.id).count(),
        "outbox": OutboxMessage.objects.filter(event__aggregate_id=control.id).count(),
    } == before


def test_exact_scope_and_authorization_are_resolved_before_protected_input() -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    unauthorized = AccountFactory()
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        approve_registration_profile_extension_field(
            actor=unauthorized,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            field_id=object(),  # type: ignore[arg-type]
            expected_version=object(),  # type: ignore[arg-type]
            reason=object(),  # type: ignore[arg-type]
            retry_key=object(),  # type: ignore[arg-type]
            correlation_id=object(),  # type: ignore[arg-type]
        )
    foreign = EventEditionFactory()
    _grant(actor, foreign)
    foreign_control, _foreign_configuration = _start(actor, foreign)
    with pytest.raises(RegistrationSetupProfileFieldUnavailableError):
        approve_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=foreign,
                field_id=field.id,
                expected_version=foreign_control.aggregate_version,
                reason="Do not reveal a foreign definition.",
            )
        )
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        approve_registration_profile_extension_field(
            **{
                **_lifecycle_values(
                    actor=actor,
                    edition=edition,
                    field_id=field.id,
                    expected_version=2,
                    reason="Reject a mismatched route chain.",
                ),
                "organization_id": foreign.organization_id,
            }
        )


@pytest.mark.parametrize(
    "failure_target",
    [
        "maru.registration.setup_definition_commands.append_audit",
        "maru.effects.services.OutboxMessage.objects.create",
    ],
)
def test_activation_audit_or_outbox_failure_rolls_back_every_write(
    failure_target: str,
) -> None:
    actor, edition, control, _configuration, field = _draft_world()
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Approve before testing atomic failure.",
        )
    )
    before = {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }
    with (
        patch(failure_target, side_effect=RuntimeError("synthetic lifecycle failure")),
        pytest.raises(RuntimeError, match="synthetic lifecycle failure"),
    ):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=approved.resulting_version,
                reason="Roll back a failed profile activation.",
            )
        )
    field.refresh_from_db()
    control.refresh_from_db()
    assert field.status == ProfileExtensionStatus.DRAFT
    assert control.aggregate_version == approved.resulting_version
    assert {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before


def test_successor_activation_failure_restores_predecessor_and_reviewed_draft() -> None:
    actor, edition, control, _configuration, active = _active_world()
    successor = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=control.aggregate_version,
            reason="Start a successor for the atomic rollback test.",
        )
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor.target_id,
            expected_version=successor.resulting_version,
            reason="Approve the successor for the atomic rollback test.",
        )
    )
    before = {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }
    with (
        patch(
            "maru.effects.services.OutboxMessage.objects.create",
            side_effect=RuntimeError("synthetic successor outbox failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic successor outbox failure"),
    ):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=successor.target_id,
                expected_version=approved.resulting_version,
                reason="Roll back both sides of successor activation.",
            )
        )
    active.refresh_from_db()
    successor_field = RegistrationProfileExtensionField.objects.get(
        pk=successor.target_id
    )
    control.refresh_from_db()
    assert active.status == ProfileExtensionStatus.ACTIVE
    assert successor_field.status == ProfileExtensionStatus.DRAFT
    assert successor_field.review_status == ProfileExtensionReviewStatus.APPROVED
    assert control.aggregate_version == approved.resulting_version
    assert {
        "receipts": RegistrationSetupCommandReceipt.objects.count(),
        "audit": AuditEvent.objects.count(),
        "events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before


def test_model_and_database_enforce_active_and_reviewed_definition_immutability() -> (
    None
):
    actor, edition, control, _configuration, active = _active_world()
    active.label = "Forbidden active rewrite"
    with pytest.raises(ValidationError, match="immutable"):
        active.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.filter(pk=active.id).update(
            label="Forbidden raw active rewrite"
        )

    successor_result = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=control.aggregate_version,
            reason="Create a successor for the raw review-reset test.",
        )
    )
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=successor_result.target_id,
            expected_version=successor_result.resulting_version,
            reason="Approve the successor before a forbidden raw edit.",
        )
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.filter(
            pk=successor_result.target_id
        ).update(label="Raw edit without review reset")
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.filter(
            pk=successor_result.target_id
        ).update(approved_at=timezone.now() + timedelta(minutes=1))
    with (
        pytest.raises(IntegrityError, match="approval evidence is immutable"),
        transaction.atomic(),
    ):
        RegistrationProfileExtensionField.objects.filter(
            pk=successor_result.target_id
        ).update(approved_at=timezone.now() - timedelta(minutes=1))
    control.refresh_from_db()
    assert control.aggregate_version == approved.resulting_version


def test_activation_binds_approval_time_to_exact_audit_effect() -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Approve before exact timestamp binding probe.",
        )
    )
    field.refresh_from_db()
    assert field.approved_at is not None
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE registration_registrationprofileextensionfield "
            "DISABLE TRIGGER registration_profile_extension_field_guard"
        )
        try:
            cursor.execute(
                """
                UPDATE registration_registrationprofileextensionfield
                   SET approved_at = %s
                 WHERE id = %s
                """,
                [field.approved_at - timedelta(seconds=1), field.id],
            )
        finally:
            cursor.execute(
                "ALTER TABLE registration_registrationprofileextensionfield "
                "ENABLE TRIGGER registration_profile_extension_field_guard"
            )

    with pytest.raises(RegistrationSetupProfileFieldReviewRequiredError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=field.id,
                expected_version=approved.resulting_version,
                reason="Reject approval whose persisted time diverges from audit.",
            )
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("change_kind", "activated"),
        ("target_schema_version", 77),
        ("content_digest", "f" * 64),
    ],
)
def test_replay_rejects_action_schema_or_digest_target_tampering(
    column: str,
    value: object,
) -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    retry_key = uuid4()
    values = _lifecycle_values(
        actor=actor,
        edition=edition,
        field_id=field.id,
        expected_version=2,
        reason="Approve the exact synthetic tamper target.",
        retry_key=retry_key,
    )
    approved = approve_registration_profile_extension_field(**values)
    target = RegistrationSetupCommandTarget.objects.get(receipt_id=approved.receipt_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE registration_registrationsetupcommandtarget "
            "DISABLE TRIGGER registration_setup_target_immutable"
        )
        try:
            cursor.execute(
                f"UPDATE registration_registrationsetupcommandtarget "  # noqa: S608
                f"SET {column} = %s WHERE id = %s",
                [value, target.id],
            )
        finally:
            cursor.execute(
                "ALTER TABLE registration_registrationsetupcommandtarget "
                "ENABLE TRIGGER registration_setup_target_immutable"
            )

    with pytest.raises(RegistrationSetupStateConflictError):
        approve_registration_profile_extension_field(
            **{**values, "correlation_id": uuid4()}
        )


def test_receipt_and_target_rows_are_database_immutable() -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Create exact immutable setup evidence.",
        )
    )
    receipt = RegistrationSetupCommandReceipt.objects.get(pk=approved.receipt_id)
    target = receipt.targets.get()

    statements = (
        (
            "UPDATE registration_registrationsetupcommandreceipt "
            "SET reason = %s WHERE id = %s",
            ["Forbidden receipt rewrite.", receipt.id],
        ),
        (
            "DELETE FROM registration_registrationsetupcommandreceipt WHERE id = %s",
            [receipt.id],
        ),
        (
            "UPDATE registration_registrationsetupcommandtarget "
            "SET content_digest = %s WHERE id = %s",
            ["f" * 64, target.id],
        ),
        (
            "DELETE FROM registration_registrationsetupcommandtarget WHERE id = %s",
            [target.id],
        ),
    )
    for statement, parameters in statements:
        with (
            pytest.raises(IntegrityError, match="command evidence is append-only"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement, parameters)


def test_active_uniqueness_and_successor_lineage_are_exact() -> None:
    actor, edition, control, _configuration, active = _active_world()
    conflicting = RegistrationProfileExtensionField(
        organization=edition.organization,
        edition=edition,
        key=active.key,
        version=2,
        label="Conflicting active definition",
        field_type=QuestionFieldType.SHORT_TEXT,
        options=[],
        purpose="Conflict with the exact active definition.",
        classification=QuestionClassification.PERSONAL,
        attendee_visible=True,
        writer_policy=ProfileExtensionWriter.ATTENDEE,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        status=ProfileExtensionStatus.ACTIVE,
        created_by=actor,
        approved_by=actor,
        approved_at=timezone.now(),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.bulk_create([conflicting])
    invalid = RegistrationProfileExtensionField(
        organization=edition.organization,
        edition=edition,
        key=active.key,
        version=active.version + 2,
        supersedes=active,
        label=active.label,
        field_type=active.field_type,
        options=list(active.options),
        purpose=active.purpose,
        classification=active.classification,
        attendee_visible=active.attendee_visible,
        writer_policy=active.writer_policy,
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="next version"):
        invalid.full_clean()
    successor = start_registration_profile_extension_field_successor(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=active.id,
            expected_version=control.aggregate_version,
            reason="Create the sole exact successor.",
        )
    )
    second_open = RegistrationProfileExtensionField(
        organization=edition.organization,
        edition=edition,
        key=active.key,
        version=3,
        supersedes=active,
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
        created_by=actor,
    )
    with pytest.raises(ValidationError, match="only one open successor"):
        second_open.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistrationProfileExtensionField.objects.bulk_create([second_open])
    with pytest.raises(RegistrationSetupProfileFieldSuccessorConflictError):
        start_registration_profile_extension_field_successor(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=active.id,
                expected_version=successor.resulting_version,
                reason="Reject a second successor branch.",
            )
        )


def test_successor_activation_requires_canonical_origin_evidence() -> None:
    actor, edition, control, _configuration, active = _active_world()
    unevidenced = RegistrationProfileExtensionField(
        organization=edition.organization,
        edition=edition,
        key=active.key,
        version=2,
        supersedes=active,
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
        created_by=actor,
    )
    unevidenced.save(force_insert=True)
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=unevidenced.id,
            expected_version=control.aggregate_version,
            reason="Review cannot manufacture missing successor origin evidence.",
        )
    )
    with pytest.raises(RegistrationSetupProfileFieldSuccessorConflictError):
        activate_registration_profile_extension_field(
            **_lifecycle_values(
                actor=actor,
                edition=edition,
                field_id=unevidenced.id,
                expected_version=approved.resulting_version,
                reason="Reject an unevidenced successor at activation.",
            )
        )


def test_concurrent_activation_commits_one_exact_transition() -> None:
    actor, edition, _control, _configuration, field = _draft_world()
    approved = approve_registration_profile_extension_field(
        **_lifecycle_values(
            actor=actor,
            edition=edition,
            field_id=field.id,
            expected_version=2,
            reason="Approve before the concurrent activation test.",
        )
    )

    def run(retry_key: UUID):
        close_old_connections()
        try:
            try:
                return activate_registration_profile_extension_field(
                    **_lifecycle_values(
                        actor=actor,
                        edition=edition,
                        field_id=field.id,
                        expected_version=approved.resulting_version,
                        reason="Race one exact reviewed activation.",
                        retry_key=retry_key,
                    )
                )
            except (
                RegistrationSetupProfileFieldImmutableError,
                RegistrationSetupVersionConflictError,
            ) as error:
                return error
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (uuid4(), uuid4())))
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert (
        RegistrationProfileExtensionField.objects.filter(
            pk=field.id,
            status=ProfileExtensionStatus.ACTIVE,
        ).count()
        == 1
    )
    assert (
        RegistrationSetupCommandReceipt.objects.filter(
            setup_id=approved.setup_id,
            action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED,
        ).count()
        == 1
    )
