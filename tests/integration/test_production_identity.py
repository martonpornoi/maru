from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import (
    AccountRestriction,
    AccountSecurityEvent,
    IdentityAbuseBucket,
    IdentityChallenge,
    RestrictionAppeal,
)
from maru.identity.services import (
    active_restrictions,
    apply_due_account_restrictions,
    bootstrap_account,
    consume_identity_challenge,
    enforce_abuse_limit,
    enforce_not_restricted,
    inventory_session,
    issue_account_restriction,
    request_account_recovery,
    revoke_account_restriction,
    revoke_all_sessions,
    session_key_digest,
)
from maru.participation.models import Participation
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    Registration,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

PASSWORD = "A-strong-registration-password-482!"


def test_public_identity_bootstrap_verify_sign_in_step_up_and_recovery() -> None:
    client = APIClient()
    assert client.get("/api/v1/public/csrf").status_code == 200
    bootstrap = client.post(
        "/api/v1/public/accounts",
        {
            "email": "new-attendee@example.invalid",
            "display_name": "New Attendee",
            "password": PASSWORD,
        },
        format="json",
        REMOTE_ADDR="192.0.2.10",
        HTTP_USER_AGENT="Synthetic browser",
    )
    assert bootstrap.status_code == 202
    assert bootstrap.data["accepted"] is True
    assert len(mail.outbox) == 1
    token = bootstrap.data["test_token"]

    verified = client.post(
        "/api/v1/public/accounts/verify-email",
        {"token": token},
        format="json",
    )
    assert verified.status_code == 200
    assert verified.data["verified"] is True
    with pytest.raises(ValidationError, match="invalid or has expired"):
        consume_identity_challenge(
            raw_token=token,
            purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
        )
    invalid_verification = client.post(
        "/api/v1/public/accounts/verify-email",
        {"token": token},
        format="json",
    )
    assert invalid_verification.status_code == 400

    invalid_sign_in = client.post(
        "/api/v1/public/sessions",
        {"email": "new-attendee@example.invalid", "password": "wrong-password"},
        format="json",
    )
    assert invalid_sign_in.status_code == 400
    signed_in = client.post(
        "/api/v1/public/sessions",
        {"email": "new-attendee@example.invalid", "password": PASSWORD},
        format="json",
        HTTP_USER_AGENT="Synthetic browser",
    )
    assert signed_in.status_code == 201
    assert signed_in.data["email_verified"] is True
    sessions = client.get("/api/v1/me/sessions")
    assert sessions.status_code == 200
    assert sessions.data[0]["current"] is True
    security_history = client.get("/api/v1/me/security-history")
    assert security_history.status_code == 200
    assert security_history.data

    step_up = client.post(
        "/api/v1/me/step-up",
        {"password": PASSWORD},
        format="json",
    )
    assert step_up.status_code == 200
    assert step_up.data["step_up_verified_at"]
    bad_step_up = client.post(
        "/api/v1/me/step-up",
        {"password": "wrong-password"},
        format="json",
    )
    assert bad_step_up.status_code == 400
    missing_session = client.post(f"/api/v1/me/sessions/{uuid4()}/revoke")
    assert missing_session.status_code == 404
    revoked_session = client.post(
        f"/api/v1/me/sessions/{sessions.data[0]['id']}/revoke"
    )
    assert revoked_session.status_code == 200
    assert revoked_session.data["revoked"] is True

    recovery = client.post(
        "/api/v1/public/accounts/recovery",
        {"email": "new-attendee@example.invalid"},
        format="json",
        REMOTE_ADDR="192.0.2.11",
    )
    recovery_token = recovery.data["test_token"]
    hidden_recovery = client.post(
        "/api/v1/public/accounts/recovery",
        {"email": "missing-account@example.invalid"},
        format="json",
        REMOTE_ADDR="192.0.2.12",
    )
    assert hidden_recovery.status_code == 202
    assert "test_token" not in hidden_recovery.data
    invalid_recovery = client.post(
        "/api/v1/public/accounts/recovery/complete",
        {"token": "invalid-token", "new_password": f"{PASSWORD}-other"},
        format="json",
    )
    assert invalid_recovery.status_code == 400
    completed = client.post(
        "/api/v1/public/accounts/recovery/complete",
        {"token": recovery_token, "new_password": f"{PASSWORD}-new"},
        format="json",
    )
    assert completed.status_code == 200
    assert AccountSecurityEvent.objects.filter(
        event_type=AccountSecurityEvent.EventType.RECOVERY_COMPLETED
    ).exists()
    assert not IdentityChallenge.objects.exclude(
        delivery_status=IdentityChallenge.DeliveryStatus.SUCCEEDED
    ).exists()


