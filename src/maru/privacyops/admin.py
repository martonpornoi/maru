from django.contrib import admin

from maru.core.admin import ReadOnlyAdminMixin
from maru.privacyops.models import (
    DisposalReceipt,
    PostEditionCorrection,
    RetentionPolicy,
    SubjectRightsRequest,
)


@admin.register(SubjectRightsRequest)
class SubjectRightsRequestAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = ("account", "kind", "status", "organization_id", "requested_at")
    list_filter = ("kind", "status", "organization_id", "requested_at")
    search_fields = ("account__email", "request_summary")


@admin.register(PostEditionCorrection)
class PostEditionCorrectionAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "target_type",
        "target_id",
        "status",
        "edition_id",
        "requested_at",
    )
    list_filter = ("status", "organization_id", "edition_id", "requested_at")


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "data_category",
        "jurisdiction_code",
        "version",
        "retention_days",
        "disposition",
        "active",
    )
    list_filter = ("organization_id", "jurisdiction_code", "active", "disposition")


@admin.register(DisposalReceipt)
class DisposalReceiptAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "target_type",
        "target_id",
        "disposition",
        "applied_at",
        "safe_result_code",
    )
    list_filter = ("organization_id", "edition_id", "disposition", "applied_at")
