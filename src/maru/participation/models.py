"""Edition participation and durable capacity snapshots."""

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel
from maru.identity.policies import validate_convention_subject

CAPACITY_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def validate_capacity_code(value: str) -> None:
    """Validate capacity code.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not CAPACITY_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable lowercase capacity code.",
            code="invalid_capacity_code",
        )


class Participation(UUIDTimeStampedModel):
    """Store participation records."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

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
        """Configure Django's declarative class metadata."""

        ordering = ("edition__starts_on", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "edition"),
                name="one_participation_per_account_and_edition",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)
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
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        if self.edition_id:
            if not self.edition_name_snapshot:
                self.edition_name_snapshot = self.edition.name
            if not self.series_name_snapshot:
                self.series_name_snapshot = self.edition.series.name
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable Participation label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.account} — {self.edition_name_snapshot}"


class ParticipationCapacity(UUIDTimeStampedModel):
    """Store participation capacity records."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

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
        """Configure Django's declarative class metadata."""

        verbose_name_plural = "participation capacities"
        ordering = ("participation_id", "code", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("participation", "code"),
                name="one_capacity_code_per_participation",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
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
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable ParticipationCapacity label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.label_snapshot} — {self.participation}"
