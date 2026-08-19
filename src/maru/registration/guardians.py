"""Guardian-consent activation without holding capacity before consent."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from maru.registration.availability import OCCUPIED_REGISTRATION_STATES
from maru.registration.models import (
    GuardianConsent,
    MinorRegistrationPolicy,
    Registration,
)
from maru.registration.services import (
    _append_timeline,
    _grant_product_entitlement,
    _payment_deadline,
    _publish_registration_transition,
)

GUARDIAN_CONSENT_LIFETIME = timedelta(days=7)


def _token_digest(raw_token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"guardian-consent:{raw_token}".encode(),
        hashlib.sha256,
    ).hexdigest()


def create_guardian_consent(
    *,
    registration: Registration,
    policy: MinorRegistrationPolicy,
    guardian_name: str,
    guardian_email: str,
    relationship: str,
) -> tuple[GuardianConsent, str | None]:
    """Create guardian consent.

    Parameters
    ----------
    registration : Registration
        The attendee registration governed by the requested transition.
    policy : MinorRegistrationPolicy
        The closed policy definition governing the requested decision.
    guardian_name : str
        The human-readable guardian name shown to authorized readers.
    guardian_email : str
        The normalized guardian email used for delivery or identity matching.
    relationship : str
        The relationship evaluated while create guardian consent.

    Returns
    -------
    tuple[GuardianConsent, str | None]
        The persisted record after validation and transaction commit.
    """
    raw_token = secrets.token_urlsafe(32)
    requested_at = timezone.now()
    consent = GuardianConsent.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        policy=policy,
        guardian_name=guardian_name.strip(),
        guardian_email=guardian_email.strip().lower(),
        relationship=relationship.strip(),
        notice_version=policy.guardian_notice_version,
        token_digest=_token_digest(raw_token),
        requested_at=requested_at,
        expires_at=requested_at + GUARDIAN_CONSENT_LIFETIME,
    )
    public_base = settings.MARU_PUBLIC_BASE_URL.rstrip("/")
    link = f"{public_base}/guardian-consent/?token={raw_token}"
    transaction.on_commit(
        lambda: send_mail(
            f"Guardian consent — {registration.edition.name}",
            (
                f"{guardian_name}, review the guardian notice and authorize "
                f"registration {registration.reference} within seven days:\n\n"
                f"{link}\n\nIf this request is unexpected, do not use the link."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [guardian_email],
            fail_silently=False,
        )
    )
    return (
        consent,
        raw_token if settings.IDENTITY_EXPOSE_TEST_TOKENS else None,
    )


def accept_guardian_consent(
    *,
    raw_token: str,
    guardian_name: str,
) -> Registration:
    """Accept guardian consent.

    Parameters
    ----------
    raw_token : str
        The untrusted token supplied by the caller.
    guardian_name : str
        The human-readable guardian name shown to authorized readers.

    Returns
    -------
    Registration
        The updated Registration after the transition commits.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    accepted_at = timezone.now()
    with transaction.atomic():
        consent = (
            GuardianConsent.objects.select_for_update()
            .select_related(
                "registration",
                "registration__configuration",
                "registration__product",
            )
            .filter(token_digest=_token_digest(raw_token))
            .first()
        )
        if (
            consent is None
            or consent.status != GuardianConsent.Status.PENDING
            or consent.expires_at <= accepted_at
        ):
            raise ValidationError(
                "This guardian link is invalid or has expired.",
                code="guardian_consent_invalid",
            )
        if not guardian_name.strip():
            raise ValidationError(
                "Enter the guardian name used for this authorization.",
                code="guardian_name_required",
            )
        registration = Registration.objects.select_for_update().get(
            id=consent.registration_id
        )
        if registration.state != Registration.State.GUARDIAN_PENDING:
            raise ValidationError(
                "This registration is no longer awaiting guardian consent.",
                code="guardian_consent_not_pending",
            )
        configuration = registration.configuration
        product = registration.product
        product_count = Registration.objects.filter(
            product=product,
            state__in=OCCUPIED_REGISTRATION_STATES,
        ).count()
        total_count = Registration.objects.filter(
            configuration=configuration,
            state__in=OCCUPIED_REGISTRATION_STATES,
        ).count()
        capacity_reached = (
            product_count >= product.capacity or total_count >= configuration.capacity
        )
        previous_state = registration.state
        if capacity_reached:
            registration.state = Registration.State.WAITLISTED
            registration.waitlisted_at = accepted_at
        elif registration.price_minor_snapshot == 0:
            registration.state = Registration.State.CONFIRMED
            registration.confirmed_at = accepted_at
            registration.confirmation_basis = Registration.ConfirmationBasis.FREE
        else:
            registration.state = Registration.State.PAYMENT_PENDING
            registration.payment_due_at = _payment_deadline(
                configuration=configuration,
                product=product,
                starts_at=accepted_at,
            )
        registration.aggregate_version += 1
        registration.save(
            update_fields=(
                "state",
                "waitlisted_at",
                "payment_due_at",
                "confirmed_at",
                "confirmation_basis",
                "aggregate_version",
                "updated_at",
            )
        )
        consent.status = GuardianConsent.Status.ACCEPTED
        consent.decided_at = accepted_at
        consent.guardian_name_at_decision = guardian_name.strip()
        consent.save(
            update_fields=(
                "status",
                "decided_at",
                "guardian_name_at_decision",
                "updated_at",
            )
        )
        if registration.state == Registration.State.CONFIRMED:
            _grant_product_entitlement(
                registration=registration,
                granted_at=accepted_at,
            )
        _append_timeline(
            registration=registration,
            kind="guardian_consent_received",
            title="Guardian consent received",
            summary=(
                "The guardian authorization was accepted. "
                + (
                    "The registration joined the waitlist."
                    if registration.state == Registration.State.WAITLISTED
                    else "Payment is the next step."
                    if registration.state == Registration.State.PAYMENT_PENDING
                    else "Admission is confirmed."
                )
            ),
            occurred_at=accepted_at,
            actor_kind="guardian",
            actor_id=None,
            correlation_id=consent.id,
        )
        _publish_registration_transition(
            registration=registration,
            event_name="registration.guardian.accepted.v1",
            from_state=previous_state,
            correlation_id=consent.id,
            actor_kind="guardian",
            actor_id=None,
        )
        return registration
