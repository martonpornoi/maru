from __future__ import annotations

from django.contrib import admin

from maru.accounts.models import (
    AccessGrant,
    AccessGrantAuditLog,
    AccessRole,
    ArchivedParticipation,
    Notification,
    UserProfile,
)


class AccessRoleInline(admin.TabularInline):
    model = AccessRole
    extra = 1


@admin.register(AccessGrant)
class AccessGrantAdmin(admin.ModelAdmin):
    inlines = [AccessRoleInline]
    list_display = ["email", "active", "can_start_project", "updated_at"]
    list_filter = ["active", "roles__role"]
    search_fields = ["email", "notes"]


@admin.register(AccessGrantAuditLog)
class AccessGrantAuditLogAdmin(admin.ModelAdmin):
    list_display = ["target_email", "action", "actor_email", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["target_email", "actor_email"]
    readonly_fields = [
        "grant",
        "actor",
        "actor_email",
        "target_email",
        "action",
        "before",
        "after",
        "created_at",
    ]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "profile_unlocked",
        "display_name",
        "fursuit_name",
        "show_profile_publicly",
    ]
    list_filter = ["profile_unlocked", "show_profile_publicly"]
    search_fields = ["user__email", "display_name", "fursuit_name"]


@admin.register(ArchivedParticipation)
class ArchivedParticipationAdmin(admin.ModelAdmin):
    list_display = ["user", "year", "project_name", "panel_title"]
    list_filter = ["year", "project_name"]
    search_fields = ["user__email", "project_name", "panel_title"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "title", "link_label", "created_at", "read_at"]
    list_filter = ["created_at", "read_at"]
    search_fields = ["user__email", "title", "body", "link_url", "link_label"]
