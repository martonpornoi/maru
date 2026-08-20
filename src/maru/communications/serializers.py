"""Inbox, preference, and delivery-failure projections."""

from rest_framework import serializers

from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)


class NotificationDeliverySerializer(serializers.ModelSerializer[NotificationDelivery]):
    """Serialize and validate notification delivery data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = NotificationDelivery
        fields = (
            "channel",
            "status",
            "attempt_count",
            "safe_error_code",
            "last_attempt_at",
            "delivered_at",
        )
        read_only_fields = fields


class NotificationMessageSerializer(serializers.ModelSerializer[NotificationMessage]):
    """Serialize and validate notification message data."""

    deliveries = NotificationDeliverySerializer(many=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = NotificationMessage
        fields = (
            "id",
            "organization_id",
            "edition_id",
            "message_type",
            "purpose",
            "locale",
            "subject",
            "body",
            "action_path",
            "rendered_at",
            "read_at",
            "deliveries",
        )
        read_only_fields = fields


class NotificationPreferenceSerializer(
    serializers.ModelSerializer[NotificationPreference]
):
    """Serialize and validate notification preference data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = NotificationPreference
        fields = (
            "organization_id",
            "operational_email_enabled",
            "marketing_email_consent",
            "marketing_consent_version",
            "marketing_consented_at",
        )
        read_only_fields = (
            "organization_id",
            "marketing_consent_version",
            "marketing_consented_at",
        )


class UpdateNotificationPreferenceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate update notification preference data."""

    operational_email_enabled = serializers.BooleanField()
    marketing_email_consent = serializers.BooleanField()
    marketing_consent_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=40,
    )


class DeliveryFailureSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate delivery failure data."""

    message_id = serializers.UUIDField()
    account_id = serializers.UUIDField()
    message_type = serializers.CharField()
    subject = serializers.CharField()
    channel = serializers.CharField()
    status = serializers.CharField()
    attempt_count = serializers.IntegerField()
    safe_error_code = serializers.CharField()
    last_attempt_at = serializers.DateTimeField(allow_null=True)
