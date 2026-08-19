from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.communications.models import NotificationDelivery, NotificationMessage
from maru.effects.models import DomainEvent, OutboxMessage
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Entitlement,
    FinancialOperation,
    PaymentAttempt,
    PaymentException,
    PaymentProviderAccount,
    QuestionFieldType,
    Registration,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSubmission,
    RegistrationTimelineEntry,
)
from maru.registration.services import (
    check_in_registration,
    confirm_demo_payment,
    create_configuration_draft,
    submit_registration,
    validate_registration_answers,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _active_registration_world(
    *,
    product_capacity: int = 10,
    include_all_question_types: bool = False,
):
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(edition=edition)
    section = RegistrationSection.objects.create(
        configuration=configuration,
        key="convention-details",
        title="Convention details",
        description="Edition-specific attendee questions.",
        position=10,
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        section=section,
        key="badge-name",
        label="Badge name",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=10,
        purpose="Print the attendee badge.",
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        section=section,
        key="bringing-fursuit",
        label="Bringing a fursuit?",
        field_type=QuestionFieldType.BOOLEAN,
        required=True,
        position=20,
        purpose="Plan fursuit lounge capacity.",
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        section=section,
        key="fursuit-species",
        label="Fursuit species",
        field_type=QuestionFieldType.SHORT_TEXT,
        required=True,
        position=30,
        purpose="Prepare the optional fursuit badge.",
        condition_question_key="bringing-fursuit",
        condition_value="true",
    )
    if include_all_question_types:
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="arrival-notes",
            label="Arrival notes",
            field_type=QuestionFieldType.LONG_TEXT,
            position=40,
            purpose="Prepare arrival support.",
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="party-size",
            label="Party size",
            field_type=QuestionFieldType.INTEGER,
            position=50,
            purpose="Plan the arrival queue.",
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="badge-language",
            label="Badge language",
            field_type=QuestionFieldType.SINGLE_CHOICE,
            options=["en", "hu"],
            position=60,
            purpose="Print localized badge details.",
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="interests",
            label="Convention interests",
            field_type=QuestionFieldType.MULTIPLE_CHOICE,
            options=["art", "dance", "games"],
            position=70,
            purpose="Prepare aggregate programme planning.",
        )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="weekend",
        name="Weekend admission",
        price_minor=12_000,
        capacity=product_capacity,
        position=10,
        entitlement_code="event-admission",
        entitlement_name="Weekend event admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Synthetic workflow configuration reviewed."
    configuration.activated_at = timezone.now()
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )
    attendee = AccountFactory(display_name="Tavi River")
    ParticipationFactory(account=attendee, edition=edition)
    return edition, configuration, product, attendee


def _answers(*, bringing_fursuit: bool = True) -> dict[str, object]:
    answers: dict[str, object] = {
        "badge-name": "Tavi",
        "bringing-fursuit": bringing_fursuit,
    }
    if bringing_fursuit:
        answers["fursuit-species"] = "River otter"
    return answers


def test_attendee_registers_pays_and_keeps_exact_form_timeline() -> None:
    edition, configuration, product, attendee = _active_registration_world()
    submit_id = uuid4()

    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers=_answers(),
        correlation_id=submit_id,
    )

    assert registration.state == Registration.State.PAYMENT_PENDING
    submission = RegistrationSubmission.objects.get(registration=registration)
    assert submission.configuration_version == configuration.version
    assert submission.answers["fursuit-species"] == "River otter"
    assert len(submission.schema_snapshot) == 3
    assert registration.timeline.get().title == "Registration submitted"
    assert AuditEvent.objects.get(correlation_id=submit_id).target_id == registration.id
    assert DomainEvent.objects.get(correlation_id=submit_id).aggregate_version == 1

    payment_key = uuid4()
    payment_id = uuid4()
    paid = confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        registration_id=registration.id,
        idempotency_key=payment_key,
        correlation_id=payment_id,
    )
    repeated = confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        registration_id=registration.id,
        idempotency_key=payment_key,
        correlation_id=uuid4(),
    )

    assert paid.state == Registration.State.CONFIRMED
    assert repeated.id == paid.id
    assert PaymentAttempt.objects.filter(registration=registration).count() == 1
    assert Entitlement.objects.get(registration=registration).status == "active"
    assert list(
        registration.timeline.order_by("sequence").values_list("kind", flat=True)
    ) == ["registration_submitted", "payment_confirmed"]
    event = DomainEvent.objects.get(correlation_id=payment_id)
    assert event.event_name == "registration.payment.reconciled.v1"
    assert (
        OutboxMessage.objects.get(event=event, destination="internal").workload_pool
        == "payments"
    )
    assert OutboxMessage.objects.filter(
        event=event,
        destination="notifications",
        workload_pool="notifications",
    ).exists()


