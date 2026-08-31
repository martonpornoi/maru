"""Event edition aggregate and lifecycle history."""

from datetime import timedelta
from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import (
    validate_currency_codes,
    validate_language_codes,
    validate_lowercase_slug,
    validate_time_zone,
)
from maru.events.adoption import (
    DEFAULT_ADOPTION_PROFILE_VERSION,
    PERSISTED_ADOPTION_PROFILE_CHOICES,
    WORKFORCE_ONLY_PROFILE_VERSION,
    AdoptionProfileCode,
    adoption_profile,
)
from maru.events.adoption_persistence import PERSISTED_ADOPTION_PROFILE_KEYS

ARCHIVE_AMENDMENT_LABEL_LENGTH = 60
ARCHIVE_AMENDMENT_CONTENT_LENGTH = ARCHIVE_AMENDMENT_LABEL_LENGTH - 3
MAX_EDITION_SPAN_DAYS = 31


def _supported_adoption_profile_condition() -> models.Q:
    """Build the database guard from its independent exact-pair catalog.

    Returns
    -------
    models.Q
        Disjunction admitting each independently declared exact pair.
    """
    conditions = tuple(
        models.Q(
            adoption_profile_code=profile_code,
            adoption_profile_version=profile_version,
        )
        for profile_code, profile_version in PERSISTED_ADOPTION_PROFILE_KEYS
    )
    condition = conditions[0]
    for alternative in conditions[1:]:
        condition |= alternative
    return condition


