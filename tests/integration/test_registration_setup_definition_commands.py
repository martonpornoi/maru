from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import Never
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.models import ParticipationCapacity
from maru.registration.models import (
    AdmissionProduct,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationSetupCommandReceipt,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupVersionConflictError,
    start_registration_setup,
)
from maru.registration.setup_definition_commands import (
    RegistrationSetupProductDependencyError,
    RegistrationSetupProfileFieldImmutableError,
    RegistrationSetupQuestionDependencyError,
    create_admission_product,
    create_registration_profile_extension_field,
    create_registration_question,
    delete_admission_product,
    delete_registration_question,
    move_registration_profile_extension_field,
    move_registration_question,
    remove_minor_registration_policy,
    retire_registration_profile_extension_field,
    set_minor_registration_policy,
    update_registration_profile_extension_field,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
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
        name="Synthetic registration",
        opens_at=timezone.now() + timedelta(days=1),
        closes_at=timezone.now() + timedelta(days=30),
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        expected_version=0,
        reason="Start the governed synthetic setup.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return (
        RegistrationSetupControl.objects.get(pk=result.setup_id),
        RegistrationConfiguration.objects.get(pk=result.configuration_id),
    )


def _question_values(
    *,
    actor: Account,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    key: str,
    expected_version: int,
    after_question_id=None,
    condition_question_key: str = "",
    condition_value: str = "",
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "key": key,
        "label": key.replace("-", " ").title(),
        "help_text": "Synthetic help.",
        "field_type": (
            QuestionFieldType.BOOLEAN
            if key == "consent"
            else QuestionFieldType.SHORT_TEXT
        ),
        "required": False,
        "options": [],
        "purpose": "Exercise a governed test definition.",
        "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
        "classification": QuestionClassification.PERSONAL,
        "condition_question_key": condition_question_key,
        "condition_value": condition_value,
        "section_id": None,
        "after_question_id": after_question_id,
        "expected_version": expected_version,
        "reason": f"Create {key} for the synthetic test.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def test_question_commands_authorize_first_and_preserve_dependencies() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    unauthorized = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)

    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        create_registration_question(
            actor=unauthorized,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=object(),  # type: ignore[arg-type]
            key=object(),  # type: ignore[arg-type]
            label=object(),  # type: ignore[arg-type]
            help_text=object(),  # type: ignore[arg-type]
            field_type=object(),  # type: ignore[arg-type]
            required=object(),  # type: ignore[arg-type]
            options=object(),  # type: ignore[arg-type]
            purpose=object(),  # type: ignore[arg-type]
            visibility=object(),  # type: ignore[arg-type]
            classification=object(),  # type: ignore[arg-type]
            condition_question_key=object(),  # type: ignore[arg-type]
            condition_value=object(),  # type: ignore[arg-type]
            section_id=None,
            after_question_id=None,
            expected_version=object(),  # type: ignore[arg-type]
            reason=object(),  # type: ignore[arg-type]
            retry_key=object(),  # type: ignore[arg-type]
            correlation_id=object(),  # type: ignore[arg-type]
        )

    first = create_registration_question(
        **_question_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="consent",
            expected_version=1,
        )
    )
    second = create_registration_question(
        **_question_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="detail",
            expected_version=2,
            after_question_id=first.target_id,
            condition_question_key="consent",
            condition_value="true",
        )
    )
    with pytest.raises(ValidationError):
        move_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            question_id=second.target_id,
            after_question_id=None,
            expected_version=3,
            reason="Attempt an invalid forward dependency.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    with pytest.raises(RegistrationSetupQuestionDependencyError):
        delete_registration_question(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            question_id=first.target_id,
            expected_version=3,
            reason="Do not cascade into a conditional question.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    deleted = delete_registration_question(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        question_id=second.target_id,
        expected_version=3,
        reason="Remove the unreferenced synthetic question.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    control.refresh_from_db()
    assert deleted.resulting_version == 4
    assert control.aggregate_version == 4
    receipt = RegistrationSetupCommandReceipt.objects.get(pk=deleted.receipt_id)
    event = DomainEvent.objects.get(correlation_id=receipt.correlation_id)
    assert OutboxMessage.objects.get(event=event).status == OutboxMessage.Status.PENDING
    assert AuditEvent.objects.get(correlation_id=receipt.correlation_id).operation == (
        "registration.setup.question.changed"
    )


def test_question_conditions_match_activation_scalar_and_integer_rules() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)

    multiple_values = _question_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        key="interests",
        expected_version=1,
    )
    multiple_values.update(
        field_type=QuestionFieldType.MULTIPLE_CHOICE,
        options=["Panels", "Dance"],
    )
    multiple = create_registration_question(**multiple_values)
    with pytest.raises(ValidationError) as multiple_error:
        create_registration_question(
            **_question_values(
                actor=actor,
                edition=edition,
                configuration=configuration,
                key="panel-detail",
                expected_version=2,
                after_question_id=multiple.target_id,
                condition_question_key="interests",
                condition_value="Panels",
            )
        )
    assert multiple_error.value.error_dict["condition_value"][0].code == (
        "registration_setup_question_condition_value_invalid"
    )

    integer_values = _question_values(
        actor=actor,
        edition=edition,
        configuration=configuration,
        key="party-size",
        expected_version=2,
        after_question_id=multiple.target_id,
    )
    integer_values["field_type"] = QuestionFieldType.INTEGER
    integer = create_registration_question(**integer_values)
    for invalid_value in ("-0", "2147483648", "-2147483649"):
        with pytest.raises(ValidationError) as integer_error:
            create_registration_question(
                **_question_values(
                    actor=actor,
                    edition=edition,
                    configuration=configuration,
                    key="party-detail",
                    expected_version=3,
                    after_question_id=integer.target_id,
                    condition_question_key="party-size",
                    condition_value=invalid_value,
                )
            )
        assert integer_error.value.error_dict["condition_value"][0].code == (
            "registration_setup_question_condition_value_invalid"
        )

    accepted_minimum = create_registration_question(
        **_question_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="minimum-party-detail",
            expected_version=3,
            after_question_id=integer.target_id,
            condition_question_key="party-size",
            condition_value="-2147483648",
        )
    )
    accepted_maximum = create_registration_question(
        **_question_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="maximum-party-detail",
            expected_version=4,
            after_question_id=accepted_minimum.target_id,
            condition_question_key="party-size",
            condition_value="2147483647",
        )
    )
    control.refresh_from_db()
    assert accepted_minimum.resulting_version == 4
    assert accepted_maximum.resulting_version == 5
    assert control.aggregate_version == 5