def test_conditional_answers_and_capacity_fail_closed() -> None:
    edition, _configuration, product, attendee = _active_registration_world(
        product_capacity=1
    )
    with pytest.raises(ValidationError, match="required"):
        submit_registration(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=attendee,
            product_id=product.id,
            answers={
                "badge-name": "Tavi",
                "bringing-fursuit": True,
            },
            correlation_id=uuid4(),
        )

    client = APIClient()
    client.force_authenticate(attendee)
    invalid = client.post(
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/registration/me",
        {
            "product_id": str(product.id),
            "answers": {
                "badge-name": "Tavi",
                "bringing-fursuit": True,
            },
        },
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_registration_submission"

    first = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers=_answers(bringing_fursuit=False),
        correlation_id=uuid4(),
    )
    other_attendee = AccountFactory()
    ParticipationFactory(account=other_attendee, edition=edition)
    waiting = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=other_attendee,
        product_id=product.id,
        answers={
            "badge-name": "Other",
            "bringing-fursuit": False,
        },
        correlation_id=uuid4(),
    )
    assert first.state == Registration.State.PAYMENT_PENDING
    assert waiting.state == Registration.State.WAITLISTED
    assert list(
        Registration.objects.filter(product=product).order_by("submitted_at", "id")
    ) == [first, waiting]


def test_registration_supports_all_configured_question_types() -> None:
    edition, configuration, product, attendee = _active_registration_world(
        include_all_question_types=True,
    )
    answers = {
        **_answers(),
        "arrival-notes": "Please use the quiet side of the arrival queue.",
        "party-size": 2,
        "badge-language": "hu",
        "interests": ["art", "games"],
    }

    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers=answers,
        correlation_id=uuid4(),
    )

    submission = RegistrationSubmission.objects.get(registration=registration)
    assert submission.answers == answers
    with pytest.raises(ValidationError, match="must be an object"):
        validate_registration_answers(
            questions=configuration.questions.all(),
            answers=["not", "an", "object"],
        )
    with pytest.raises(ValidationError, match="Unknown registration question"):
        validate_registration_answers(
            questions=configuration.questions.all(),
            answers={"unknown-question": "unexpected"},
        )
    for out_of_range in (-(2**31) - 1, 2**31):
        with pytest.raises(ValidationError, match="signed 32-bit"):
            validate_registration_answers(
                questions=configuration.questions.all(),
                answers={**answers, "party-size": out_of_range},
            )


def test_registration_configuration_can_copy_another_edition() -> None:
    source, source_configuration, _product, _attendee = _active_registration_world()
    target = EventEditionFactory(
        organization=source.organization,
        series=source.series,
    )
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=target.organization,
        edition=target,
        principal=actor,
        capability_code="registration.manage_configuration",
    )

    draft = create_configuration_draft(
        organization_id=target.organization_id,
        edition_id=target.id,
        actor=actor,
        name="Copied annual registration",
        reason="Reuse the last reviewed edition as a starting point.",
        source_edition_id=source.id,
        correlation_id=uuid4(),
    )

    assert draft.source_edition_id == source.id
    assert draft.review_required is True
    assert draft.capacity == source_configuration.capacity
    assert draft.currency == source_configuration.currency
    assert draft.minimum_age == source_configuration.minimum_age
    assert draft.sections.get().title == "Convention details"
    assert draft.questions.count() == source_configuration.questions.count()
    assert draft.questions.get(key="badge-name").section == draft.sections.get()
    assert draft.products.get().name == "Weekend admission"