class EventEdition(UUIDTimeStampedModel):
    """Store event edition records."""

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

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
    aggregate_version = models.PositiveIntegerField(default=1, editable=False)
    adoption_profile_code = models.CharField(
        max_length=40,
        choices=PERSISTED_ADOPTION_PROFILE_CHOICES,
        default=AdoptionProfileCode.FULL_CONVENTION,
        db_default=AdoptionProfileCode.FULL_CONVENTION,
        editable=False,
    )
    adoption_profile_version = models.PositiveIntegerField(
        default=DEFAULT_ADOPTION_PROFILE_VERSION,
        db_default=DEFAULT_ADOPTION_PROFILE_VERSION,
        editable=False,
    )
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
        """Configure Django's declarative class metadata."""

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
            models.CheckConstraint(
                condition=models.Q(
                    ends_on__lte=(
                        models.F("starts_on") + timedelta(days=MAX_EDITION_SPAN_DAYS)
                    )
                ),
                name="edition_span_no_more_than_31_days",
            ),
            models.CheckConstraint(
                condition=_supported_adoption_profile_condition(),
                name="edition_adoption_profile_supported",
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
        profile = adoption_profile(
            self.adoption_profile_code,
            self.adoption_profile_version,
        )
        if profile is None:
            raise ValidationError(
                {
                    "adoption_profile_code": (
                        "Choose a supported, versioned adoption profile."
                    )
                },
                code="edition_adoption_profile_unsupported",
            )
        if self.series_id and self.organization_id:
            series_organization_id = self.series.organization_id
            if series_organization_id != self.organization_id:
                raise ValidationError(
                    {"series": "The series must belong to the edition organization."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            current = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(
                    "lifecycle",
                    "adoption_profile_code",
                    "adoption_profile_version",
                )
                .first()
            )
            if current is not None and current["lifecycle"] == self.Lifecycle.ARCHIVED:
                raise ValidationError(
                    "Archived editions require the correction workflow.",
                    code="archived_edition",
                )
            if current is not None and (
                current["adoption_profile_code"] != self.adoption_profile_code
                or current["adoption_profile_version"] != self.adoption_profile_version
            ):
                raise ValidationError(
                    "An edition adoption profile is immutable after creation.",
                    code="edition_adoption_profile_immutable",
                )

        self.slug = self.slug.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable EventEdition label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return self.name


class EditionCreationReceipt(UUIDTimeStampedModel):
    """Immutable idempotency evidence for one edition-creation command."""

    edition = models.OneToOneField(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="creation_receipt",
    )
    organization_id = models.UUIDField()
    series_id = models.UUIDField()
    actor_id = models.UUIDField()
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="Use a lowercase SHA-256 digest.",
                code="invalid_edition_creation_digest",
            ),
        ),
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor_id", "series_id", "idempotency_key"),
                name="edition_creation_receipt_unique",
            ),
        ]

    def clean(self) -> None:
        """Validate the receipt's exact organization and series scope.

        Raises
        ------
        ValidationError
            If the receipt does not match its edition.
        """
        super().clean()
        if self.edition_id:
            if self.edition.organization_id != self.organization_id:
                raise ValidationError(
                    "Edition creation receipt organization does not match.",
                    code="edition_creation_receipt_organization_mismatch",
                )
            if self.edition.series_id != self.series_id:
                raise ValidationError(
                    "Edition creation receipt series does not match.",
                    code="edition_creation_receipt_series_mismatch",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the immutable receipt.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If an existing receipt is mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Edition creation receipts are immutable.",
                code="immutable_edition_creation_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of retained edition-creation evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's deletion result, which is never reached.

        Raises
        ------
        ValidationError
            Always, because creation evidence is retained.
        """
        _ = args, kwargs
        raise ValidationError(
            "Edition creation receipts are retained with the edition.",
            code="protected_edition_creation_receipt",
        )


class WorkforceAdoptionSetupReceipt(UUIDTimeStampedModel):
    """Immutable idempotency evidence for guided Workforce setup."""

    class Mode(models.TextChoices):
        """Enumerate supported guided setup foundation choices."""

        NEW_FOUNDATION = "new_foundation", "Create organization, series, and edition"
        EXISTING_ORGANIZATION = (
            "existing_organization",
            "Add a series and edition to an organization",
        )
        EXISTING_SERIES = "existing_series", "Add an edition to a series"

    edition = models.ForeignKey(
        EventEdition,
        on_delete=models.PROTECT,
        related_name="workforce_adoption_setup_receipts",
    )
    organization_id = models.UUIDField()
    series_id = models.UUIDField()
    actor_id = models.UUIDField()
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="Use a lowercase SHA-256 digest.",
                code="invalid_workforce_adoption_setup_digest",
            ),
        ),
    )
    mode = models.CharField(max_length=40, choices=Mode)
    representation_code = models.CharField(max_length=40)
    created_organization = models.BooleanField()
    created_series = models.BooleanField()
    created_edition = models.BooleanField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor_id", "idempotency_key"),
                name="workforce_setup_actor_idempotency_unique",
            ),
        ]

    def clean(self) -> None:
        """Validate the retained setup scope and adopted profile.

        Raises
        ------
        ValidationError
            If the receipt does not match its exact Workforce edition.
        """
        super().clean()
        if not self.edition_id:
            return
        if self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "Workforce setup receipt organization does not match.",
                code="workforce_setup_receipt_organization_mismatch",
            )
        if self.edition.series_id != self.series_id:
            raise ValidationError(
                "Workforce setup receipt series does not match.",
                code="workforce_setup_receipt_series_mismatch",
            )
        profile = adoption_profile(
            self.edition.adoption_profile_code,
            self.edition.adoption_profile_version,
        )
        if profile is None or profile.key != (
            AdoptionProfileCode.WORKFORCE_ONLY.value,
            WORKFORCE_ONLY_PROFILE_VERSION,
        ):
            raise ValidationError(
                "Guided Workforce setup must resolve to a Workforce-only edition.",
                code="workforce_setup_receipt_profile_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the immutable setup receipt.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If an existing receipt is mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Workforce adoption setup receipts are immutable.",
                code="immutable_workforce_adoption_setup_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of retained guided-setup evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's deletion result, which is never reached.

        Raises
        ------
        ValidationError
            Always, because setup evidence is retained.
        """
        _ = args, kwargs
        raise ValidationError(
            "Workforce adoption setup receipts are retained.",
            code="protected_workforce_adoption_setup_receipt",
        )


EDITION_LIFECYCLE_CHOICES = EventEdition.Lifecycle.choices


class EditionLifecycleTransition(UUIDTimeStampedModel):
    """Store edition lifecycle transition records."""

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
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError(
                "Edition lifecycle transitions are append-only.",
                code="immutable_lifecycle_transition",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        _ = args, kwargs
        raise ValidationError(
            "Edition lifecycle transitions are append-only.",
            code="immutable_lifecycle_transition",
        )

    def __str__(self) -> str:
        """Return the human-readable EditionLifecycleTransition label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
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
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")

    def __str__(self) -> str:
        """Return the human-readable ArchiveAmendment label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        summary = self.summary.strip()
        if len(summary) > ARCHIVE_AMENDMENT_LABEL_LENGTH:
            summary = f"{summary[:ARCHIVE_AMENDMENT_CONTENT_LENGTH]}…"
        return f"{self.edition}: {summary or 'Archive amendment'}"


class EditionReadinessGate(UUIDTimeStampedModel):
    """Accountable external/internal review evidence for pilot and closure."""

    class Code(models.TextChoices):
        """Enumerate supported code values."""

        PRIVACY = "privacy", "Privacy"
        FINANCE = "finance", "Finance"
        OPERATIONS = "operations", "Operations"
        SECURITY = "security", "Security"
        JURISDICTION = "jurisdiction", "Jurisdiction and safeguarding"

    class Status(models.TextChoices):
        """Enumerate supported status values."""

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
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "code", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="edition_readiness_gate_unique",
            )
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
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
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError(
                "Edition closure manifests are immutable.",
                code="immutable_edition_closure_manifest",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        _ = args, kwargs
        raise ValidationError(
            "Edition closure manifests are retained with the archive.",
            code="protected_edition_closure_manifest",
        )