def test_concurrent_question_writes_serialize_version_and_exact_replay() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)

    def create_in_thread(
        *,
        key: str,
        retry_key,
        barrier: Barrier,
    ):
        close_old_connections()
        try:
            thread_actor = Account.objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            values = _question_values(
                actor=thread_actor,
                edition=edition,
                configuration=configuration,
                key=key,
                expected_version=1,
            )
            values["retry_key"] = retry_key
            return create_registration_question(**values)
        finally:
            connections.close_all()

    distinct_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        distinct_futures = tuple(
            executor.submit(
                create_in_thread,
                key=key,
                retry_key=uuid4(),
                barrier=distinct_barrier,
            )
            for key in ("arrival-note", "diet-note")
        )
        successes = []
        conflicts = 0
        for future in distinct_futures:
            try:
                successes.append(future.result(timeout=20))
            except RegistrationSetupVersionConflictError:
                conflicts += 1
    control.refresh_from_db()
    assert len(successes) == 1
    assert conflicts == 1
    assert control.aggregate_version == 2
    assert configuration.questions.count() == 1

    replay_edition = EventEditionFactory()
    _grant(actor, replay_edition)
    replay_control, replay_configuration = _start(actor, replay_edition)
    replay_key = uuid4()
    replay_barrier = Barrier(2)

    def replay_in_thread():
        close_old_connections()
        try:
            thread_actor = Account.objects.get(pk=actor.pk)
            replay_barrier.wait(timeout=10)
            values = _question_values(
                actor=thread_actor,
                edition=replay_edition,
                configuration=replay_configuration,
                key="arrival-note",
                expected_version=1,
            )
            values["retry_key"] = replay_key
            return create_registration_question(**values)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        replay_results = tuple(
            future.result(timeout=20)
            for future in (
                executor.submit(replay_in_thread),
                executor.submit(replay_in_thread),
            )
        )
    replay_control.refresh_from_db()
    assert {result.replayed for result in replay_results} == {False, True}
    assert len({result.receipt_id for result in replay_results}) == 1
    assert replay_control.aggregate_version == 2
    assert replay_configuration.questions.count() == 1