def test_front_desk_view_is_minimized_audited_and_check_in_is_reasoned() -> None:
    edition, _configuration, product, attendee = _active_registration_world()
    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers=_answers(),
        correlation_id=uuid4(),
    )
    confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        registration_id=registration.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    desk_agent = AccountFactory(display_name="Front Desk Agent")
    for capability_code in (
        "registration.view_service_summary",
        "registration.check_in",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=desk_agent,
            capability_code=capability_code,
        )
    client = APIClient()
    client.force_authenticate(desk_agent)
    list_id = uuid4()

    response = client.get(
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/registrations",
        HTTP_X_REQUEST_ID=str(list_id),
    )

    assert response.status_code == 200
    payload = response.json()["results"][0]
    assert payload["display_name"] == attendee.display_name
    assert "email" not in payload
    assert "answers" not in payload
    assert AuditEvent.objects.get(correlation_id=list_id).outcome == "allow"

    check_in_id = uuid4()
    checked_in = check_in_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        actor=desk_agent,
        reason="Badge and attendee identity matched at Front Desk.",
        correlation_id=check_in_id,
    )
    assert checked_in.state == Registration.State.CHECKED_IN
    assert checked_in.check_in.reason.startswith("Badge and attendee")
    assert (
        RegistrationTimelineEntry.objects.get(
            registration=registration,
            kind="checked_in",
        ).title
        == "Checked in"
    )
    assert (
        DomainEvent.objects.get(correlation_id=check_in_id).event_name
        == "registration.checked_in.v1"
    )


def test_registration_api_walks_from_submission_through_front_desk() -> None:
    edition, _configuration, product, attendee = _active_registration_world()
    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    base_path = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"

    submission_response = attendee_client.post(
        f"{base_path}/registration/me",
        {
            "product_id": str(product.id),
            "answers": _answers(),
        },
        format="json",
    )

    assert submission_response.status_code == 201
    registration_id = submission_response.json()["id"]
    assert submission_response.json()["state"] == "payment_pending"

    payment_response = attendee_client.post(
        f"{base_path}/registration/me/{registration_id}/demo-payment",
        {"idempotency_key": str(uuid4())},
        format="json",
    )

    assert payment_response.status_code == 200
    assert payment_response.json()["state"] == "confirmed"
    assert payment_response.json()["entitlements"][0]["status"] == "active"

    desk_agent = AccountFactory(display_name="API Front Desk Agent")
    for capability_code in (
        "registration.view_service_summary",
        "registration.check_in",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=desk_agent,
            capability_code=capability_code,
        )
    desk_client = APIClient()
    desk_client.force_authenticate(desk_agent)

    detail_response = desk_client.get(
        f"{base_path}/registrations/{registration_id}",
    )
    check_in_response = desk_client.post(
        f"{base_path}/registrations/{registration_id}/check-in",
        {"reason": "Identity, badge name, and active entitlement confirmed."},
        format="json",
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["display_name"] == attendee.display_name
    assert "answers" not in detail_response.json()
    assert check_in_response.status_code == 200
    assert check_in_response.json()["state"] == "checked_in"
    assert check_in_response.json()["timeline"][-1]["kind"] == "checked_in"


def test_self_and_staff_endpoints_do_not_cross_tenant_or_edition() -> None:
    edition, _configuration, _product, attendee = _active_registration_world()
    other = EventEditionFactory()
    staff = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=staff,
        capability_code="registration.view_service_summary",
    )
    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    staff_client = APIClient()
    staff_client.force_authenticate(staff)

    own = attendee_client.get(
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/registration/me"
    )
    other_tenant_self = attendee_client.get(
        f"/api/v1/organizations/{other.organization_id}/"
        f"editions/{other.id}/registration/me"
    )
    other_tenant_staff = staff_client.get(
        f"/api/v1/organizations/{other.organization_id}/"
        f"editions/{other.id}/registrations"
    )

    assert own.status_code == 200
    assert own.json()["configuration"]["products"][0]["name"] == "Weekend admission"
    assert other_tenant_self.status_code == 404
    assert other_tenant_staff.status_code == 403


