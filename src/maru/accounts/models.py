from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from maru.domain import (
    AttendeeType,
    BenefitTarget,
    FursuiterStatus,
    Pronouns,
    Role,
    TicketLevel,
    VolunteerType,
)

COUNTRY_CHOICES = [
    ("", "Choose a country"),
    ("AT", "Austria"),
    ("BE", "Belgium"),
    ("BG", "Bulgaria"),
    ("CA", "Canada"),
    ("HR", "Croatia"),
    ("CZ", "Czechia"),
    ("DK", "Denmark"),
    ("EE", "Estonia"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("GR", "Greece"),
    ("HU", "Hungary"),
    ("IE", "Ireland"),
    ("IT", "Italy"),
    ("LV", "Latvia"),
    ("LT", "Lithuania"),
    ("LU", "Luxembourg"),
    ("NL", "Netherlands"),
    ("NO", "Norway"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("RO", "Romania"),
    ("SK", "Slovakia"),
    ("SI", "Slovenia"),
    ("ES", "Spain"),
    ("SE", "Sweden"),
    ("CH", "Switzerland"),
    ("GB", "United Kingdom"),
    ("US", "United States"),
    ("OTHER", "Other"),
]

HEX_COLOR_VALIDATOR = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Use a hex color like #f0f7ff.",
)


class AccessGrant(models.Model):
    email = models.EmailField(unique=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs) -> None:
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def role_names(self) -> set[str]:
        return set(self.roles.values_list("role", flat=True))

    @property
    def can_start_project(self) -> bool:
        return bool(self.role_names & {Role.ADMIN.value, Role.BOARD.value})

    @property
    def can_review_applications(self) -> bool:
        return bool(
            self.role_names
            & {Role.ADMIN.value, Role.BOARD.value, Role.EVENT_MANAGER.value}
        )


class AccessRole(models.Model):
    grant = models.ForeignKey(
        AccessGrant, related_name="roles", on_delete=models.CASCADE
    )
    role = models.CharField(
        max_length=64, choices=[(role.value, role.value) for role in Role]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["grant", "role"], name="unique_role_per_access_grant"
            )
        ]
        ordering = ["grant__email", "role"]

    def __str__(self) -> str:
        return f"{self.grant.email}: {self.role}"


class AccessGrantAuditLog(models.Model):
    ACTION_CREATED = "created"
    ACTION_PROFILE_LOCKED = "profile_locked"
    ACTION_PROFILE_UNLOCKED = "profile_unlocked"
    ACTION_UPDATED = "updated"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_PROFILE_LOCKED, "Profile locked"),
        (ACTION_PROFILE_UNLOCKED, "Profile unlocked"),
        (ACTION_UPDATED, "Updated"),
    ]

    grant = models.ForeignKey(
        AccessGrant,
        related_name="audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="access_grant_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    actor_email = models.EmailField(blank=True)
    target_email = models.EmailField()
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} {self.target_email} by {self.actor_email or '-'}"


class RoleDefinition(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        related_name="role_definitions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    key = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    system_default = models.BooleanField(default=False)
    cloned_from = models.ForeignKey(
        "self",
        related_name="clones",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "key"],
                condition=Q(project__isnull=False),
                name="unique_project_role_definition_key",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(project__isnull=True),
                name="unique_global_role_definition_key",
            ),
        ]
        ordering = ["project__opens_at", "name"]

    def __str__(self) -> str:
        scope = self.project.name if self.project_id else "Global"
        return f"{scope}: {self.name}"


class RoleAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="role_assignments",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        "projects.Project",
        related_name="role_assignments",
        on_delete=models.CASCADE,
    )
    role_definition = models.ForeignKey(
        RoleDefinition,
        related_name="assignments",
        on_delete=models.CASCADE,
    )
    scopes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "project", "role_definition"],
                name="unique_project_role_assignment",
            )
        ]
        ordering = ["project__opens_at", "role_definition__name", "user__email"]

    def __str__(self) -> str:
        return f"{self.user.email}: {self.project.name} - {self.role_definition.name}"


class AccessBenefit(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        related_name="access_benefits",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=120)
    target = models.CharField(
        max_length=40,
        choices=[(target.value, target.value) for target in BenefitTarget],
    )
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    cloned_from = models.ForeignKey(
        "self",
        related_name="clones",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "key"],
                condition=Q(project__isnull=False),
                name="unique_project_access_benefit_key",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(project__isnull=True),
                name="unique_global_access_benefit_key",
            ),
        ]
        ordering = ["project__opens_at", "label"]

    def __str__(self) -> str:
        scope = self.project.name if self.project_id else "Global"
        return f"{scope}: {self.label}"


class StatusBenefitGrant(models.Model):
    TICKET_LEVEL = "ticket_level"
    FURSUITER_STATUS = "fursuiter_status"

    STATUS_TYPE_CHOICES = [
        (TICKET_LEVEL, "Ticket level"),
        (FURSUITER_STATUS, "Fursuiter status"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        related_name="status_benefit_grants",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    status_type = models.CharField(max_length=40, choices=STATUS_TYPE_CHOICES)
    status_value = models.CharField(max_length=80)
    benefit = models.ForeignKey(
        AccessBenefit,
        related_name="status_grants",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "status_type", "status_value", "benefit"],
                condition=Q(project__isnull=False),
                name="unique_project_status_benefit_grant",
            ),
            models.UniqueConstraint(
                fields=["status_type", "status_value", "benefit"],
                condition=Q(project__isnull=True),
                name="unique_global_status_benefit_grant",
            ),
        ]
        ordering = ["project__opens_at", "status_type", "status_value"]

    def __str__(self) -> str:
        return f"{self.status_type}: {self.status_value} -> {self.benefit.label}"


