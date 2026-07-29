"""Edition participation and durable capacity snapshots."""

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel

CAPACITY_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def validate_capacity_code(value: str) -> None:
    if not CAPACITY_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable lowercase capacity code.",
            code="invalid_capacity_code",
        )


class Participation(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        INTERESTED = "interested", "Interested"
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="event_participations",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="participations",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="participations",
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.INTERESTED,
    )
    edition_name_snapshot = models.CharField(max_length=160)
    series_name_snapshot = models.CharField(max_length=160)
    public_history_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ("edition__starts_on", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "edition"),
                name="one_participation_per_account_and_edition",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.edition_id
            and self.organization_id
            and self.edition.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"edition": "The edition must belong to the organization."}
            )
        if self.edition_id:
            current_lifecycle = (
                type(self.edition)
                .objects.filter(pk=self.edition_id)
                .values_list("lifecycle", flat=True)
                .first()
            )
            if current_lifecycle == "archived":
                raise ValidationError(
                    "Archived participation requires the correction workflow.",
                    code="archived_edition",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.edition_id:
            if not self.edition_name_snapshot:
                self.edition_name_snapshot = self.edition.name
            if not self.series_name_snapshot:
                self.series_name_snapshot = self.edition.series.name
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.account} — {self.edition_name_snapshot}"


class ParticipationCapacity(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        WITHDRAWN = "withdrawn", "Withdrawn"

    participation = models.ForeignKey(
        Participation,
        on_delete=models.PROTECT,
        related_name="capacities",
    )
    code = models.CharField(max_length=80, validators=[validate_capacity_code])
    label_snapshot = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.PROPOSED,
    )
    contribution_summary = models.CharField(max_length=240, blank=True)
    public_history_visible = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "participation capacities"
        ordering = ("participation_id", "code", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("participation", "code"),
                name="one_capacity_code_per_participation",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.participation_id:
            current_lifecycle = (
                Participation.objects.filter(pk=self.participation_id)
                .values_list("edition__lifecycle", flat=True)
                .first()
            )
            if current_lifecycle == "archived":
                raise ValidationError(
                    "Archived participation requires the correction workflow.",
                    code="archived_edition",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.label_snapshot} — {self.participation}"
