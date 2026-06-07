from __future__ import annotations

from django.contrib import admin

from maru.projects.models import (
    Application,
    ApplicationVersion,
    EventGroup,
    ExportAccessLog,
    ExportToken,
    FormField,
    Hotel,
    HotelFloorPlan,
    Panel,
    Project,
    ProjectRoomAvailability,
    ProjectRoomCombinationAvailability,
    ProjectRoomCombinationSetting,
    ProjectRoomSetting,
    Room,
    RoomCombination,
    SignageReminder,
    Subproject,
    TimetablePlacement,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
)


class SubprojectInline(admin.TabularInline):
    model = Subproject
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    inlines = [SubprojectInline]
    filter_horizontal = ["hotels"]
    list_display = [
        "name",
        "slug",
        "timezone",
        "opens_at",
        "closes_at",
        "timetable_round",
        "profile_exports_enabled",
        "profile_contact_exports_enabled",
    ]
    list_filter = [
        "timetable_round",
        "profile_exports_enabled",
        "profile_contact_exports_enabled",
    ]
    search_fields = ["name", "slug"]


@admin.register(ExportToken)
class ExportTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "export_type", "active", "updated_at"]
    list_filter = ["export_type", "active", "project"]
    readonly_fields = ["token", "created_at", "updated_at"]
    search_fields = ["name", "project__name", "token"]


@admin.register(ExportAccessLog)
class ExportAccessLogAdmin(admin.ModelAdmin):
    list_display = [
        "export_type",
        "project",
        "export_token",
        "success",
        "status_code",
        "remote_address",
        "created_at",
    ]
    list_filter = ["export_type", "success", "status_code", "project"]
    readonly_fields = [
        "project",
        "export_token",
        "export_type",
        "token_hash",
        "success",
        "status_code",
        "remote_address",
        "user_agent",
        "created_at",
    ]
    search_fields = ["token_hash", "remote_address", "user_agent"]


@admin.register(SignageReminder)
class SignageReminderAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "project",
        "starts_at",
        "ends_at",
        "priority",
        "active",
    ]
    list_filter = ["active", "project"]
    search_fields = ["title", "body", "project__name"]


class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0


@admin.register(Subproject)
class SubprojectAdmin(admin.ModelAdmin):
    inlines = [FormFieldInline]
    list_display = [
        "name",
        "project",
        "slug",
        "kind",
        "form_status",
        "is_timetable_source",
        "accepts_reopen_requests",
    ]
    list_filter = [
        "kind",
        "form_status",
        "is_timetable_source",
        "accepts_reopen_requests",
        "project",
    ]
    search_fields = ["name", "slug", "project__name"]


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0


class RoomCombinationInline(admin.TabularInline):
    model = RoomCombination
    extra = 0


class HotelFloorPlanInline(admin.TabularInline):
    model = HotelFloorPlan
    extra = 0


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    inlines = [RoomInline, RoomCombinationInline, HotelFloorPlanInline]
    list_display = ["name", "project_names"]
    search_fields = ["name", "projects__name"]

    @admin.display(description="Projects")
    def project_names(self, hotel: Hotel) -> str:
        return ", ".join(hotel.projects.values_list("name", flat=True))


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "hotel", "capacity"]
    list_filter = ["hotel"]
    search_fields = ["name", "hotel__name", "hotel__projects__name"]


@admin.register(RoomCombination)
class RoomCombinationAdmin(admin.ModelAdmin):
    list_display = ["name", "hotel", "capacity"]
    list_filter = ["hotel"]
    search_fields = ["name", "hotel__name", "hotel__projects__name"]
    filter_horizontal = ["rooms"]


class ProjectRoomAvailabilityInline(admin.TabularInline):
    model = ProjectRoomAvailability
    extra = 0


@admin.register(ProjectRoomSetting)
class ProjectRoomSettingAdmin(admin.ModelAdmin):
    inlines = [ProjectRoomAvailabilityInline]
    list_display = ["display_name", "project", "room", "blocked"]
    list_filter = ["project", "blocked", "room__hotel"]
    search_fields = ["local_name", "room__name", "project__name"]


class ProjectRoomCombinationAvailabilityInline(admin.TabularInline):
    model = ProjectRoomCombinationAvailability
    extra = 0


@admin.register(ProjectRoomCombinationSetting)
class ProjectRoomCombinationSettingAdmin(admin.ModelAdmin):
    inlines = [ProjectRoomCombinationAvailabilityInline]
    list_display = ["display_name", "project", "room_combination", "blocked"]
    list_filter = ["project", "blocked", "room_combination__hotel"]
    search_fields = ["local_name", "room_combination__name", "project__name"]


class ApplicationVersionInline(admin.TabularInline):
    model = ApplicationVersion
    extra = 0
    readonly_fields = ["version", "answers", "submitted_at"]
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    inlines = [ApplicationVersionInline]
    list_display = [
        "title",
        "subproject",
        "applicant",
        "status",
        "has_event_header_image",
        "submitted_at",
    ]
    list_filter = ["status", "subproject__project", "subproject"]
    search_fields = ["title", "applicant__email", "subproject__name"]

    @admin.display(boolean=True, description="Header image")
    def has_event_header_image(self, application: Application) -> bool:
        return bool(application.event_header_image)


@admin.register(EventGroup)
class EventGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "slug", "requires_order", "updated_at"]
    list_filter = ["project", "requires_order"]
    search_fields = ["name", "slug", "project__name"]


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "project",
        "owner",
        "event_group",
        "group_order",
        "recurrence_label",
        "updated_at",
    ]
    list_filter = ["project", "event_group"]
    search_fields = ["title", "owner__email", "project__name", "event_group__name"]


@admin.register(TimetablePlacement)
class TimetablePlacementAdmin(admin.ModelAdmin):
    list_display = ["panel", "layer", "starts_at", "ends_at", "location_name"]
    list_filter = ["layer", "panel__project"]
    search_fields = ["panel__title", "room__name", "room_combination__name"]


@admin.register(VolunteerShift)
class VolunteerShiftAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "project",
        "role",
        "needed_volunteers",
        "locked",
        "updated_at",
    ]
    list_filter = ["project", "role", "locked"]
    search_fields = ["title", "role", "project__name"]


@admin.register(VolunteerShiftPlacement)
class VolunteerShiftPlacementAdmin(admin.ModelAdmin):
    list_display = ["shift", "layer", "starts_at", "ends_at", "location_name"]
    list_filter = ["layer", "shift__project"]
    search_fields = ["shift__title", "room__name", "room_combination__name"]


@admin.register(VolunteerShiftAssignment)
class VolunteerShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ["shift", "user", "status", "assigned_by", "assigned_at"]
    list_filter = ["status", "shift__project", "shift__role"]
    search_fields = ["shift__title", "user__email", "assigned_by__email"]
