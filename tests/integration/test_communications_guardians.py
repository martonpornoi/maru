import smtplib
from datetime import date, timedelta
from typing import Never
from uuid import uuid4

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
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
from maru.effects.models import DomainEvent, OutboxMessage
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
    Entitlement,
    GuardianConsent,
    MinorRegistrationPolicy,
    Registration,
    RegistrationQuestion,
    RegistrationTimelineEntry,
)
from maru.registration.queries import notification_context
from maru.registration.services import AttendeeProfileInput, submit_public_registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
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


def test_retained_guardian_token_cannot_revive_unadopted_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return generic denials without mutating retained guardian evidence."""
    now = timezone.now()
    edition = EventEditionFactory(
        name="Hidden Guardian Edition",
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    configuration = RegistrationConfigurationFactory(edition=edition)
    reviewer = AccountFactory()
    policy = MinorRegistrationPolicy.objects.create(
        configuration=configuration,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="synthetic-reviewed",
        review_reference="LEGAL-RETAINED-1",
        reviewed_by=reviewer,
        reviewed_at=now,
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="retained-minor-admission",
        name="Hidden minor admission",
        price_minor=0,
        capacity=20,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    _activate(configuration, now)
    attendee = AccountFactory(display_name="Hidden minor attendee")
    participation = ParticipationFactory(account=attendee, edition=edition)
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=participation,
        account=attendee,
        configuration=configuration,
        product=product,
        reference="HIDDEN-GUARDIAN-REG",
        state=Registration.State.GUARDIAN_PENDING,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=now,
    )
    raw_token = "retained-guardian-consent-token"
    token_digest = "a" * 64
    monkeypatch.setattr(
        "maru.registration.guardians._token_digest",
        lambda _raw_token: token_digest,
    )
    consent = GuardianConsent.objects.create(
        registration=registration,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        policy=policy,
        guardian_name="Hidden Guardian Person",
        guardian_email="hidden.guardian@example.invalid",
        relationship="Parent",
        notice_version=policy.guardian_notice_version,
        token_digest=token_digest,
        requested_at=now,
        expires_at=now + timedelta(days=1),
    )
    before = {
        "timeline": RegistrationTimelineEntry.objects.filter(
            registration=registration
        ).count(),
        "entitlements": Entitlement.objects.filter(registration=registration).count(),
        "events": DomainEvent.objects.filter(aggregate_id=registration.id).count(),
        "outbox": OutboxMessage.objects.filter(
            event__aggregate_id=registration.id
        ).count(),
    }
    payload = {
        "token": raw_token,
        "guardian_name": "Retained Guardian",
    }

    html_response = Client().post(reverse("guardian-consent"), payload)
    api_response = APIClient().post(
        reverse("api-public-guardian-consent"),
        payload,
        format="json",
    )

    assert html_response.status_code == 200
    assert b"invalid or has expired" in html_response.content
    assert api_response.status_code == 400
    assert api_response.data["detail"] == "Guardian consent could not be accepted."
    rendered = html_response.content + bytes(str(api_response.data), "utf-8")
    assert b"Hidden Guardian Edition" not in rendered
    assert b"Hidden Guardian Person" not in rendered
    assert b"HIDDEN-GUARDIAN-REG" not in rendered
    registration.refresh_from_db()
    consent.refresh_from_db()
    assert registration.state == Registration.State.GUARDIAN_PENDING
    assert registration.aggregate_version == 1
    assert consent.status == GuardianConsent.Status.PENDING
    assert consent.decided_at is None
    assert consent.guardian_name_at_decision == ""
    assert {
        "timeline": RegistrationTimelineEntry.objects.filter(
            registration=registration
        ).count(),
        "entitlements": Entitlement.objects.filter(registration=registration).count(),
        "events": DomainEvent.objects.filter(aggregate_id=registration.id).count(),
        "outbox": OutboxMessage.objects.filter(
            event__aggregate_id=registration.id
        ).count(),
    } == before


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


def test_workforce_restriction_skips_communications_and_hides_retained_message() -> (
    None
):
    """Keep Workforce-only restriction effects out of Communications."""
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    operator = AccountFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="identity.manage_restrictions",
    )

    restriction = issue_account_restriction(
        actor=operator,
        account=account,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind=AccountRestriction.Kind.COMMUNICATION,
        reason_code="support-review",
        attendee_message="Contact support for an access review.",
        internal_reference="PRIVATE-WORKFORCE-CASE",
        effective_at=timezone.now(),
        expires_at=None,
        notify_account=True,
        correlation_id=uuid4(),
    )
    event = DomainEvent.objects.get(
        aggregate_type="identity.account_restriction",
        aggregate_id=restriction.id,
    )

    assert OutboxMessage.objects.filter(event=event, destination="internal").exists()
    assert not OutboxMessage.objects.filter(
        event=event,
        destination="notifications",
    ).exists()
    with pytest.raises(PermanentEffectError) as denied:
        deliver_restriction_notification(event, _effect_context(event))
    assert denied.value.error_code == "effect_profile_not_allowed"
    assert not NotificationMessage.objects.filter(domain_event_id=event.id).exists()

    retained = NotificationMessage.objects.create(
        account=account,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        domain_event_id=event.id,
        message_type="account_restriction_applied",
        purpose=NotificationMessage.Purpose.OPERATIONAL,
        locale="en",
        subject="Hidden workforce-only message",
        body="This retained Communications body must remain hidden.",
        action_path="/admin/workspace/?view=security",
        rendered_at=timezone.now(),
    )
    client = APIClient()
    client.force_authenticate(account)

    inbox = client.get("/api/v1/me/notifications")
    marked = client.post(f"/api/v1/me/notifications/{retained.id}/read")

    assert inbox.status_code == 200
    assert inbox.data == []
    assert marked.status_code == 404
    retained.refresh_from_db()
    assert retained.read_at is None


def test_organization_restriction_notification_remains_in_the_self_inbox() -> None:
    """Preserve the explicit non-edition restriction-notification route."""
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    operator = AccountFactory(is_staff=True, is_superuser=True)
    account = AccountFactory()

    restriction = issue_account_restriction(
        actor=operator,
        account=account,
        organization_id=edition.organization_id,
        edition_id=None,
        kind=AccountRestriction.Kind.COMMUNICATION,
        reason_code="organization-support-review",
        attendee_message="Contact the organizer about this account change.",
        internal_reference="PRIVATE-ORGANIZATION-CASE",
        effective_at=timezone.now(),
        expires_at=None,
        notify_account=True,
        correlation_id=uuid4(),
    )
    event = DomainEvent.objects.get(
        aggregate_type="identity.account_restriction",
        aggregate_id=restriction.id,
    )
    assert event.event_edition_id is None
    assert OutboxMessage.objects.filter(
        event=event,
        destination="notifications",
    ).exists()
    deliver_restriction_notification(event, _effect_context(event))
    message = NotificationMessage.objects.get(domain_event_id=event.id)

    client = APIClient()
    client.force_authenticate(account)
    inbox = client.get("/api/v1/me/notifications")
    marked = client.post(f"/api/v1/me/notifications/{message.id}/read")

    assert inbox.status_code == 200
    assert [item["id"] for item in inbox.data] == [str(message.id)]
    assert marked.status_code == 200
    assert marked.data["read_at"] is not None
