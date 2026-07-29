"""Event edition aggregate and lifecycle history."""

from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import (
    validate_currency_codes,
    validate_language_codes,
    validate_lowercase_slug,
    validate_time_zone,
)

ARCHIVE_AMENDMENT_LABEL_LENGTH = 60
ARCHIVE_AMENDMENT_CONTENT_LENGTH = ARCHIVE_AMENDMENT_LABEL_LENGTH - 3


class EventEdition(UUIDTimeStampedModel):
    class Lifecycle(models.TextChoices):
        DRAFT = "draft", "Draft"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        LIVE = "live", "Live"
        CLOSING = "closing", "Closing"
        ARCHIVED = "archived", "Archived"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="event_editions",
    )
    series = models.ForeignKey(
        "organizations.ConventionSeries",
        on_delete=models.PROTECT,
        related_name="event_editions",
    )
    slug = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    lifecycle = models.CharField(
        max_length=20,
        choices=Lifecycle,
        default=Lifecycle.DRAFT,
    )
    lifecycle_version = models.PositiveIntegerField(default=0, editable=False)
    time_zone = models.CharField(max_length=63, validators=[validate_time_zone])
    language_codes = ArrayField(
        models.CharField(max_length=35),
        validators=[validate_language_codes],
    )
    currency_codes = ArrayField(
        models.CharField(max_length=3),
        validators=[validate_currency_codes],
    )
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        ordering = ("starts_on", "name", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("series"),
                Lower("slug"),
                name="edition_slug_unique_within_series",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="edition_ends_on_or_after_starts_on",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.series_id and self.organization_id:
            series_organization_id = self.series.organization_id
            if series_organization_id != self.organization_id:
                raise ValidationError(
                    {"series": "The series must belong to the edition organization."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            current_lifecycle = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("lifecycle", flat=True)
                .first()
            )
            if current_lifecycle == self.Lifecycle.ARCHIVED:
                raise ValidationError(
                    "Archived editions require the correction workflow.",
                    code="archived_edition",
                )

        self.slug = self.slug.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


EDITION_LIFECYCLE_CHOICES = EventEdition.Lifecycle.choices


class EditionLifecycleTransition(UUIDTimeStampedModel):
    edition = models.ForeignKey(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="lifecycle_transitions",
    )
    from_state = models.CharField(max_length=20, choices=EventEdition.Lifecycle)
    to_state = models.CharField(max_length=20, choices=EventEdition.Lifecycle)
    actor_id = models.UUIDField()
    reason = models.TextField()

    class Meta:
        ordering = ("created_at", "id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Edition lifecycle transitions are append-only.",
                code="immutable_lifecycle_transition",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Edition lifecycle transitions are append-only.",
            code="immutable_lifecycle_transition",
        )

    def __str__(self) -> str:
        from_label = EventEdition.Lifecycle(self.from_state).label
        to_label = EventEdition.Lifecycle(self.to_state).label
        return f"{self.edition}: {from_label} → {to_label}"


class ArchiveAmendment(UUIDTimeStampedModel):
    """A visible reasoned correction without mutating archived edition facts."""

    edition = models.ForeignKey(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="archive_amendments",
    )
    actor_id = models.UUIDField()
    reason = models.TextField()
    summary = models.TextField()

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        summary = self.summary.strip()
        if len(summary) > ARCHIVE_AMENDMENT_LABEL_LENGTH:
            summary = f"{summary[:ARCHIVE_AMENDMENT_CONTENT_LENGTH]}…"
        return f"{self.edition}: {summary or 'Archive amendment'}"


class EditionReadinessGate(UUIDTimeStampedModel):
    """Accountable external/internal review evidence for pilot and closure."""

    class Code(models.TextChoices):
        PRIVACY = "privacy", "Privacy"
        FINANCE = "finance", "Finance"
        OPERATIONS = "operations", "Operations"
        SECURITY = "security", "Security"
        JURISDICTION = "jurisdiction", "Jurisdiction and safeguarding"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    edition = models.ForeignKey(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="readiness_gates",
    )
    organization_id = models.UUIDField()
    code = models.CharField(max_length=24, choices=Code)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PENDING,
    )
    evidence_reference = models.CharField(max_length=240)
    review_summary = models.CharField(max_length=500)
    reviewed_by_id = models.UUIDField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "code", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="edition_readiness_gate_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "Readiness gate scope must match the edition.",
                code="readiness_gate_scope_mismatch",
            )
        reviewed = self.status in (self.Status.APPROVED, self.Status.REJECTED)
        if reviewed != bool(self.reviewed_by_id and self.reviewed_at):
            raise ValidationError(
                "A completed gate requires reviewer evidence.",
                code="readiness_gate_review_evidence",
            )


class EditionClosureManifest(UUIDTimeStampedModel):
    """Immutable reconciliation snapshot required before archival."""

    edition = models.OneToOneField(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="closure_manifest",
    )
    organization_id = models.UUIDField()
    generated_by_id = models.UUIDField()
    generated_at = models.DateTimeField()
    counts = models.JSONField()
    manifest_digest = models.CharField(max_length=64)
    recovery_reference = models.CharField(max_length=240)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Edition closure manifests are immutable.",
                code="immutable_edition_closure_manifest",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Edition closure manifests are retained with the archive.",
            code="protected_edition_closure_manifest",
        )
