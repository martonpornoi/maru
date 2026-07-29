from django.contrib import admin

from maru.accreditation.models import (
    Credential,
    CredentialEvent,
    OfflineCheckInOperation,
    OfflineCredentialManifest,
    RelayDevice,
)
from maru.core.admin import ReadOnlyAdminMixin


@admin.register(Credential)
class CredentialAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "public_id",
        "registration",
        "status",
        "issue_sequence",
        "issued_at",
        "revoked_at",
    )
    list_filter = ("organization_id", "edition_id", "status")
    search_fields = ("public_id", "registration__reference")
    exclude = ("token_digest",)


@admin.register(CredentialEvent)
class CredentialEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("credential", "kind", "occurred_at", "reason_code")
    list_filter = ("organization_id", "edition_id", "kind", "occurred_at")


@admin.register(RelayDevice)
class RelayDeviceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("code", "label", "edition_id", "enabled", "last_sequence")
    list_filter = ("organization_id", "edition_id", "enabled")
    exclude = ("signing_secret_env_var",)


@admin.register(OfflineCredentialManifest)
class OfflineCredentialManifestAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "edition_id",
        "sequence",
        "valid_from",
        "valid_until",
        "credential_count",
    )
    list_filter = ("organization_id", "edition_id", "generated_at")
    exclude = ("payload", "signature")


@admin.register(OfflineCheckInOperation)
class OfflineCheckInOperationAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "device",
        "device_sequence",
        "credential_public_id",
        "outcome",
        "occurred_at",
        "received_at",
    )
    list_filter = ("organization_id", "edition_id", "outcome", "received_at")
