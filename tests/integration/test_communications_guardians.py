import smtplib
from datetime import date, timedelta
from typing import Never
from uuid import uuid4

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)
from maru.communications.services import (
    deliver_registration_notification,
    deliver_restriction_notification,
    render_registration_notification,
)
from maru.effects.models import DomainEvent
from maru.effects.worker import (
    EffectContext,
    PermanentEffectError,
    TransientEffectError,
)
from maru.identity.models import AccountRestriction
from maru.identity.services import issue_account_restriction
from maru.registration.guardians import accept_guardian_consent
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    GuardianConsent,
    MinorRegistrationPolicy,
    Registration,
    RegistrationQuestion,
)
from maru.registration.queries import notification_context
from maru.registration.services import AttendeeProfileInput, submit_public_registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _registration_world(*, price_minor: int = 10_000):
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Badge name",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print the attendee credential.",
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="admission",
        name="Admission",
        price_minor=price_minor,
        capacity=20,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    return edition, configuration, product, now


def _profile(*, birth_date: date, guardian: bool = False) -> AttendeeProfileInput:
    return AttendeeProfileInput(
        real_name="Synthetic Attendee",
        date_of_birth=birth_date,
        address_line_1="1 Test Street",
        address_line_2="",
        locality="Test City",
        postal_code="1000",
        region="Test Region",
        country_code="HU",
        emergency_contact_name="Emergency Contact",
        emergency_contact_phone="+361234567",
        phone_number="+361234568",
        telegram_handle="synthetic_user",
        pronoun_code="they_them",
        other_pronouns="",
        bio="Synthetic profile.",
        spoken_language_codes=("en", "hu"),
        profile_photo=None,
        reuse_profile_photo_id=None,
        keep_profile_photo=False,
        brings_fursuits=False,
        fursuits=(),
        directory_visible=False,
        guardian_name="Guardian Person" if guardian else "",
        guardian_email="guardian@example.invalid" if guardian else "",
        guardian_relationship="Parent" if guardian else "",
        guardian_notice_version="guardian-v1" if guardian else "",
    )


def _activate(configuration, now) -> None:
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed."
    configuration.activated_at = now
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )


def _effect_context(event: DomainEvent) -> EffectContext:
    return EffectContext(
        event_id=event.id,
        idempotency_key=f"notification:{event.id}",
        organization_id=event.organization_id,
        correlation_id=event.correlation_id,
        attempt_number=1,
        deadline=timezone.now() + timedelta(minutes=1),
    )


def test_registration_notification_inbox_email_preferences_and_self_api() -> None:
    edition, configuration, product, now = _registration_world()
    _activate(configuration, now)
    attendee = AccountFactory()
    result = submit_public_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product.id,
        answers={"badge-name": "Synthetic"},
        profile_input=_profile(birth_date=date(1990, 1, 1)),
        correlation_id=uuid4(),
        account=attendee,
    )
    event = DomainEvent.objects.get(
        aggregate_id=result.registration.id,
        event_name="registration.submitted.v1",
    )
    deliver_registration_notification(event, _effect_context(event))
    message = NotificationMessage.objects.get(domain_event_id=event.id)
    delivery = NotificationDelivery.objects.get(message=message)
    assert delivery.status == NotificationDelivery.Status.SUCCEEDED
    assert len(mail.outbox) == 1
    assert "Payment deadline" in message.body

    deliver_registration_notification(event, _effect_context(event))
    delivery.refresh_from_db()
    assert delivery.attempt_count == 1
    context = notification_context(
        registration_id=result.registration.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert context is not None
    rendered = render_registration_notification(
        event_name="registration.submitted.v1",
        context=context,
    )
    assert rendered.action_path.endswith("/profile/")
    with pytest.raises(PermanentEffectError):
        render_registration_notification(event_name="unknown", context=context)

    client = APIClient()
    client.force_authenticate(attendee)
    inbox = client.get("/api/v1/me/notifications")
    assert inbox.status_code == 200
    marked = client.post(f"/api/v1/me/notifications/{message.id}/read")
    assert marked.status_code == 200
    assert marked.data["read_at"]
    preference = client.put(
        f"/api/v1/me/notification-preferences/{edition.organization_id}",
        {
            "operational_email_enabled": False,
            "marketing_email_consent": True,
            "marketing_consent_version": "marketing-email-v1",
        },
        format="json",
    )
    assert preference.status_code == 200
    assert NotificationPreference.objects.get(account=attendee).marketing_consented_at
    retrieved = client.get(
        f"/api/v1/me/notification-preferences/{edition.organization_id}"
    )
    assert retrieved.status_code == 200
    assert retrieved.data["marketing_email_consent"] is True
    invalid_consent = client.put(
        f"/api/v1/me/notification-preferences/{edition.organization_id}",
        {
            "operational_email_enabled": True,
            "marketing_email_consent": True,
            "marketing_consent_version": "outdated-version",
        },
        format="json",
    )
    assert invalid_consent.status_code == 400
    assert client.post(f"/api/v1/me/notifications/{uuid4()}/read").status_code == 404


def test_notification_suppression_transient_and_permanent_failures(
    monkeypatch,
) -> None:
    edition, configuration, product, now = _registration_world()
    _activate(configuration, now)
    attendee = AccountFactory()
    result = submit_public_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product.id,
        answers={"badge-name": "Synthetic"},
        profile_input=_profile(birth_date=date(1990, 1, 1)),
        correlation_id=uuid4(),
        account=attendee,
    )
    event = DomainEvent.objects.get(
        aggregate_id=result.registration.id,
        event_name="registration.submitted.v1",
    )
    NotificationPreference.objects.create(
        account=attendee,
        organization=edition.organization,
        operational_email_enabled=False,
    )
    deliver_registration_notification(event, _effect_context(event))
    assert (
        NotificationDelivery.objects.get(message__domain_event_id=event.id).status
        == NotificationDelivery.Status.SUPPRESSED
    )

    second_edition, second_configuration, second_product, second_now = (
        _registration_world()
    )
    _activate(second_configuration, second_now)
    second_attendee = AccountFactory()
    second = submit_public_registration(
        organization_id=second_edition.organization_id,
        edition_id=second_edition.id,
        product_id=second_product.id,
        answers={"badge-name": "Second"},
        profile_input=_profile(birth_date=date(1990, 1, 1)),
        correlation_id=uuid4(),
        account=second_attendee,
    )
    second_event = DomainEvent.objects.get(
        aggregate_id=second.registration.id,
        event_name="registration.submitted.v1",
    )

    def transient(*args, **kwargs) -> Never:
        raise OSError("provider unavailable")

    monkeypatch.setattr("maru.communications.services.send_mail", transient)
    with pytest.raises(TransientEffectError):
        deliver_registration_notification(second_event, _effect_context(second_event))

    def permanent(*args, **kwargs) -> Never:
        raise smtplib.SMTPRecipientsRefused({})

    monkeypatch.setattr("maru.communications.services.send_mail", permanent)
    with pytest.raises(PermanentEffectError):
        deliver_registration_notification(second_event, _effect_context(second_event))
    assert (
        NotificationDelivery.objects.get(
            message__domain_event_id=second_event.id
        ).status
        == NotificationDelivery.Status.PERMANENT_FAILED
    )
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=second_edition.organization,
        edition=second_edition,
        principal=operator,
        capability_code="registration.view_service_summary",
    )
    staff = APIClient()
    staff.force_authenticate(operator)
    failures = staff.get(
        f"/api/v1/organizations/{second_edition.organization_id}/editions/"
        f"{second_edition.id}/communication-delivery-failures"
    )
    assert failures.status_code == 200
    assert failures.data[0]["safe_error_code"] == "email_recipient_rejected"