class LabelOverride(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        related_name="label_overrides",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    key = models.SlugField(max_length=120)
    label = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "key"],
                condition=Q(project__isnull=False),
                name="unique_project_label_override_key",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(project__isnull=True),
                name="unique_global_label_override_key",
            ),
        ]
        ordering = ["project__opens_at", "key"]

    def __str__(self) -> str:
        scope = self.project.name if self.project_id else "Global"
        return f"{scope}: {self.key}"


class AccessConfigurationAuditLog(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        related_name="access_configuration_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="access_configuration_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    actor_email = models.EmailField(blank=True)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80)
    target_key = models.CharField(max_length=160, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        scope = self.project.name if self.project_id else "Global"
        return f"{scope}: {self.action} {self.target_type}"


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    profile_unlocked = models.BooleanField(default=False)
    display_name = models.CharField(max_length=120, blank=True)
    profile_picture = models.ImageField(
        upload_to="profiles/profile-pictures/", blank=True
    )
    fursuit_picture = models.ImageField(
        upload_to="profiles/fursuit-pictures/", blank=True
    )
    fursuit_name = models.CharField(max_length=120, blank=True)
    pronouns = models.CharField(
        max_length=40,
        blank=True,
        choices=[(pronoun.value, pronoun.value or "Not set") for pronoun in Pronouns],
    )
    telegram = models.CharField(max_length=120, blank=True)
    discord = models.CharField(max_length=120, blank=True)
    phone_number = models.CharField(max_length=80, blank=True)
    personal_email = models.EmailField(blank=True)
    convention_email = models.EmailField(blank=True)
    country = models.CharField(max_length=8, blank=True, choices=COUNTRY_CHOICES)
    postal_code = models.CharField(max_length=32, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    street_address = models.CharField(max_length=240, blank=True)
    address_extra = models.CharField(max_length=240, blank=True)
    bio = models.TextField(blank=True)
    show_profile_publicly = models.BooleanField(default=False)
    show_contact_handles = models.BooleanField(default=False)
    show_fursuit_picture = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.display_name or self.user.get_username()


class UserConventionProfile(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="convention_profiles",
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        "projects.Project",
        related_name="user_convention_profiles",
        on_delete=models.CASCADE,
    )
    attendee_type = models.CharField(
        max_length=40,
        blank=True,
        choices=[
            (attendee_type.value, attendee_type.value)
            for attendee_type in AttendeeType
        ],
    )
    ticket_level_selected = models.CharField(
        max_length=40,
        choices=[(level.value, level.value) for level in TicketLevel],
        default=TicketLevel.PENDING.value,
    )
    ticket_level_verified = models.CharField(
        max_length=40,
        blank=True,
        choices=[
            ("", "Not verified"),
            *[(level.value, level.value) for level in TicketLevel],
        ],
    )
    volunteer_type = models.CharField(
        max_length=40,
        choices=[
            (volunteer_type.value, volunteer_type.value)
            for volunteer_type in VolunteerType
        ],
        default=VolunteerType.NONE.value,
    )
    fursuit_species = models.CharField(max_length=120, blank=True)
    fursuiter_status = models.CharField(
        max_length=40,
        choices=[(status.value, status.value) for status in FursuiterStatus],
        default=FursuiterStatus.NOT_REQUESTED.value,
    )
    roles = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "project"],
                name="unique_user_convention_profile",
            )
        ]
        ordering = ["project__opens_at", "project__name", "user__email"]

    def __str__(self) -> str:
        return f"{self.user.email}: {self.project.name}"

    @property
    def role_labels(self) -> list[str]:
        return list(self.roles or [])


class UserTileColorRule(models.Model):
    ATTENDEE_TYPE = "attendee_type"
    VOLUNTEER_TYPE = "volunteer_type"
    EDGE = "edge"
    INTERIOR = "interior"

    TARGET_CHOICES = [
        (ATTENDEE_TYPE, "Attendee type"),
        (VOLUNTEER_TYPE, "Volunteer type"),
    ]
    APPLIES_TO_CHOICES = [
        (EDGE, "Tile edge"),
        (INTERIOR, "Tile interior"),
    ]

    target_type = models.CharField(max_length=32, choices=TARGET_CHOICES)
    target_value = models.CharField(max_length=80)
    applies_to = models.CharField(
        max_length=24,
        choices=APPLIES_TO_CHOICES,
        default=INTERIOR,
    )
    background_color = models.CharField(
        max_length=7,
        default="#f4f7fb",
        validators=[HEX_COLOR_VALIDATOR],
    )
    text_color = models.CharField(
        max_length=7,
        default="#1f2937",
        validators=[HEX_COLOR_VALIDATOR],
    )
    priority = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_value", "applies_to"],
                name="unique_user_tile_color_target",
            )
        ]
        ordering = ["-priority", "target_type", "target_value", "applies_to"]

    def __str__(self) -> str:
        return f"{self.get_target_type_display()}: {self.target_value}"


class ArchivedParticipation(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    project_name = models.CharField(max_length=160)
    panel_title = models.CharField(max_length=200)
    year = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "project_name", "panel_title"]

    def __str__(self) -> str:
        return f"{self.year} {self.project_name}: {self.panel_title}"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="notifications", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    link_url = models.CharField(max_length=255, blank=True)
    link_label = models.CharField(max_length=80, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user}: {self.title}"
