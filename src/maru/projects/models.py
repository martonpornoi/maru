from __future__ import annotations

import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from maru.domain import (
    ApplicationStatus,
    AssignmentStatus,
    ExportType,
    FormStatus,
    SubprojectKind,
    TimetableLayer,
    TimetableRound,
)


def generate_export_token() -> str:
    return secrets.token_urlsafe(32)


class Project(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120, unique=True)
    timezone = models.CharField(max_length=64)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    timetable_round = models.CharField(
        max_length=64,
        choices=[(round_.value, round_.value) for round_ in TimetableRound],
        default=TimetableRound.PRIVATE_PLACEMENT.value,
    )
    hotels = models.ManyToManyField("Hotel", related_name="projects", blank=True)
    profile_exports_enabled = models.BooleanField(default=False)
    profile_contact_exports_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["opens_at", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_closed(self) -> bool:
        return self.closes_at <= timezone.now()


class ProjectArchiveSnapshot(models.Model):
    project = models.OneToOneField(
        Project,
        related_name="archive_snapshot",
        on_delete=models.CASCADE,
    )
    closed_at = models.DateTimeField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-closed_at", "project__name"]

    def __str__(self) -> str:
        return f"{self.project.name} archive"


class ExportToken(models.Model):
    project = models.ForeignKey(
        Project, related_name="export_tokens", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    token = models.CharField(
        max_length=96, unique=True, default=generate_export_token
    )
    export_type = models.CharField(
        max_length=64,
        choices=[(export_type.value, export_type.value) for export_type in ExportType],
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__opens_at", "name"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.name}"


class ExportAccessLog(models.Model):
    project = models.ForeignKey(
        Project,
        related_name="export_access_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    export_token = models.ForeignKey(
        ExportToken,
        related_name="access_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    export_type = models.CharField(
        max_length=64,
        choices=[(export_type.value, export_type.value) for export_type in ExportType],
    )
    token_hash = models.CharField(max_length=64)
    success = models.BooleanField(default=False)
    status_code = models.PositiveSmallIntegerField(default=404)
    remote_address = models.CharField(max_length=80, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        outcome = "ok" if self.success else "denied"
        return f"{self.export_type}: {outcome} at {self.created_at:%Y-%m-%d %H:%M}"


class SignageReminder(models.Model):
    project = models.ForeignKey(
        Project, related_name="signage_reminders", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    priority = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "starts_at", "title"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.title}"


class Subproject(models.Model):
    project = models.ForeignKey(
        Project, related_name="subprojects", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120)
    kind = models.CharField(
        max_length=64,
        choices=[(kind.value, kind.value) for kind in SubprojectKind],
    )
    form_status = models.CharField(
        max_length=32,
        choices=[(status.value, status.value) for status in FormStatus],
        default=FormStatus.PUBLISHED.value,
    )
    inherited_from = models.ForeignKey(
        "self",
        related_name="inherited_forms",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    is_timetable_source = models.BooleanField(default=False)
    accepts_reopen_requests = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "slug"], name="unique_subproject_slug_per_project"
            )
        ]
        ordering = ["project__opens_at", "name"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.name}"


class Hotel(models.Model):
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    hotel = models.ForeignKey(Hotel, related_name="rooms", on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    properties = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "name"], name="unique_room_name_per_hotel"
            )
        ]
        ordering = ["hotel__name", "name"]

    def __str__(self) -> str:
        return f"{self.hotel.name}: {self.name}"


class RoomCombination(models.Model):
    hotel = models.ForeignKey(
        Hotel, related_name="room_combinations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    rooms = models.ManyToManyField(Room, related_name="combinations", blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "name"], name="unique_room_combination_per_hotel"
            )
        ]
        ordering = ["hotel__name", "name"]

    def __str__(self) -> str:
        return f"{self.hotel.name}: {self.name}"


class HotelFloorPlan(models.Model):
    hotel = models.ForeignKey(
        Hotel, related_name="floor_plans", on_delete=models.CASCADE
    )
    floor_label = models.CharField(max_length=120)
    image = models.ImageField(upload_to="hotels/floor-plans/")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["hotel", "floor_label"],
                name="unique_floor_plan_label_per_hotel",
            )
        ]
        ordering = ["hotel__name", "floor_label"]

    def __str__(self) -> str:
        return f"{self.hotel.name}: {self.floor_label}"


