from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from maru.accounts.models import AccessGrant
from maru.domain import AssignmentStatus, ExportType, FormStatus
from maru.projects.models import (
    EventGroup,
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

TEXTAREA_TYPES = {"long_text", "availability_grid"}
SELECT_TYPES = {"single_choice"}
MULTI_TYPES = {"multi_choice"}
BOOLEAN_TYPES = {"boolean"}
FORM_FIELD_TYPES = [
    ("short_text", "Short text"),
    ("long_text", "Long text"),
    ("single_choice", "Single choice"),
    ("multi_choice", "Multiple choice"),
    ("boolean", "Checkbox"),
    ("availability_grid", "Availability grid"),
]
EVENT_HEADER_IMAGE_HELP = (
    "Upload 16:9 artwork for hotel screens. Recommended: 1920x1080 px. "
    "Minimum: 1280x720 px. Keep any text large and centered."
)
EVENT_HEADER_IMAGE_MAX_BYTES = 8 * 1024 * 1024
EVENT_HEADER_IMAGE_MIN_WIDTH = 1280
EVENT_HEADER_IMAGE_MIN_HEIGHT = 720
EVENT_HEADER_IMAGE_MIN_RATIO = 1.6
EVENT_HEADER_IMAGE_MAX_RATIO = 1.9


class ApplicationSubmissionForm(forms.Form):
    event_header_image = forms.ImageField(
        label="Event header image",
        required=False,
        help_text=EVENT_HEADER_IMAGE_HELP,
    )

    def __init__(
        self,
        *args,
        form_fields: list[FormField],
        application=None,
        initial_answers: dict[str, str | bool | list[str]] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.application = application
        self.form_fields = form_fields
        initial_answers = initial_answers or {}
        for form_field in form_fields:
            field_name = self.field_name(form_field)
            self.fields[field_name] = self.build_field(form_field)
            if form_field.label in initial_answers:
                self.initial[field_name] = initial_answers[form_field.label]

    @staticmethod
    def field_name(form_field: FormField) -> str:
        return f"field_{form_field.pk}"

    def build_field(self, form_field: FormField):
        common = {"label": form_field.label, "required": form_field.required}
        if form_field.field_type in TEXTAREA_TYPES:
            return forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), **common)
        if form_field.field_type in SELECT_TYPES:
            return forms.ChoiceField(
                choices=[("", "Choose one"), *self.option_choices(form_field)],
                **common,
            )
        if form_field.field_type in MULTI_TYPES:
            return forms.MultipleChoiceField(
                choices=self.option_choices(form_field),
                widget=forms.CheckboxSelectMultiple,
                **common,
            )
        if form_field.field_type in BOOLEAN_TYPES:
            return forms.BooleanField(required=False, label=form_field.label)
        return forms.CharField(**common)

    @staticmethod
    def option_choices(form_field: FormField) -> list[tuple[str, str]]:
        return [(option, option) for option in form_field.options]

    def answers_by_label(self) -> dict[str, str | bool | list[str]]:
        answers = {}
        for form_field in self.form_fields:
            answers[form_field.label] = self.cleaned_data[self.field_name(form_field)]
        return answers

    def clean_event_header_image(self):
        image = self.cleaned_data.get("event_header_image")
        if not image:
            return image
        if image.size > EVENT_HEADER_IMAGE_MAX_BYTES:
            raise forms.ValidationError("Header images must be 8 MB or smaller.")

        width, height = image.image.size
        if (
            width < EVENT_HEADER_IMAGE_MIN_WIDTH
            or height < EVENT_HEADER_IMAGE_MIN_HEIGHT
        ):
            raise forms.ValidationError(
                "Header images must be at least 1280x720 px."
            )
        ratio = width / height
        if not EVENT_HEADER_IMAGE_MIN_RATIO <= ratio <= EVENT_HEADER_IMAGE_MAX_RATIO:
            raise forms.ValidationError(
                "Header images should be a 16:9 rectangle for hotel screens."
            )
        return image