def test_action_projection_contains_review_and_front_desk_work() -> None:
    edition, configuration, product, attendee = _active_registration_world()
    registration = submit_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        product_id=product.id,
        answers=_answers(),
        correlation_id=uuid4(),
    )
    confirm_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        registration_id=registration.id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    draft = RegistrationConfiguration.objects.create(
        organization=edition.organization,
        edition=edition,
        name="Next registration version",
        version=2,
        opens_at=timezone.now() + timedelta(days=10),
        closes_at=timezone.now() + timedelta(days=40),
        capacity=100,
        currency="EUR",
        created_by_id=uuid4(),
    )
    operator = AccountFactory()
    for capability_code in (
        "registration.manage_configuration",
        "registration.view_service_summary",
        "registration.manage_exceptions",
        "registration.manage_finance",
        "registration.moderate_public_profile",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=operator,
            capability_code=capability_code,
        )
    attendee.is_active = False
    attendee.save(update_fields=("is_active",))
    provider = PaymentProviderAccount.objects.create(
        organization=edition.organization,
        code="action-provider",
        display_name="Action Provider",
        adapter="synthetic_test",
        api_base_url="https://payments.example",
        credential_env_var="ACTION_PROVIDER_KEY",
        webhook_secret_env_var="ACTION_PROVIDER_WEBHOOK",
        enabled=False,
    )
    PaymentException.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        provider_account=provider,
        kind=PaymentException.Kind.OUT_OF_ORDER,
        safe_summary="Synthetic provider outcome needs review.",
        opened_at=timezone.now(),
    )
    FinancialOperation.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind=FinancialOperation.Kind.CANCEL,
        amount_minor=0,
        currency=registration.currency_snapshot,
        requested_by=operator,
        requested_at=timezone.now(),
        request_reason="Synthetic cancellation needs independent review.",
    )
    message = NotificationMessage.objects.create(
        account=attendee,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        domain_event_id=uuid4(),
        message_type="synthetic_failure",
        purpose=NotificationMessage.Purpose.OPERATIONAL,
        locale="en",
        subject="Synthetic delivery failure",
        body="Use the platform inbox.",
        rendered_at=timezone.now(),
    )
    NotificationDelivery.objects.create(
        message=message,
        channel=NotificationDelivery.Channel.EMAIL,
        status=NotificationDelivery.Status.PERMANENT_FAILED,
        attempt_count=1,
        safe_error_code="email_recipient_rejected",
        last_attempt_at=timezone.now(),
    )
    client = APIClient()
    client.force_authenticate(operator)

    response = client.get(
        f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}/actions"
    )

    assert response.status_code == 200
    keys = {item["key"] for item in response.json()}
    assert f"registration-config-review:{draft.id}" in keys
    assert f"registration-check-in:{registration.id}" in keys
    assert f"registration-inactive-confirmed:{registration.id}" in keys
    assert "registration-delivery-failures" in keys
    assert "registration-provider-exceptions" in keys
    assert "registration-financial-operations" in keys
    assert all(item["owner_label"] for item in response.json())
    configuration.refresh_from_db()
    assert configuration.status == ConfigurationStatus.ACTIVE
