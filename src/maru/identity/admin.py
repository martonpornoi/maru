"""Inspection-only administration for platform identity records."""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from maru.core.admin import ReadOnlyAdminMixin
from maru.events.admin_context import selected_admin_edition
from maru.identity.models import (
    Account,
    AccountRestriction,
    AccountSecurityEvent,
    AccountSession,
    IdentityAbuseBucket,
    IdentityChallenge,
    PlatformInvitationSchedulerRun,
    RestrictionAppeal,
)


@admin.register(Account)
class AccountAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    """Minimized identity inspection; every account mutation is command-owned."""

    ordering = ("date_joined", "id")
    list_display = (
        "person",
        "login_handle",
        "email",
        "preferred_language",
        "email_verified_at",
        "date_joined",
    )
    list_display_links = ("person", "login_handle", "email")
    list_filter = ("preferred_language", "email_verified_at")
    search_fields = ("email", "login_handle", "display_name")
    date_hierarchy = "date_joined"
    list_per_page = 50
    actions = None
    readonly_fields = (
        "id",
        "email",
        "login_handle",
        "display_name",
        "preferred_language",
        "email_verified_at",
        "date_joined",
        "last_login",
    )
    fields = readonly_fields

    @admin.display(description="Person", ordering="display_name")
    def person(self, obj: Account) -> str:
        return obj.display_name or obj.email

    def get_queryset(self, request: HttpRequest) -> QuerySet[Account]:
        queryset = super().get_queryset(request)
        edition = selected_admin_edition(request)
        if edition is None or request.path == "/admin/autocomplete/":
            return queryset
        return queryset.filter(event_participations__edition_id=edition.id).distinct()


@admin.register(AccountSecurityEvent)
class AccountSecurityEventAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "account",
        "event_type",
        "outcome",
        "occurred_at",
        "source_channel",
    )
    list_display_links = ("account", "event_type")
    list_filter = ("event_type", "outcome", "source_channel", "occurred_at")
    search_fields = ("account__display_name", "account__email", "detail_code")
    ordering = ("-occurred_at",)
    list_select_related = ("account",)
    date_hierarchy = "occurred_at"
    readonly_fields = (
        "account",
        "event_type",
        "outcome",
        "occurred_at",
        "source_channel",
        "detail_code",
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(IdentityChallenge)
class IdentityChallengeAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    """Show safe lifecycle facts without exposing C3 or legacy delivery fields."""

    list_display = (
        "account",
        "purpose",
        "expires_at",
        "consumed_at",
        "invalidated_at",
    )
    list_filter = ("purpose", "expires_at", "consumed_at", "invalidated_at")
    search_fields = ("account__email",)
    readonly_fields = (
        "account",
        "purpose",
        "email_snapshot",
        "expires_at",
        "consumed_at",
        "invalidated_at",
        "invalidation_reason",
        "attempt_count",
        "delivery_boundary",
        "id",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    @admin.display(description="Delivery ownership")
    def delivery_boundary(self, obj: IdentityChallenge) -> str:
        if obj.purpose == IdentityChallenge.Purpose.ACCOUNT_INVITATION:
            return (
                "Invitation delivery is governed by the purpose-built Accounts "
                "workspace; legacy challenge delivery fields are not evidence."
            )
        return (
            "Delivery belongs to the purpose-specific identity workflow; this "
            "generic challenge page does not assert delivery state."
        )


@admin.register(AccountSession)
class AccountSessionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "account",
        "label",
        "last_seen_at",
        "step_up_verified_at",
        "revoked_at",
    )
    list_filter = ("created_channel", "revoked_at", "step_up_verified_at")
    search_fields = ("account__email", "account__display_name", "label")
    exclude = ("session_key_digest", "session")


@admin.register(IdentityAbuseBucket)
class IdentityAbuseBucketAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "flow",
        "window_started_at",
        "attempt_count",
        "blocked_until",
    )
    list_filter = ("flow", "window_started_at", "blocked_until")
    exclude = ("subject_digest",)


@admin.register(PlatformInvitationSchedulerRun)
class PlatformInvitationSchedulerRunAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    """Count-only operational evidence; recipient identity never appears here."""

    list_display = (
        "kind",
        "generation",
        "ran_at",
        "processed_count",
        "remaining_count",
        "private_key_coverage_complete",
    )
    list_filter = ("kind", "generation", "private_key_coverage_complete")
    ordering = ("-ran_at", "-id")
    date_hierarchy = "ran_at"
    readonly_fields = (
        "id",
        "kind",
        "generation",
        "ran_at",
        "processed_count",
        "remaining_count",
        "private_key_coverage_complete",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields


class RestrictionAppealInline(admin.TabularInline):  # type: ignore[type-arg]
    model = RestrictionAppeal
    extra = 0
    can_delete = False
    readonly_fields = (
        "account",
        "statement",
        "status",
        "submitted_at",
        "decided_at",
        "decided_by",
        "decision_summary",
    )


@admin.register(AccountRestriction)
class AccountRestrictionAdmin(
    ReadOnlyAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
    list_display = (
        "account",
        "organization",
        "edition",
        "kind",
        "status",
        "effective_at",
        "expires_at",
    )
    list_filter = ("organization", "edition", "kind", "status")
    search_fields = (
        "account__email",
        "account__display_name",
        "reason_code",
        "internal_reference",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "revoked_at",
        "revoked_by",
        "revocation_reason",
    )
    inlines = (RestrictionAppealInline,)