class ManagedFormForm(forms.ModelForm):
    class Meta:
        model = Subproject
        fields = [
            "name",
            "slug",
            "kind",
            "form_status",
            "is_timetable_source",
            "accepts_reopen_requests",
        ]
        help_texts = {
            "is_timetable_source": (
                "Use this form to create timetable entries after approval."
            )
        }

    def __init__(self, *args, project: Project, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project

    def save(self, commit=True):
        form = super().save(commit=False)
        form.project = self.project
        if commit:
            form.save()
            self.ensure_timetable_source(form)
        return form

    def ensure_timetable_source(self, form: Subproject) -> None:
        if form.is_timetable_source:
            return
        has_source = Subproject.objects.filter(
            project=self.project,
            is_timetable_source=True,
        )
        if form.pk:
            has_source = has_source.exclude(pk=form.pk)
        if not has_source.exists():
            form.is_timetable_source = True
            form.save(update_fields=["is_timetable_source"])


class ManagedFormFieldForm(forms.ModelForm):
    options_text = forms.CharField(
        label="Options",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One option per line for choice fields.",
    )

    class Meta:
        model = FormField
        fields = ["label", "field_type", "required", "options_text", "position"]
        widgets = {
            "field_type": forms.Select(choices=FORM_FIELD_TYPES),
        }

    def __init__(self, *args, subproject: Subproject, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.subproject = subproject
        if self.instance.pk and not self.is_bound:
            self.initial["options_text"] = "\n".join(self.instance.options)

    def save(self, commit=True):
        field = super().save(commit=False)
        field.subproject = self.subproject
        field.options = [
            option.strip()
            for option in self.cleaned_data.get("options_text", "").splitlines()
            if option.strip()
        ]
        if commit:
            field.save()
        return field


class CloneManagedFormForm(forms.Form):
    source_form = forms.ModelChoiceField(queryset=Subproject.objects.none())

    def __init__(self, *args, project: Project, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["source_form"].queryset = (
            Subproject.objects.exclude(project=project)
            .select_related("project")
            .order_by("project__opens_at", "project__name", "name")
        )

    def save(self) -> Subproject:
        source = self.cleaned_data["source_form"]
        clone = Subproject.objects.create(
            project=self.project,
            name=source.name,
            slug=_unique_form_slug(self.project, source.slug),
            kind=source.kind,
            form_status=FormStatus.DRAFT.value,
            inherited_from=source,
            is_timetable_source=not Subproject.objects.filter(
                project=self.project,
                is_timetable_source=True,
            ).exists(),
            accepts_reopen_requests=source.accepts_reopen_requests,
        )
        for field in source.form_fields.all():
            FormField.objects.create(
                subproject=clone,
                label=field.label,
                field_type=field.field_type,
                required=field.required,
                options=list(field.options),
                position=field.position,
            )
        return clone


def _unique_form_slug(project: Project, source_slug: str) -> str:
    base_slug = source_slug[:100]
    candidate = base_slug
    counter = 2
    while Subproject.objects.filter(project=project, slug=candidate).exists():
        suffix = f"-{counter}"
        candidate = f"{base_slug[: 120 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


class PanelPlacementForm(forms.Form):
    location = forms.ChoiceField()
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    ends_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args, project, placement: TimetablePlacement | None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.placement = placement
        self.fields["location"].choices = self.location_choices()
        if placement and not self.is_bound:
            self.initial["location"] = self.location_value(placement)
            self.initial["starts_at"] = self.datetime_initial(placement.starts_at)
            self.initial["ends_at"] = self.datetime_initial(placement.ends_at)

    def location_choices(self):
        choices = [("", "Choose a room")]
        rooms = Room.objects.filter(hotel__projects=self.project).select_related(
            "hotel"
        )
        combinations = RoomCombination.objects.filter(
            hotel__projects=self.project
        ).select_related("hotel")
        room_settings = _room_settings_for_project(self.project)
        combination_settings = _combination_settings_for_project(self.project)
        choices.extend(
            (
                f"room:{room.pk}",
                f"{room.hotel.name} - {room_settings[room.pk].display_name}",
            )
            for room in rooms
            if not room_settings[room.pk].blocked
        )
        choices.extend(
            (
                f"combination:{combination.pk}",
                (
                    f"{combination.hotel.name} - "
                    f"{combination_settings[combination.pk].display_name}"
                ),
            )
            for combination in combinations
            if not combination_settings[combination.pk].blocked
        )
        return choices

    @staticmethod
    def location_value(placement: TimetablePlacement) -> str:
        if placement.room_id:
            return f"room:{placement.room_id}"
        if placement.room_combination_id:
            return f"combination:{placement.room_combination_id}"
        return ""

    @staticmethod
    def datetime_initial(value):
        return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "End time must be after start time.")
        if starts_at and starts_at < self.project.opens_at:
            self.add_error(
                "starts_at", "Start time must be inside project opening times."
            )
        if ends_at and ends_at > self.project.closes_at:
            self.add_error("ends_at", "End time must be inside project opening times.")
        location = cleaned.get("location")
        if location and starts_at and ends_at:
            blocker = _room_availability_blocker(
                project=self.project,
                location=location,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if blocker:
                self.add_error("location", blocker)
        return cleaned

    def save(self, panel):
        location = self.cleaned_data["location"]
        room = None
        room_combination = None
        kind, raw_pk = location.split(":", 1)
        if kind == "room":
            room = Room.objects.get(pk=raw_pk, hotel__projects=self.project)
        else:
            room_combination = RoomCombination.objects.get(
                pk=raw_pk, hotel__projects=self.project
            )
        placement, _ = TimetablePlacement.objects.update_or_create(
            panel=panel,
            defaults={
                "room": room,
                "room_combination": room_combination,
                "starts_at": self.cleaned_data["starts_at"],
                "ends_at": self.cleaned_data["ends_at"],
            },
        )
        return placement


class PanelSchedulingMetadataForm(forms.ModelForm):
    class Meta:
        model = Panel
        fields = ["event_group", "group_order", "recurrence_label"]

    def __init__(self, *args, panel: Panel, **kwargs):
        super().__init__(*args, instance=panel, **kwargs)
        self.panel = panel
        self.fields["event_group"].queryset = EventGroup.objects.filter(
            project=panel.project
        ).order_by("name")
        self.fields["event_group"].empty_label = "No group"
        self.fields["group_order"].help_text = "Required for ordered event groups."
        self.fields["recurrence_label"].help_text = "For example: Daily, Day 2 repeat."

    def clean(self):
        cleaned = super().clean()
        event_group = cleaned.get("event_group")
        group_order = cleaned.get("group_order")
        if event_group and event_group.requires_order and group_order is None:
            self.add_error(
                "group_order",
                "Ordered event groups need a group order.",
            )
        if event_group and group_order is not None:
            duplicate_exists = (
                Panel.objects.filter(
                    event_group=event_group,
                    group_order=group_order,
                )
                .exclude(pk=self.panel.pk)
                .exists()
            )
            if duplicate_exists:
                self.add_error(
                    "group_order",
                    "Another panel in this group already uses this order.",
                )
        return cleaned


class EventGroupForm(forms.ModelForm):
    class Meta:
        model = EventGroup
        fields = ["name", "slug", "description", "requires_order"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class HotelForm(forms.ModelForm):
    class Meta:
        model = Hotel
        fields = ["name"]


class ProjectHotelsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["hotels"]
        widgets = {"hotels": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hotels"].queryset = Hotel.objects.order_by("name")
        self.fields["hotels"].required = False
        self.fields["hotels"].label = "Hotels used by this project"


class RoomForm(forms.ModelForm):
    properties_text = forms.CharField(
        label="Equipment and properties",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One item per line, for example: projector, movable wall.",
    )

    class Meta:
        model = Room
        fields = ["hotel", "name", "capacity"]

    def __init__(self, *args, hotel: Hotel | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if hotel:
            self.fields["hotel"].initial = hotel
            self.fields["hotel"].widget = forms.HiddenInput()
        if self.instance.pk and not self.is_bound:
            self.initial["properties_text"] = "\n".join(self.instance.properties)

    def save(self, commit=True):
        room = super().save(commit=False)
        room.properties = [
            item.strip()
            for item in self.cleaned_data.get("properties_text", "").splitlines()
            if item.strip()
        ]
        if commit:
            room.save()
        return room


class HotelFloorPlanForm(forms.ModelForm):
    class Meta:
        model = HotelFloorPlan
        fields = ["floor_label", "image", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ProjectRoomSettingForm(forms.ModelForm):
    class Meta:
        model = ProjectRoomSetting
        fields = ["local_name", "blocked", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ProjectRoomCombinationSettingForm(forms.ModelForm):
    class Meta:
        model = ProjectRoomCombinationSetting
        fields = ["local_name", "blocked", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ProjectRoomAvailabilityForm(forms.ModelForm):
    class Meta:
        model = ProjectRoomAvailability
        fields = ["starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        _validate_project_window(self, starts_at, ends_at)
        return cleaned


class ProjectRoomCombinationAvailabilityForm(ProjectRoomAvailabilityForm):
    class Meta(ProjectRoomAvailabilityForm.Meta):
        model = ProjectRoomCombinationAvailability


class ExportTokenForm(forms.ModelForm):
    class Meta:
        model = ExportToken
        fields = ["name", "export_type", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["export_type"].choices = [
            (export_type.value, export_type.value) for export_type in ExportType
        ]


class VolunteerShiftForm(forms.ModelForm):
    class Meta:
        model = VolunteerShift
        fields = ["title", "role", "needed_volunteers", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    def clean_needed_volunteers(self) -> int:
        needed_volunteers = self.cleaned_data["needed_volunteers"]
        if needed_volunteers < 1:
            raise forms.ValidationError("At least one volunteer is required.")
        return needed_volunteers


class SignageReminderForm(forms.ModelForm):
    class Meta:
        model = SignageReminder
        fields = ["title", "body", "starts_at", "ends_at", "priority", "active"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "End time must be after start time.")
        if starts_at and starts_at < self.project.opens_at:
            self.add_error(
                "starts_at", "Start time must be inside project opening times."
            )
        if ends_at and ends_at > self.project.closes_at:
            self.add_error("ends_at", "End time must be inside project opening times.")
        return cleaned


class VolunteerShiftAssignmentForm(forms.ModelForm):
    class Meta:
        model = VolunteerShiftAssignment
        fields = ["user", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, shift: VolunteerShift, **kwargs):
        super().__init__(*args, **kwargs)
        self.shift = shift
        active_emails = AccessGrant.objects.filter(active=True).values_list(
            "email", flat=True
        )
        assigned_user_ids = (
            shift.assignments.exclude(status=AssignmentStatus.REMOVED.value)
            .values_list("user_id", flat=True)
        )
        users = (
            get_user_model()
            .objects.filter(email__in=active_emails)
            .exclude(id__in=assigned_user_ids)
            .order_by("email")
        )
        self.fields["user"].queryset = users
        self.fields["user"].label = "Volunteer"
        self.fields["user"].empty_label = "Choose a registered user"


class VolunteerShiftPlacementForm(PanelPlacementForm):
    def __init__(
        self, *args, project, placement: VolunteerShiftPlacement | None, **kwargs
    ):
        super().__init__(*args, project=project, placement=placement, **kwargs)

    @staticmethod
    def location_value(placement: VolunteerShiftPlacement) -> str:
        if placement.room_id:
            return f"room:{placement.room_id}"
        if placement.room_combination_id:
            return f"combination:{placement.room_combination_id}"
        return ""

    def save(self, shift):
        location = self.cleaned_data["location"]
        room = None
        room_combination = None
        kind, raw_pk = location.split(":", 1)
        if kind == "room":
            room = Room.objects.get(pk=raw_pk, hotel__projects=self.project)
        else:
            room_combination = RoomCombination.objects.get(
                pk=raw_pk, hotel__projects=self.project
            )
        placement, _ = VolunteerShiftPlacement.objects.update_or_create(
            shift=shift,
            defaults={
                "room": room,
                "room_combination": room_combination,
                "starts_at": self.cleaned_data["starts_at"],
                "ends_at": self.cleaned_data["ends_at"],
            },
        )
        return placement


def _room_settings_for_project(project) -> dict[int, ProjectRoomSetting]:
    rooms = Room.objects.filter(hotel__projects=project)
    settings = {
        setting.room_id: setting
        for setting in ProjectRoomSetting.objects.filter(
            project=project,
            room__in=rooms,
        ).select_related("room")
    }
    for room in rooms:
        if room.pk not in settings:
            settings[room.pk] = ProjectRoomSetting.objects.create(
                project=project,
                room=room,
            )
    return settings


def _combination_settings_for_project(
    project,
) -> dict[int, ProjectRoomCombinationSetting]:
    combinations = RoomCombination.objects.filter(hotel__projects=project)
    settings = {
        setting.room_combination_id: setting
        for setting in ProjectRoomCombinationSetting.objects.filter(
            project=project,
            room_combination__in=combinations,
        ).select_related("room_combination")
    }
    for combination in combinations:
        if combination.pk not in settings:
            settings[combination.pk] = ProjectRoomCombinationSetting.objects.create(
                project=project,
                room_combination=combination,
            )
    return settings


def _room_availability_blocker(*, project, location: str, starts_at, ends_at) -> str:
    kind, raw_pk = location.split(":", 1)
    if kind == "room":
        setting = ProjectRoomSetting.objects.get(
            project=project,
            room_id=raw_pk,
        )
    else:
        setting = ProjectRoomCombinationSetting.objects.get(
            project=project,
            room_combination_id=raw_pk,
        )
    if setting.blocked:
        return "This room is blocked for this project."

    windows = list(setting.availability_windows.all())
    if not windows:
        return ""
    if any(
        window.starts_at <= starts_at and ends_at <= window.ends_at
        for window in windows
    ):
        return ""
    return "This room is not open for the selected time."


def _validate_project_window(form, starts_at, ends_at) -> None:
    if starts_at and ends_at and ends_at <= starts_at:
        form.add_error("ends_at", "End time must be after start time.")
    if starts_at and starts_at < form.project.opens_at:
        form.add_error("starts_at", "Start time must be inside project opening times.")
    if ends_at and ends_at > form.project.closes_at:
        form.add_error("ends_at", "End time must be inside project opening times.")