def test_identity_services_are_enumeration_safe_rate_limited_and_revoke_sessions(
    rf,
) -> None:
    account, dispatch = bootstrap_account(
        email="safe@example.invalid",
        display_name="Safe",
        password=PASSWORD,
        fingerprint="a" * 64,
    )
    assert account is not None
    assert dispatch.raw_token
    repeated, repeated_dispatch = bootstrap_account(
        email="SAFE@example.invalid",
        display_name="Ignored",
        password=PASSWORD,
        fingerprint="b" * 64,
    )
    assert repeated == account
    assert repeated_dispatch.raw_token
    consume_identity_challenge(
        raw_token=repeated_dispatch.raw_token or "",
        purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
    )
    hidden, accepted = bootstrap_account(
        email="safe@example.invalid",
        display_name="Ignored",
        password=PASSWORD,
        fingerprint="c" * 64,
    )
    assert hidden is None
    assert accepted.accepted
    assert request_account_recovery(
        email="missing@example.invalid",
        fingerprint="d" * 64,
    ).accepted

    for _ in range(8):
        enforce_abuse_limit(flow="test", subject_digest="e" * 64)
    with pytest.raises(ValidationError, match="wait"):
        enforce_abuse_limit(flow="test", subject_digest="e" * 64)
    assert IdentityAbuseBucket.objects.get(flow="test").blocked_until

    request = rf.get("/", HTTP_USER_AGENT="Test browser")
    SessionMiddleware(lambda value: value).process_request(request)
    request.session.save()
    item = inventory_session(account=account, request=request)
    assert item is not None
    assert item.session_key_digest == session_key_digest(request.session.session_key)
    assert (
        revoke_all_sessions(
            account=account,
            reason="test",
            exclude_session_id=None,
        )
        == 1
    )


def test_identity_delivery_failure_is_durable_and_retryable(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise OSError("synthetic mail outage")

    monkeypatch.setattr(
        "maru.identity.services._dispatch_challenge_email",
        unavailable,
    )
    account, dispatch = bootstrap_account(
        email="retry-identity@example.invalid",
        display_name="Retry Identity",
        password=PASSWORD,
        fingerprint="f" * 64,
    )
    assert account is not None
    challenge = IdentityChallenge.objects.get(account=account)
    assert challenge.delivery_status == IdentityChallenge.DeliveryStatus.PENDING
    assert challenge.delivery_error_code == "email_provider_unavailable"
    assert challenge.delivery_attempt_count == 1

    delivered: list[str] = []

    def available(*, account, purpose, raw_token):
        del account, purpose
        delivered.append(raw_token)

    monkeypatch.setattr(
        "maru.identity.services._dispatch_challenge_email",
        available,
    )
    output = StringIO()
    call_command("identity_delivery", limit=100, stdout=output)
    assert "attempted 1; 0 remain pending" in output.getvalue()
    challenge.refresh_from_db()
    assert challenge.delivery_status == IdentityChallenge.DeliveryStatus.SUCCEEDED
    assert delivered == [dispatch.raw_token]
    errors = StringIO()
    call_command("identity_delivery", limit=0, stderr=errors)
    assert "between 1 and 10000" in errors.getvalue()


def test_scoped_restriction_issue_appeal_decision_and_revoke_api() -> None:
    edition = EventEditionFactory()
    operator = AccountFactory()
    attendee = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="identity.manage_restrictions",
    )
    client = APIClient()
    client.force_authenticate(operator)
    issued = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/restrictions"
        ),
        {
            "account_id": attendee.id,
            "kind": "registration",
            "reason_code": "conduct-review",
            "attendee_message": "Registration is paused while support reviews this.",
            "internal_reference": "CASE-SYNTHETIC",
            "effective_at": timezone.now().isoformat(),
            "expires_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "notify_account": True,
        },
        format="json",
    )
    assert issued.status_code == 201
    restriction_id = issued.data["id"]
    staff_list = client.get(
        f"/api/v1/organizations/{edition.organization_id}/editions/"
        f"{edition.id}/restrictions"
    )
    assert staff_list.status_code == 200
    assert staff_list.data[0]["id"] == restriction_id
    with pytest.raises(ValidationError, match="paused"):
        enforce_not_restricted(
            account=attendee,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind=AccountRestriction.Kind.REGISTRATION,
        )
    assert (
        active_restrictions(
            account=attendee,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind=AccountRestriction.Kind.REGISTRATION,
        ).count()
        == 1
    )

    self_client = APIClient()
    self_client.force_authenticate(attendee)
    self_list = self_client.get("/api/v1/me/restrictions")
    assert self_list.status_code == 200
    assert self_list.data[0]["id"] == restriction_id
    appealed = self_client.post(
        f"/api/v1/me/restrictions/{restriction_id}/appeals",
        {"statement": "Please review the corrected information."},
        format="json",
    )
    assert appealed.status_code == 201
    appeal_id = appealed.data["id"]
    decided = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/restriction-appeals/{appeal_id}/decision"
        ),
        {"decision": "revoke", "summary": "The concern was resolved."},
        format="json",
    )
    assert decided.status_code == 200
    assert decided.data["status"] == RestrictionAppeal.Status.RESOLVED
    restriction = AccountRestriction.objects.get(id=restriction_id)
    assert restriction.status == AccountRestriction.Status.REVOKED

    repeated = revoke_account_restriction(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        restriction_id=restriction.id,
        reason="Already resolved.",
        correlation_id=uuid4(),
    )
    assert repeated.status == AccountRestriction.Status.REVOKED

    second = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/restrictions"
        ),
        {
            "account_id": attendee.id,
            "kind": "public_profile",
            "reason_code": "profile-review",
            "attendee_message": "The public profile is temporarily hidden.",
            "effective_at": timezone.now().isoformat(),
            "notify_account": False,
        },
        format="json",
    )
    assert second.status_code == 201
    revoked = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/restrictions/{second.data['id']}/revoke"
        ),
        {"reason": "The profile review was completed."},
        format="json",
    )
    assert revoked.status_code == 200
    assert revoked.data["status"] == AccountRestriction.Status.REVOKED

    unauthorized = APIClient()
    unauthorized.force_authenticate(AccountFactory())
    assert (
        unauthorized.get(
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/restrictions"
        ).status_code
        == 403
    )
    assert (
        unauthorized.post(
            (
                f"/api/v1/organizations/{edition.organization_id}/editions/"
                f"{edition.id}/restrictions/{uuid4()}/revoke"
            ),
            {"reason": "No authority."},
            format="json",
        ).status_code
        == 403
    )
    assert (
        unauthorized.post(
            (
                f"/api/v1/organizations/{edition.organization_id}/editions/"
                f"{edition.id}/restriction-appeals/{uuid4()}/decision"
            ),
            {"decision": "uphold", "summary": "No authority."},
            format="json",
        ).status_code
        == 403
    )