def test_question_delete_refuses_an_immutable_submission_snapshot() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    _, configuration = _start(actor, edition)
    question = create_registration_question(
        **_question_values(
            actor=actor,
            edition=edition,
            configuration=configuration,
            key="arrival-note",
            expected_version=1,
        )
    )
    # Current database guards already make draft submissions impossible. This
    # seam proves the command still fails closed if legacy or restored evidence
    # ever presents that protected relationship.
    with patch(
        "maru.registration.setup_definition_commands."
        "RegistrationSubmission.objects.select_for_update"
    ) as submission_lock:
        submission_lock.return_value.filter.return_value.exists.return_value = True
        with pytest.raises(RegistrationSetupQuestionDependencyError):
            delete_registration_question(
                actor=actor,
                organization_id=edition.organization_id,
                series_id=edition.series_id,
                edition_id=edition.id,
                configuration_id=configuration.id,
                question_id=question.target_id,
                expected_version=2,
                reason="Prove immutable submissions protect their schema.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
            )


def test_product_commands_require_active_capacity_and_refuse_cascading_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    _, configuration = _start(actor, edition)
    participation = ParticipationFactory(
        edition=edition,
        organization=edition.organization,
    )
    ParticipationCapacityFactory(
        participation=participation,
        code="volunteer",
        status=ParticipationCapacity.Status.ACTIVE,
    )
    values = {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "code": "weekend",
        "name": "Weekend admission",
        "description": "Synthetic restricted admission.",
        "price_minor": 12_000,
        "capacity": 100,
        "entitlement_code": "weekend-admission",
        "entitlement_name": "Weekend admission",
        "sales_open_at": None,
        "sales_close_at": None,
        "required_capacity_codes": ["volunteer"],
        "eligibility_explanation": "Available to current volunteers.",
        "waitlist_enabled": True,
        "payment_window_minutes": 1_440,
        "after_product_id": None,
        "expected_version": 1,
        "reason": "Create a restricted synthetic product.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    result = create_admission_product(**values)
    replay = create_admission_product(**{**values, "correlation_id": uuid4()})
    assert replay.replayed is True
    assert replay.receipt_id == result.receipt_id
    with pytest.raises(RegistrationSetupRetryConflictError):
        create_admission_product(
            **{**values, "name": "Changed retry", "correlation_id": uuid4()}
        )

    product = configuration.products.get(pk=result.target_id)

    def protected_delete(_product: AdmissionProduct, *args, **kwargs) -> Never:
        del args, kwargs
        raise ProtectedError("synthetic protected reference", [_product])

    monkeypatch.setattr(AdmissionProduct, "delete", protected_delete)
    with pytest.raises(RegistrationSetupProductDependencyError):
        delete_admission_product(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            product_id=product.id,
            expected_version=2,
            reason="Prove referenced products never cascade.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert configuration.products.filter(pk=product.id).exists()


def test_minor_policy_supports_disabled_create_reviewed_update_and_remove() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, configuration = _start(actor, edition)
    create_retry_key = uuid4()
    create_values = {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "enabled": False,
        "minor_age_threshold": 19,
        "guardian_notice_version": "",
        "jurisdiction_code": "",
        "review_reference": "",
        "expected_version": 1,
        "reason": "Record that minors are not enabled yet.",
        "retry_key": create_retry_key,
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    created = set_minor_registration_policy(**create_values)
    created_replay = set_minor_registration_policy(
        **{**create_values, "correlation_id": uuid4()}
    )
    assert created_replay.replayed is True
    assert created_replay.receipt_id == created.receipt_id
    assert created_replay.target_id == created.target_id
    assert created.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
    updated = set_minor_registration_policy(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        configuration_id=configuration.id,
        enabled=True,
        minor_age_threshold=19,
        guardian_notice_version="notice-v1",
        jurisdiction_code="AT",
        review_reference="LEGAL-2026-01",
        expected_version=2,
        reason="Apply the jurisdiction-reviewed guardian policy.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    policy = configuration.minor_policy
    assert updated.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_UPDATED
    assert policy.reviewed_by_id == actor.id
    remove_values = {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "configuration_id": configuration.id,
        "expected_version": 3,
        "reason": "Remove the unreferenced synthetic policy.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    removed = remove_minor_registration_policy(**remove_values)
    removed_replay = remove_minor_registration_policy(
        **{**remove_values, "correlation_id": uuid4()}
    )
    historical_create_replay = set_minor_registration_policy(
        **{**create_values, "correlation_id": uuid4()}
    )
    control.refresh_from_db()
    assert removed.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_REMOVED
    assert removed_replay.replayed is True
    assert removed_replay.receipt_id == removed.receipt_id
    assert removed_replay.target_id == removed.target_id
    assert historical_create_replay.replayed is True
    assert historical_create_replay.receipt_id == created.receipt_id
    with pytest.raises(RegistrationSetupRetryConflictError):
        set_minor_registration_policy(
            **{
                **create_values,
                "minor_age_threshold": 20,
                "correlation_id": uuid4(),
            }
        )
    with pytest.raises(RegistrationSetupRetryConflictError):
        remove_minor_registration_policy(
            **{
                **remove_values,
                "reason": "Changed retry intent.",
                "correlation_id": uuid4(),
            }
        )
    assert control.aggregate_version == 4
    assert not configuration.__class__.objects.filter(
        pk=configuration.pk,
        minor_policy__isnull=False,
    ).exists()


def _profile_values(
    *, actor: Account, edition: EventEdition, key: str, expected_version: int
) -> dict[str, object]:
    return {
        "actor": actor,
        "organization_id": edition.organization_id,
        "series_id": edition.series_id,
        "edition_id": edition.id,
        "key": key,
        "label": key.replace("-", " ").title(),
        "help_text": "Synthetic current-profile field.",
        "field_type": QuestionFieldType.SHORT_TEXT,
        "options": [],
        "purpose": "Maintain a current attendee preference.",
        "classification": QuestionClassification.PERSONAL,
        "attendee_visible": True,
        "writer_policy": ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        "required": False,
        "source_template_id": None,
        "source_prior_edition_id": None,
        "after_field_id": None,
        "expected_version": expected_version,
        "reason": f"Create {key} as a governed profile definition.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def test_profile_field_definition_create_update_order_retire_and_immutability() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    control, _configuration = _start(actor, edition)
    first = create_registration_profile_extension_field(
        **_profile_values(
            actor=actor,
            edition=edition,
            key="diet-note",
            expected_version=1,
        )
    )
    second_values = _profile_values(
        actor=actor,
        edition=edition,
        key="arrival-note",
        expected_version=2,
    )
    second_values["after_field_id"] = first.target_id
    second = create_registration_profile_extension_field(**second_values)
    moved = move_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        field_id=second.target_id,
        after_field_id=None,
        expected_version=3,
        reason="Move the arrival note before the diet note.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert moved.action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_MOVED
    field = RegistrationProfileExtensionField.objects.get(pk=second.target_id)
    updated = update_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        field_id=field.id,
        key=field.key,
        label="Arrival details",
        help_text=field.help_text,
        field_type=field.field_type,
        options=list(field.options),
        purpose=field.purpose,
        classification=field.classification,
        attendee_visible=field.attendee_visible,
        writer_policy=field.writer_policy,
        required=field.required,
        expected_version=4,
        reason="Clarify the current-profile label.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert updated.resulting_version == 5
    retired = retire_registration_profile_extension_field(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        field_id=first.target_id,
        expected_version=5,
        reason="Retire the no-longer-needed profile definition.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert retired.resulting_version == 6
    assert (
        RegistrationProfileExtensionField.objects.get(pk=first.target_id).status
        == ProfileExtensionStatus.RETIRED
    )

    RegistrationProfileExtensionField.objects.filter(pk=field.id).update(
        status=ProfileExtensionStatus.ACTIVE,
        review_status=ProfileExtensionReviewStatus.APPROVED,
        approved_by=actor,
        approved_at=timezone.now() - timezone.timedelta(minutes=1),
    )
    field.refresh_from_db()
    with pytest.raises(RegistrationSetupProfileFieldImmutableError):
        update_registration_profile_extension_field(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            field_id=field.id,
            key=field.key,
            label="Must not change",
            help_text=field.help_text,
            field_type=field.field_type,
            options=list(field.options),
            purpose=field.purpose,
            classification=field.classification,
            attendee_visible=field.attendee_visible,
            writer_policy=field.writer_policy,
            required=field.required,
            expected_version=6,
            reason="Attempt to rewrite an active definition.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    control.refresh_from_db()
    assert control.aggregate_version == 6
