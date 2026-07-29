from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from maru.accounts.access_config import (
    DEFAULT_LABELS,
    clean_permission_values,
    fursuiter_status_choices,
    permission_choices,
    ticket_level_choices,
)
from maru.accounts.auth import is_google_email, normalize_email
from maru.accounts.models import (
    AccessBenefit,
    AccessGrant,
    LabelOverride,
    RoleAssignment,
    RoleDefinition,
    StatusBenefitGrant,
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
    VolunteerGroup,
    VolunteerMembership,
)
from maru.accounts.permissions import can_set_verified_ticket_level, normalize_label_key
from maru.domain import AttendeeType, FursuiterStatus, Role, TicketLevel, VolunteerType


class AccessGrantForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=[(role.value, role.value) for role in Role],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AccessGrant
        fields = ["email", "active", "roles", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = sorted(self.instance.role_names)

    def clean_email(self) -> str:
        email = normalize_email(self.cleaned_data["email"])
        if not is_google_email(email):
            raise forms.ValidationError("Use a Gmail or Googlemail address.")
        return email


class AccessGrantImportForm(forms.Form):
    csv_file = forms.FileField(label="CSV file")


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "display_name",
            "profile_picture",
            "fursuit_picture",
            "fursuit_name",
            "pronouns",
            "telegram",
            "discord",
            "phone_number",
            "personal_email",
            "convention_email",
            "country",
            "postal_code",
            "city",
            "region",
            "street_address",
            "address_extra",
            "bio",
            "show_profile_publicly",
            "show_contact_handles",
            "show_fursuit_picture",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
        }