def test_restriction_service_rejects_invalid_inputs_and_cross_scope() -> None:
    edition = EventEditionFactory()
    operator = AccountFactory()
    attendee = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="identity.manage_restrictions",
    )
    with pytest.raises(ValidationError, match="supported"):
        issue_account_restriction(
            actor=operator,
            account=attendee,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind="invalid",
            reason_code="",
            attendee_message="",
            internal_reference="",
            effective_at=object(),
            expires_at=None,
            notify_account=False,
            correlation_id=uuid4(),
        )


def test_scheduled_restriction_applies_registration_consequences_once() -> None:
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(edition=edition)
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="admission",
        name="Admission",
        price_minor=10_000,
        capacity=20,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed for a synthetic restriction test."
    configuration.activated_at = now
    configuration.save()
    attendee = AccountFactory()
    participation = ParticipationFactory(
        account=attendee,
        edition=edition,
        status=Participation.Status.PENDING,
    )
    registration = Registration.objects.create(
        organization=edition.organization,
        edition=edition,
        participation=participation,
        account=attendee,
        configuration=configuration,
        product=product,
        reference="SCHEDULED-1",
        state=Registration.State.PAYMENT_PENDING,
        product_name_snapshot=product.name,
        price_minor_snapshot=product.price_minor,
        currency_snapshot=configuration.currency,
        submitted_at=now,
        payment_due_at=now + timedelta(days=2),
    )
    operator = AccountFactory()
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
        kind=AccountRestriction.Kind.ATTENDANCE,
        reason_code="scheduled-policy",
        attendee_message="This registration is no longer available.",
        internal_reference="SYNTHETIC-SCHEDULED",
        effective_at=now + timedelta(hours=1),
        expires_at=None,
        notify_account=True,
        correlation_id=uuid4(),
    )
    assert restriction.consequences_applied_at is None
    assert registration.state == Registration.State.PAYMENT_PENDING

    assert (
        apply_due_account_restrictions(
            edition_id=edition.id,
            now=now + timedelta(hours=2),
        )
        == 1
    )
    registration.refresh_from_db()
    restriction.refresh_from_db()
    assert registration.state == Registration.State.CANCELLED
    assert restriction.consequences_applied_at == now + timedelta(hours=2)
    event = DomainEvent.objects.get(
        aggregate_type="identity.account_restriction",
        aggregate_id=restriction.id,
    )
    assert OutboxMessage.objects.filter(
        event=event,
        destination="notifications",
    ).exists()
    assert (
        apply_due_account_restrictions(
            edition_id=edition.id,
            now=now + timedelta(hours=3),
        )
        == 0
    )
