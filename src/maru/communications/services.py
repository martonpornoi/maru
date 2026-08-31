"""Rendering and retry-aware delivery of registration service messages."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)
from maru.communications.queries import notification_messages_for_account
from maru.effects.adoption import (
    EFFECT_PROFILE_NOT_ALLOWED,
    effect_delivery_is_allowed,
)
from maru.effects.worker import (
    EffectContext,
    PermanentEffectError,
    TransientEffectError,
)
from maru.identity.models import Account, AccountRestriction
from maru.registration.queries import RegistrationNotificationContext
from maru.registration.queries import notification_context as registration_context

if TYPE_CHECKING:
    from uuid import UUID

    from maru.effects.models import DomainEvent


@dataclass(frozen=True, slots=True)
class RenderedNotification:
    """Describe rendered notification.

    Attributes
    ----------
    message_type
        The closed message type discriminator defined by the domain catalog.
    subject
        The tenant-scoped person or resource governed by the operation.
    body
        The body retained in this immutable projection.
    action_path
        The action path retained in this immutable projection.
    """

    message_type: str
    subject: str
    body: str
    action_path: str


EVENT_LABELS = {
    "registration.submitted.v1": (
        "registration_submitted",
        "Registration received",
        "Your registration has been received.",
    ),
    "registration.payment.reconciled.v1": (
        "payment_confirmed",
        "Payment confirmed",
        "Your payment is confirmed and your admission is active.",
    ),
    "registration.payment.expired.v1": (
        "payment_expired",
        "Payment time expired",
        "The payment window ended and the reserved place was released.",
    ),
    "registration.waitlist.offered.v1": (
        "waitlist_offer",
        "A place is available",
        "A place is now reserved for you until the payment deadline.",
    ),
    "registration.payment.deadline_changed.v1": (
        "payment_deadline_changed",
        "Payment deadline changed",
        "Registration staff changed your payment deadline.",
    ),
    "registration.payment.waived.v1": (
        "payment_waived",
        "Registration confirmed",
        "The payment requirement was waived and your admission is active.",
    ),
    "registration.cancelled.v1": (
        "registration_cancelled",
        "Registration cancelled",
        "Your registration is no longer active.",
    ),
    "registration.checked_in.v1": (
        "checked_in",
        "Checked in",
        "Your arrival was recorded successfully.",
    ),
    "registration.guardian.accepted.v1": (
        "guardian_consent_received",
        "Guardian consent received",
        "Guardian consent was accepted and registration can continue.",
    ),
}


def _require_notification_route(event: DomainEvent) -> None:
    """Reject direct handler invocation outside the exact route contract.

    Parameters
    ----------
    event : DomainEvent
        Persisted domain event whose exact edition route must allow
        notification delivery.

    Raises
    ------
    PermanentEffectError
        If the selected edition profile does not allow the event's
        notification effect route.
    """
    if not effect_delivery_is_allowed(
        organization_id=event.organization_id,
        event_edition_id=event.event_edition_id,
        event_name=event.event_name,
        destination="notifications",
        payload=event.payload,
    ):
        raise PermanentEffectError(EFFECT_PROFILE_NOT_ALLOWED)


def _localized_deadline(
    context: RegistrationNotificationContext,
) -> str:
    if context.payment_due_at is None:
        return ""
    local = context.payment_due_at.astimezone(ZoneInfo(context.edition_time_zone))
    return local.strftime("%Y-%m-%d %H:%M %Z")


def render_registration_notification(
    *,
    event_name: str,
    context: RegistrationNotificationContext,
) -> RenderedNotification:
    """Render registration notification.

    Parameters
    ----------
    event_name : str
        The human-readable event name shown to authorized readers.
    context : RegistrationNotificationContext
        The resolved context for the operation.

    Returns
    -------
    RenderedNotification
        The rendered registration notification.

    Raises
    ------
    PermanentEffectError
        If the operation encounters a permanent effect condition.
    """
    template = EVENT_LABELS.get(event_name)
    if template is None:
        raise PermanentEffectError("notification_template_missing")
    message_type, subject, summary = template
    price = f"{context.amount_minor / 100:.2f} {context.currency}"
    deadline = _localized_deadline(context)
    details = [
        summary,
        "",
        f"Convention: {context.edition_name}",
        f"Registration: {context.reference}",
        f"Admission: {context.product_name}",
        f"Price: {price}",
    ]
    if deadline:
        details.append(f"Payment deadline: {deadline}")
    details.extend(
        [
            "",
            f"Review your registration: {context.registration_path}",
            f"Need help: {context.support_path}",
        ]
    )
    return RenderedNotification(
        message_type=message_type,
        subject=f"{subject} — {context.edition_name}",
        body="\n".join(details),
        action_path=context.registration_path,
    )


def _message_for_event(
    *,
    event: DomainEvent,
    context: RegistrationNotificationContext,
    rendered: RenderedNotification,
) -> NotificationMessage:
    message, _ = NotificationMessage.objects.get_or_create(
        domain_event_id=event.id,
        defaults={
            "account_id": context.account_id,
            "organization_id": context.organization_id,
            "edition_id": context.edition_id,
            "message_type": rendered.message_type,
            "purpose": NotificationMessage.Purpose.OPERATIONAL,
            "locale": context.locale,
            "subject": rendered.subject,
            "body": rendered.body,
            "action_path": rendered.action_path,
            "rendered_at": timezone.now(),
        },
    )
    return message


def _deliver_email_message(
    *,
    message: NotificationMessage,
    recipient: str,
    effect_context: EffectContext,
) -> None:
    with transaction.atomic():
        preference = NotificationPreference.objects.filter(
            account_id=message.account_id,
            organization_id=message.organization_id,
        ).first()
        enabled = preference is None or preference.operational_email_enabled
        delivery, _ = NotificationDelivery.objects.select_for_update().get_or_create(
            message=message,
            channel=NotificationDelivery.Channel.EMAIL,
            defaults={"status": NotificationDelivery.Status.PENDING},
        )
        if delivery.status in (
            NotificationDelivery.Status.SUCCEEDED,
            NotificationDelivery.Status.SUPPRESSED,
        ):
            return
        delivery.attempt_count += 1
        delivery.last_attempt_at = timezone.now()
        if not enabled:
            delivery.status = NotificationDelivery.Status.SUPPRESSED
            delivery.safe_error_code = "operational_email_disabled"
            delivery.save(
                update_fields=(
                    "attempt_count",
                    "last_attempt_at",
                    "status",
                    "safe_error_code",
                    "updated_at",
                )
            )
            return
        delivery.save(update_fields=("attempt_count", "last_attempt_at", "updated_at"))
    try:
        sent = send_mail(
            message.subject,
            message.body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except smtplib.SMTPRecipientsRefused as error:
        with transaction.atomic():
            delivery = NotificationDelivery.objects.select_for_update().get(
                id=delivery.id
            )
            delivery.status = NotificationDelivery.Status.PERMANENT_FAILED
            delivery.safe_error_code = "email_recipient_rejected"
            delivery.save(update_fields=("status", "safe_error_code", "updated_at"))
        raise PermanentEffectError("email_recipient_rejected") from error
    except (OSError, smtplib.SMTPException) as error:
        raise TransientEffectError("email_provider_unavailable") from error
    if sent != 1:
        raise TransientEffectError("email_delivery_ambiguous")
    with transaction.atomic():
        delivery = NotificationDelivery.objects.select_for_update().get(id=delivery.id)
        delivery.status = NotificationDelivery.Status.SUCCEEDED
        delivery.remote_identity = effect_context.idempotency_key
        delivery.safe_error_code = ""
        delivery.delivered_at = timezone.now()
        delivery.save(
            update_fields=(
                "status",
                "remote_identity",
                "safe_error_code",
                "delivered_at",
                "updated_at",
            )
        )


def deliver_registration_notification(
    event: DomainEvent,
    effect_context: EffectContext,
) -> None:
    """Return deliver registration notification.

    Parameters
    ----------
    event : DomainEvent
        The immutable domain event to process.
    effect_context : EffectContext
        The effect context applied within the audited domain transition.

    Raises
    ------
    PermanentEffectError
        If the operation encounters a permanent effect condition.
    TransientEffectError
        If the operation encounters a transient effect condition.
    """
    _require_notification_route(event)
    if timezone.now() >= effect_context.deadline:
        raise TransientEffectError("notification_delivery_timeout")
    if event.event_edition_id is None:
        raise PermanentEffectError("notification_event_scope_missing")
    context = registration_context(
        registration_id=event.aggregate_id,
        organization_id=event.organization_id,
        edition_id=event.event_edition_id,
    )
    if context is None:
        raise PermanentEffectError("notification_registration_missing")
    rendered = render_registration_notification(
        event_name=event.event_name,
        context=context,
    )
    with transaction.atomic():
        message = _message_for_event(
            event=event,
            context=context,
            rendered=rendered,
        )
    _deliver_email_message(
        message=message,
        recipient=context.email,
        effect_context=effect_context,
    )


def deliver_restriction_notification(
    event: DomainEvent,
    effect_context: EffectContext,
) -> None:
    """Deliver only the safe attendee-facing restriction explanation.

    Parameters
    ----------
    event : DomainEvent
        The immutable domain event to process.
    effect_context : EffectContext
        The effect context applied within the audited domain transition.

    Raises
    ------
    PermanentEffectError
        If the operation encounters a permanent effect condition.
    TransientEffectError
        If the operation encounters a transient effect condition.
    """
    _require_notification_route(event)
    if timezone.now() >= effect_context.deadline:
        raise TransientEffectError("notification_delivery_timeout")
    restriction = (
        AccountRestriction.objects.select_related("account", "edition")
        .filter(
            id=event.aggregate_id,
            organization_id=event.organization_id,
        )
        .first()
    )
    if restriction is None:
        raise PermanentEffectError("notification_restriction_missing")
    edition_label = (
        restriction.edition.name if restriction.edition else "this organizer"
    )
    message, _ = NotificationMessage.objects.get_or_create(
        domain_event_id=event.id,
        defaults={
            "account": restriction.account,
            "organization_id": restriction.organization_id,
            "edition_id": restriction.edition_id,
            "message_type": "account_restriction_applied",
            "purpose": NotificationMessage.Purpose.OPERATIONAL,
            "locale": restriction.account.preferred_language,
            "subject": f"Account access changed — {edition_label}",
            "body": (
                f"{restriction.attendee_message}\n\n"
                "You can review the restriction and submit an appeal in Maru.\n"
                "Review account security: /admin/workspace/?view=security"
            ),
            "action_path": "/admin/workspace/?view=security",
            "rendered_at": timezone.now(),
        },
    )
    _deliver_email_message(
        message=message,
        recipient=restriction.account.email,
        effect_context=effect_context,
    )


def mark_message_read(*, account: Account, message_id: UUID) -> NotificationMessage:
    """Mark message read.

    Parameters
    ----------
    account : Account
        The account applied within the audited domain transition.
    message_id : UUID
        The identifier of the message.

    Returns
    -------
    NotificationMessage
        The updated NotificationMessage after the transition commits.
    """
    with transaction.atomic():
        message = (
            notification_messages_for_account(account=account)
            .select_for_update()
            .get(
                id=message_id,
            )
        )
        if message.read_at is None:
            message.read_at = timezone.now()
            message.save(update_fields=("read_at", "updated_at"))
        return message
