from django.contrib import admin

from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)
from maru.core.admin import ReadOnlyAdminMixin


@admin.register(NotificationMessage)
class NotificationMessageAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "account",
        "message_type",
        "purpose",
        "organization_id",
        "edition_id",
        "rendered_at",
        "read_at",
    )
    list_filter = ("purpose", "message_type", "rendered_at", "read_at")
    search_fields = ("account__email", "subject")
    exclude = ("body",)


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "message",
        "channel",
        "status",
        "attempt_count",
        "last_attempt_at",
        "delivered_at",
    )
    list_filter = ("channel", "status", "last_attempt_at")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "account",
        "organization",
        "operational_email_enabled",
        "marketing_email_consent",
    )
    list_filter = (
        "organization",
        "operational_email_enabled",
        "marketing_email_consent",
    )
