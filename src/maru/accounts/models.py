from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from maru.domain import Role


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
    telegram = models.CharField(max_length=120, blank=True)
    discord = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    show_profile_publicly = models.BooleanField(default=False)
    show_contact_handles = models.BooleanField(default=False)
    show_fursuit_picture = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.display_name or self.user.get_username()


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
