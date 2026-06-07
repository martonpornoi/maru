from __future__ import annotations

from django.contrib import admin

from maru.accounts.models import (
    AccessBenefit,
    AccessConfigurationAuditLog,
    AccessGrant,
    AccessGrantAuditLog,
    AccessRole,
    ArchivedParticipation,
    LabelOverride,
    Notification,
    RoleAssignment,
    RoleDefinition,
    StatusBenefitGrant,
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
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
    search_fields = [
        "user__email",
        "display_name",
        "fursuit_name",
        "personal_email",
        "convention_email",
    ]


@admin.register(UserConventionProfile)
class UserConventionProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "project",
        "ticket_level_selected",
        "ticket_level_verified",
        "fursuiter_status",
        "attendee_type",
        "volunteer_type",
        "roles",
    ]
    list_filter = [
        "project",
        "ticket_level_selected",
        "ticket_level_verified",
        "fursuiter_status",
        "attendee_type",
        "volunteer_type",
    ]
    search_fields = ["user__email", "project__name", "roles"]


@admin.register(RoleDefinition)
class RoleDefinitionAdmin(admin.ModelAdmin):
    list_display = ["name", "key", "project", "active", "system_default"]
    list_filter = ["project", "active", "system_default"]
    search_fields = ["name", "key", "permissions"]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "project", "role_definition"]
    list_filter = ["project", "role_definition"]
    search_fields = ["user__email", "role_definition__name"]


@admin.register(AccessBenefit)
class AccessBenefitAdmin(admin.ModelAdmin):
    list_display = ["label", "key", "target", "project", "active"]
    list_filter = ["project", "target", "active"]
    search_fields = ["label", "key", "description"]


@admin.register(StatusBenefitGrant)
class StatusBenefitGrantAdmin(admin.ModelAdmin):
    list_display = ["status_type", "status_value", "benefit", "project"]
    list_filter = ["project", "status_type", "status_value"]
    search_fields = ["status_value", "benefit__label"]


@admin.register(LabelOverride)
class LabelOverrideAdmin(admin.ModelAdmin):
    list_display = ["key", "label", "project"]
    list_filter = ["project"]
    search_fields = ["key", "label"]


@admin.register(AccessConfigurationAuditLog)
class AccessConfigurationAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "action",
        "target_type",
        "target_key",
        "project",
        "actor_email",
        "created_at",
    ]
    list_filter = ["action", "target_type", "project", "created_at"]
    search_fields = ["target_key", "actor_email"]
    readonly_fields = [
        "project",
        "actor",
        "actor_email",
        "action",
        "target_type",
        "target_key",
        "before",
        "after",
        "created_at",
    ]


@admin.register(UserTileColorRule)
class UserTileColorRuleAdmin(admin.ModelAdmin):
    list_display = [
        "target_type",
        "target_value",
        "applies_to",
        "background_color",
        "priority",
        "active",
    ]
    list_filter = ["target_type", "applies_to", "active"]
    search_fields = ["target_value"]


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
