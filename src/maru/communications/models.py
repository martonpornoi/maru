"""Purpose-separated operational messages and external delivery evidence."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel


class NotificationPreference(UUIDTimeStampedModel):
    """Organizer-specific preferences; service inbox remains mandatory."""

    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="notification_preferences",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="notification_preferences",
    )
    operational_email_enabled = models.BooleanField(default=True)
    marketing_email_consent = models.BooleanField(default=False)
    marketing_consent_version = models.CharField(max_length=40, blank=True)
    marketing_consented_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("account", "organization"),
                name="notification_preference_account_org_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.marketing_email_consent != bool(
            self.marketing_consent_version and self.marketing_consented_at
        ):
            raise ValidationError(
                "Marketing consent requires versioned evidence.",
                code="marketing_consent_evidence_mismatch",
            )


class NotificationMessage(UUIDTimeStampedModel):
    """Immutable rendered operational message in the platform inbox."""

    class Purpose(models.TextChoices):
        OPERATIONAL = "operational", "Operational service"
        MARKETING = "marketing", "Optional marketing"
        EMERGENCY = "emergency", "Emergency"

    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="notification_messages",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField(null=True, blank=True)
    domain_event_id = models.UUIDField(unique=True)
    message_type = models.CharField(max_length=80)
    purpose = models.CharField(max_length=20, choices=Purpose)
    locale = models.CharField(max_length=35)
    subject = models.CharField(max_length=200)
    body = models.TextField(max_length=8000)
    action_path = models.CharField(max_length=500, blank=True)
    rendered_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-rendered_at", "-id")
        indexes = [
            models.Index(
                fields=("account", "read_at", "rendered_at"),
                name="communications_inbox_idx",
            ),
            models.Index(
                fields=("organization_id", "edition_id", "message_type"),
                name="comm_message_scope_idx",
            ),
        ]

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Messages require the communication retention workflow.",
            code="protected_notification_message",
        )


class NotificationDelivery(UUIDTimeStampedModel):
    """Mutable delivery state backed by append-only effect attempts."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        SUPPRESSED = "suppressed", "Suppressed by preference"
        PERMANENT_FAILED = "permanent_failed", "Permanent failure"

    message = models.ForeignKey(
        NotificationMessage,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    channel = models.CharField(max_length=20, choices=Channel)
    status = models.CharField(max_length=24, choices=Status)
    attempt_count = models.PositiveIntegerField(default=0)
    remote_identity = models.CharField(max_length=160, blank=True)
    safe_error_code = models.CharField(max_length=120, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "notification deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=("message", "channel"),
                name="notification_delivery_channel_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("status", "last_attempt_at"),
                name="comm_delivery_queue_idx",
            )
        ]