class UserConventionProfileForm(forms.Form):
    attendee_type = forms.ChoiceField(
        choices=[("", "Not set"), *[(item.value, item.value) for item in AttendeeType]],
        required=False,
    )
    ticket_level_selected = forms.ChoiceField(
        choices=ticket_level_choices(),
        required=False,
    )
    ticket_level_verified = forms.ChoiceField(
        choices=ticket_level_choices(include_blank=True),
        required=False,
    )
    volunteer_type = forms.ChoiceField(
        choices=[(item.value, item.value) for item in VolunteerType],
        required=False,
    )
    fursuit_species = forms.CharField(max_length=120, required=False)
    fursuiter_status = forms.ChoiceField(
        choices=fursuiter_status_choices(),
        required=False,
    )
    roles = forms.MultipleChoiceField(
        choices=[(role.value, role.value) for role in Role],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(
        self,
        *args,
        allow_role_edit: bool,
        allow_status_edit: bool = False,
        allow_fursuiter_validation: bool = False,
        actor=None,
        instance: UserConventionProfile | None,
        project,
        user,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.allow_fursuiter_validation = allow_fursuiter_validation
        self.allow_role_edit = allow_role_edit
        self.allow_status_edit = allow_status_edit
        self.instance = instance
        self.project = project
        self.user = user
        self.fields["attendee_type"].label = project.name
        if instance and not self.is_bound:
            self.initial["attendee_type"] = instance.attendee_type
            self.initial["fursuit_species"] = instance.fursuit_species
            self.initial["fursuiter_status"] = instance.fursuiter_status
            self.initial["ticket_level_selected"] = instance.ticket_level_selected
            self.initial["ticket_level_verified"] = instance.ticket_level_verified
            self.initial["volunteer_type"] = instance.volunteer_type
            self.initial["roles"] = instance.role_labels
        if not allow_status_edit:
            self.fields["ticket_level_verified"].disabled = True
            self.fields["ticket_level_verified"].help_text = (
                "Verified ticket level is assigned after payment verification."
            )
        if not allow_fursuiter_validation:
            self.fields["fursuiter_status"].disabled = True
            self.fields["fursuiter_status"].help_text = (
                "Fursuiter status is validated by Fursuit Support."
            )
        if not allow_role_edit:
            self.fields["volunteer_type"].disabled = True
            self.fields["volunteer_type"].help_text = (
                "Volunteer type is assigned by admins."
            )
            self.fields["roles"].disabled = True
            self.fields["roles"].help_text = "Convention roles are assigned by admins."

    @property
    def has_profile_data(self) -> bool:
        if not self.is_bound:
            return bool(
                self.initial.get("attendee_type")
                or self.initial.get("fursuit_species")
                or self.initial.get("roles")
                or self.initial.get("ticket_level_selected")
                != TicketLevel.PENDING.value
                or self.initial.get("ticket_level_verified")
                or self.initial.get("volunteer_type")
                not in {"", VolunteerType.NONE.value}
                or self.initial.get("fursuiter_status")
                not in {"", FursuiterStatus.NOT_REQUESTED.value}
            )
        return bool(
            self.cleaned_data.get("attendee_type")
            or self.cleaned_data.get("fursuit_species")
            or self.cleaned_data.get("roles")
            or self.cleaned_data.get("ticket_level_selected")
            != TicketLevel.PENDING.value
            or self.cleaned_data.get("ticket_level_verified")
            or self.cleaned_data.get("volunteer_type") != VolunteerType.NONE.value
            or self.cleaned_data.get("fursuiter_status")
            != FursuiterStatus.NOT_REQUESTED.value
            or self.instance
        )

    def clean_ticket_level_verified(self) -> str:
        level = self.cleaned_data.get("ticket_level_verified", "")
        current_level = self.instance.ticket_level_verified if self.instance else ""
        if self.allow_status_edit and not can_set_verified_ticket_level(
            actor=self.actor,
            current_level=current_level,
            new_level=level,
        ):
            raise forms.ValidationError(
                "Verified ticket levels can only move upward unless changed by Admin."
            )
        return level

    def save(self) -> UserConventionProfile | None:
        if not self.has_profile_data:
            return None
        convention_profile = self.instance or UserConventionProfile(
            user=self.user,
            project=self.project,
        )
        convention_profile.attendee_type = self.cleaned_data.get("attendee_type", "")
        convention_profile.fursuit_species = self.cleaned_data.get(
            "fursuit_species",
            "",
        )
        convention_profile.ticket_level_selected = self.cleaned_data.get(
            "ticket_level_selected",
            TicketLevel.PENDING.value,
        )
        if self.allow_status_edit:
            convention_profile.ticket_level_verified = self.cleaned_data.get(
                "ticket_level_verified",
                "",
            )
        if self.allow_fursuiter_validation:
            convention_profile.fursuiter_status = self.cleaned_data.get(
                "fursuiter_status",
                FursuiterStatus.NOT_REQUESTED.value,
            )
        elif (
            convention_profile.fursuit_species
            and convention_profile.fursuiter_status
            == FursuiterStatus.NOT_REQUESTED.value
        ):
            convention_profile.fursuiter_status = FursuiterStatus.PENDING.value
        if self.allow_role_edit:
            convention_profile.volunteer_type = self.cleaned_data.get(
                "volunteer_type",
                VolunteerType.NONE.value,
            )
            convention_profile.roles = list(self.cleaned_data.get("roles", []))
        convention_profile.save()
        return convention_profile


class VolunteerGroupForm(forms.ModelForm):
    class Meta:
        model = VolunteerGroup
        fields = ["title", "slug", "description", "parents"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "parents": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        parents = VolunteerGroup.objects.order_by("title")
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parents"].queryset = parents
        self.fields["parents"].required = False

    def clean_parents(self):
        parents = self.cleaned_data["parents"]
        if not self.instance.pk:
            return parents
        descendant_ids = _volunteer_group_descendant_ids(self.instance)
        invalid_parents = [
            parent.title for parent in parents if parent.pk in descendant_ids
        ]
        if invalid_parents:
            raise forms.ValidationError(
                "A child group cannot also be assigned as a parent."
            )
        return parents


class VolunteerMembershipForm(forms.ModelForm):
    class Meta:
        model = VolunteerMembership
        fields = ["user", "role", "custom_title", "responsibilities"]
        labels = {
            "custom_title": "Custom title",
            "role": "Level",
            "responsibilities": "Responsibilities",
        }
        widgets = {
            "responsibilities": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = get_user_model().objects.order_by("email")
        self.fields["custom_title"].required = False
        self.fields["responsibilities"].required = False


class RoleDefinitionForm(forms.ModelForm):
    permissions = forms.MultipleChoiceField(
        choices=permission_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = RoleDefinition
        fields = ["key", "name", "description", "permissions", "active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        if self.instance.pk and not self.is_bound:
            self.initial["permissions"] = self.instance.permissions

    def save(self, commit=True):
        role = super().save(commit=False)
        role.project = self.project
        role.permissions = clean_permission_values(
            self.cleaned_data.get("permissions", []),
        )
        if commit:
            role.save()
        return role


class RoleAssignmentForm(forms.ModelForm):
    user = forms.ModelChoiceField(queryset=get_user_model().objects.none())

    class Meta:
        model = RoleAssignment
        fields = ["user", "role_definition", "scopes"]
        widgets = {"scopes": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "scopes": (
                "Optional JSON-style notes for department, forms, room groups, "
                "or other local scope names."
            )
        }

    def __init__(self, *args, project, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["role_definition"].queryset = RoleDefinition.objects.filter(
            project=project,
            active=True,
        )
        self.fields["user"].queryset = get_user_model().objects.order_by("email")

    def clean_scopes(self):
        return self.cleaned_data.get("scopes") or []

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.project = self.project
        if commit:
            assignment.save()
        return assignment


class CloneAccessConfigurationForm(forms.Form):
    source_project = forms.ModelChoiceField(
        queryset=None,
        required=False,
        help_text="Leave empty to clone global defaults.",
    )

    def __init__(self, *args, project=None, **kwargs) -> None:
        from maru.projects.models import Project

        super().__init__(*args, **kwargs)
        queryset = Project.objects.order_by("opens_at", "name")
        if project:
            queryset = queryset.exclude(pk=project.pk)
        self.fields["source_project"].queryset = queryset


class AccessBenefitForm(forms.ModelForm):
    class Meta:
        model = AccessBenefit
        fields = ["key", "label", "target", "description", "active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project

    def save(self, commit=True):
        benefit = super().save(commit=False)
        benefit.project = self.project
        if commit:
            benefit.save()
        return benefit


class StatusBenefitGrantForm(forms.ModelForm):
    status_value = forms.ChoiceField()

    class Meta:
        model = StatusBenefitGrant
        fields = ["status_type", "status_value", "benefit"]

    def __init__(self, *args, project=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["benefit"].queryset = AccessBenefit.objects.filter(project=project)
        self.fields["status_value"].choices = [
            *((level.value, level.value) for level in TicketLevel),
            *(
                (status.value, status.value)
                for status in FursuiterStatus
                if status != FursuiterStatus.NOT_REQUESTED
            ),
        ]

    def save(self, commit=True):
        grant = super().save(commit=False)
        grant.project = self.project
        if commit:
            grant.save()
        return grant


class LabelOverrideForm(forms.ModelForm):
    key = forms.ChoiceField()

    class Meta:
        model = LabelOverride
        fields = ["key", "label"]

    def __init__(self, *args, project=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["key"].choices = [
            (normalize_label_key(key), key) for key in sorted(DEFAULT_LABELS)
        ]

    def save(self, commit=True):
        label = super().save(commit=False)
        label.project = self.project
        if commit:
            label.save()
        return label


class UserTileColorRuleForm(forms.ModelForm):
    target = forms.ChoiceField()

    class Meta:
        model = UserTileColorRule
        fields = [
            "target",
            "applies_to",
            "background_color",
            "priority",
            "active",
        ]
        widgets = {
            "background_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, project=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["target"].choices = _user_tile_target_choices()
        self.fields["background_color"].label = "Color"
        self.fields["background_color"].help_text = (
            "Pick the color, then choose whether it changes the edge or interior."
        )
        if self.instance.pk:
            self.initial["target"] = (
                f"{self.instance.target_type}:{self.instance.target_value}"
            )

    def clean_target(self) -> str:
        target = self.cleaned_data["target"]
        target_type, target_value = target.split(":", 1)
        if target_type not in {
            UserTileColorRule.ATTENDEE_TYPE,
            UserTileColorRule.VOLUNTEER_TYPE,
        }:
            raise forms.ValidationError("Choose a valid target.")
        return target

    def clean(self):
        cleaned_data = super().clean()
        target = cleaned_data.get("target")
        applies_to = cleaned_data.get("applies_to")
        if not target or not applies_to:
            return cleaned_data
        target_type, target_value = target.split(":", 1)
        duplicate = UserTileColorRule.objects.filter(
            applies_to=applies_to,
            project=self.project,
            target_type=target_type,
            target_value=target_value,
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            self.add_error(
                "target",
                "A color rule already exists for this target and tile area.",
            )
        return cleaned_data

    def save(self, commit=True):
        target_type, target_value = self.cleaned_data["target"].split(":", 1)
        rule = super().save(commit=False)
        rule.project = self.project
        rule.target_type = target_type
        rule.target_value = target_value
        if commit:
            rule.save()
        return rule


def _user_tile_target_choices() -> list[tuple[str, str]]:
    attendee_choices = [
        (
            f"{UserTileColorRule.ATTENDEE_TYPE}:{attendee_type.value}",
            f"Attendee type: {attendee_type.value}",
        )
        for attendee_type in AttendeeType
    ]
    role_choices = [
        (
            f"{UserTileColorRule.VOLUNTEER_TYPE}:{volunteer_type.value}",
            f"Volunteer type: {volunteer_type.value}",
        )
        for volunteer_type in VolunteerType
    ]
    return [*attendee_choices, *role_choices]


def _volunteer_group_descendant_ids(group: VolunteerGroup) -> set[int]:
    descendants: set[int] = set()
    stack = list(group.children.all())
    while stack:
        child = stack.pop()
        if child.pk in descendants:
            continue
        descendants.add(child.pk)
        stack.extend(child.children.all())
    return descendants
