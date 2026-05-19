from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from maru.accounts.models import AccessGrant
from maru.domain import AssignmentStatus
from maru.projects.models import (
    EventGroup,
    FormField,
    Panel,
    Room,
    RoomCombination,
    SignageReminder,
    TimetablePlacement,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
)

TEXTAREA_TYPES = {"long_text", "availability_grid"}
SELECT_TYPES = {"single_choice"}
MULTI_TYPES = {"multi_choice"}
BOOLEAN_TYPES = {"boolean"}


class ApplicationSubmissionForm(forms.Form):
    def __init__(
        self,
        *args,
        form_fields: list[FormField],
        initial_answers: dict[str, str | bool | list[str]] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
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
        rooms = Room.objects.filter(hotel__project=self.project).select_related("hotel")
        combinations = RoomCombination.objects.filter(
            hotel__project=self.project
        ).select_related("hotel")
        choices.extend(
            (f"room:{room.pk}", f"{room.hotel.name} - {room.name}")
            for room in rooms
        )
        choices.extend(
            (
                f"combination:{combination.pk}",
                f"{combination.hotel.name} - {combination.name}",
            )
            for combination in combinations
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
        return cleaned

    def save(self, panel):
        location = self.cleaned_data["location"]
        room = None
        room_combination = None
        kind, raw_pk = location.split(":", 1)
        if kind == "room":
            room = Room.objects.get(pk=raw_pk, hotel__project=self.project)
        else:
            room_combination = RoomCombination.objects.get(
                pk=raw_pk, hotel__project=self.project
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
            room = Room.objects.get(pk=raw_pk, hotel__project=self.project)
        else:
            room_combination = RoomCombination.objects.get(
                pk=raw_pk, hotel__project=self.project
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