def test_minor_registration_waits_for_single_use_guardian_consent() -> None:
    edition, configuration, product, now = _registration_world(price_minor=0)
    configuration.minimum_age = 13
    configuration.save(update_fields=("minimum_age", "updated_at"))
    reviewer = AccountFactory()
    policy = MinorRegistrationPolicy.objects.create(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="synthetic-reviewed",
        review_reference="LEGAL-TEST-1",
        reviewed_by=reviewer,
        reviewed_at=now,
    )
    _activate(configuration, now)
    attendee = AccountFactory()
    result = submit_public_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product.id,
        answers={"badge-name": "Young Attendee"},
        profile_input=_profile(birth_date=date(2014, 1, 1), guardian=True),
        correlation_id=uuid4(),
        account=attendee,
    )
    assert result.registration.state == Registration.State.GUARDIAN_PENDING
    assert result.guardian_consent_required
    assert result.guardian_test_token
    consent = GuardianConsent.objects.get(registration=result.registration)
    assert consent.policy == policy
    accepted = accept_guardian_consent(
        raw_token=result.guardian_test_token or "",
        guardian_name="Guardian Person",
    )
    assert accepted.state == Registration.State.CONFIRMED
    assert accepted.entitlements.filter(status="active").exists()
    with pytest.raises(ValidationError, match="invalid or has expired"):
        accept_guardian_consent(
            raw_token=result.guardian_test_token or "",
            guardian_name="Guardian Person",
        )


def test_restriction_notice_uses_durable_inbox_and_safe_attendee_text() -> None:
    edition = EventEditionFactory()
    operator = AccountFactory()
    attendee = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="identity.manage_restrictions",
    )
    restriction = issue_account_restriction(
        actor=operator,
        account=attendee,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind=AccountRestriction.Kind.REGISTRATION,
        reason_code="support-review",
        attendee_message="Registration is paused. Please contact support.",
        internal_reference="PRIVATE-CASE-REFERENCE",
        effective_at=timezone.now(),
        expires_at=None,
        notify_account=True,
        correlation_id=uuid4(),
    )
    event = DomainEvent.objects.get(
        aggregate_type="identity.account_restriction",
        aggregate_id=restriction.id,
    )
    deliver_restriction_notification(event, _effect_context(event))
    message = NotificationMessage.objects.get(domain_event_id=event.id)
    assert "Registration is paused" in message.body
    assert "PRIVATE-CASE-REFERENCE" not in message.body
    assert NotificationDelivery.objects.get(message=message).status == (
        NotificationDelivery.Status.SUCCEEDED
    )