class ProjectRoomSetting(models.Model):
    project = models.ForeignKey(
        Project, related_name="room_settings", on_delete=models.CASCADE
    )
    room = models.ForeignKey(
        Room, related_name="project_settings", on_delete=models.CASCADE
    )
    local_name = models.CharField(max_length=160, blank=True)
    blocked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "room"], name="unique_room_setting_per_project"
            )
        ]
        ordering = ["room__hotel__name", "room__name"]

    @property
    def display_name(self) -> str:
        return self.local_name or self.room.name

    def __str__(self) -> str:
        return f"{self.project.name}: {self.display_name}"


class ProjectRoomCombinationSetting(models.Model):
    project = models.ForeignKey(
        Project,
        related_name="room_combination_settings",
        on_delete=models.CASCADE,
    )
    room_combination = models.ForeignKey(
        RoomCombination,
        related_name="project_settings",
        on_delete=models.CASCADE,
    )
    local_name = models.CharField(max_length=160, blank=True)
    blocked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "room_combination"],
                name="unique_room_combination_setting_per_project",
            )
        ]
        ordering = ["room_combination__hotel__name", "room_combination__name"]

    @property
    def display_name(self) -> str:
        return self.local_name or self.room_combination.name

    def __str__(self) -> str:
        return f"{self.project.name}: {self.display_name}"


class ProjectRoomAvailability(models.Model):
    setting = models.ForeignKey(
        ProjectRoomSetting,
        related_name="availability_windows",
        on_delete=models.CASCADE,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        ordering = ["starts_at"]

    def __str__(self) -> str:
        return f"{self.setting}: {self.starts_at:%Y-%m-%d %H:%M}"


class ProjectRoomCombinationAvailability(models.Model):
    setting = models.ForeignKey(
        ProjectRoomCombinationSetting,
        related_name="availability_windows",
        on_delete=models.CASCADE,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        ordering = ["starts_at"]

    def __str__(self) -> str:
        return f"{self.setting}: {self.starts_at:%Y-%m-%d %H:%M}"


class FormField(models.Model):
    subproject = models.ForeignKey(
        Subproject, related_name="form_fields", on_delete=models.CASCADE
    )
    label = models.CharField(max_length=240)
    field_type = models.CharField(max_length=80)
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subproject", "label"], name="unique_form_label_per_subproject"
            )
        ]
        ordering = ["subproject__name", "position", "label"]

    def __str__(self) -> str:
        return f"{self.subproject.name}: {self.label}"


class Application(models.Model):
    subproject = models.ForeignKey(
        Subproject, related_name="applications", on_delete=models.CASCADE
    )
    applicant = models.ForeignKey(
        "auth.User", related_name="applications", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=240)
    event_header_image = models.ImageField(
        blank=True,
        upload_to="events/header-images/",
    )
    status = models.CharField(
        max_length=32,
        choices=[(status.value, status.value) for status in ApplicationStatus],
        default=ApplicationStatus.SUBMITTED.value,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at", "title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.subproject.name})"


class ApplicationVersion(models.Model):
    application = models.ForeignKey(
        Application, related_name="versions", on_delete=models.CASCADE
    )
    version = models.PositiveIntegerField()
    answers = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "version"],
                name="unique_application_version_number",
            )
        ]
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"{self.application.title} v{self.version}"


class EventGroup(models.Model):
    project = models.ForeignKey(
        Project, related_name="event_groups", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    requires_order = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "slug"], name="unique_event_group_slug_per_project"
            )
        ]
        ordering = ["project__opens_at", "name"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.name}"


class Panel(models.Model):
    application = models.OneToOneField(
        Application, related_name="panel", on_delete=models.CASCADE
    )
    project = models.ForeignKey(
        Project, related_name="panels", on_delete=models.CASCADE
    )
    owner = models.ForeignKey(
        "auth.User", related_name="panels", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=240)
    event_group = models.ForeignKey(
        EventGroup,
        related_name="panels",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    group_order = models.PositiveIntegerField(null=True, blank=True)
    recurrence_label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__opens_at", "title"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.title}"


class TimetablePlacement(models.Model):
    panel = models.OneToOneField(
        Panel, related_name="placement", on_delete=models.CASCADE
    )
    layer = models.CharField(
        max_length=64,
        choices=[(layer.value, layer.value) for layer in TimetableLayer],
        default=TimetableLayer.PANELS.value,
    )
    room = models.ForeignKey(
        Room,
        related_name="placements",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    room_combination = models.ForeignKey(
        RoomCombination,
        related_name="placements",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "panel__title"]

    def __str__(self) -> str:
        return f"{self.panel.title}: {self.starts_at:%Y-%m-%d %H:%M}"

    @property
    def location_name(self) -> str:
        if self.room_combination_id:
            return self.room_combination.name
        if self.room_id:
            return self.room.name
        return "Unplaced"


class TimetableDay(models.Model):
    project = models.ForeignKey(
        Project, related_name="timetable_days", on_delete=models.CASCADE
    )
    service_date = models.DateField()
    label = models.CharField(max_length=120, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    grid_interval_minutes = models.PositiveSmallIntegerField(default=15)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "service_date"],
                name="unique_timetable_day_per_project",
            )
        ]
        ordering = ["starts_at", "service_date"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.display_label}"

    @property
    def display_label(self) -> str:
        return self.label or self.service_date.strftime("%a %m.%d")


class TimetableLayerSetting(models.Model):
    project = models.ForeignKey(
        Project, related_name="timetable_layer_settings", on_delete=models.CASCADE
    )
    layer = models.CharField(
        max_length=64,
        choices=[(layer.value, layer.value) for layer in TimetableLayer],
    )
    label = models.CharField(max_length=120, blank=True)
    visible = models.BooleanField(default=True)
    locked = models.BooleanField(default=False)
    opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "layer"],
                name="unique_timetable_layer_per_project",
            )
        ]
        ordering = ["position", "layer"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.display_label}"

    @property
    def display_label(self) -> str:
        return self.label or self.layer.replace("_", " ").title()


class VolunteerShift(models.Model):
    project = models.ForeignKey(
        Project, related_name="volunteer_shifts", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=200)
    role = models.CharField(max_length=120)
    needed_volunteers = models.PositiveIntegerField(default=1)
    locked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__opens_at", "title"]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.title}"

    @property
    def assignment_count(self) -> int:
        return self.assignments.exclude(status=AssignmentStatus.REMOVED.value).count()

    @property
    def open_spots(self) -> int:
        return max(self.needed_volunteers - self.assignment_count, 0)


class VolunteerShiftPlacement(models.Model):
    shift = models.OneToOneField(
        VolunteerShift, related_name="placement", on_delete=models.CASCADE
    )
    layer = models.CharField(
        max_length=64,
        choices=[(layer.value, layer.value) for layer in TimetableLayer],
        default=TimetableLayer.VOLUNTEER_SHIFTS.value,
    )
    room = models.ForeignKey(
        Room,
        related_name="volunteer_shift_placements",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    room_combination = models.ForeignKey(
        RoomCombination,
        related_name="volunteer_shift_placements",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "shift__title"]

    def __str__(self) -> str:
        return f"{self.shift.title}: {self.starts_at:%Y-%m-%d %H:%M}"

    @property
    def location_name(self) -> str:
        if self.room_combination_id:
            return self.room_combination.name
        if self.room_id:
            return self.room.name
        return "Unplaced"


class VolunteerShiftAssignment(models.Model):
    shift = models.ForeignKey(
        VolunteerShift, related_name="assignments", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        "auth.User",
        related_name="volunteer_shift_assignments",
        on_delete=models.CASCADE,
    )
    assigned_by = models.ForeignKey(
        "auth.User",
        related_name="created_volunteer_shift_assignments",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=32,
        choices=[(status.value, status.value) for status in AssignmentStatus],
        default=AssignmentStatus.CLAIMED.value,
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "user"],
                name="unique_volunteer_assignment_per_shift",
            )
        ]
        ordering = ["shift__project__opens_at", "shift__title", "user__email"]

    def __str__(self) -> str:
        return f"{self.user.email} -> {self.shift.title}"
