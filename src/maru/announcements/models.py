"""Owned immutable text, independent decisions and reported external facts."""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel

from .catalog import MAX_BODY, MAX_HEADLINE, MAX_NOTE, OPERATIONS, STATUSES
from .writer_boundary import require_announcement_writer


class _Owned(UUIDTimeStampedModel):
    """All domain rows retain exact organization and event ownership."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="announcements_%(class)s",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="announcements_%(class)s",
    )

    class Meta:
        """Declare owned persistence constraints."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Permit only registered writers; native guards validate the full graph.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django model implementation.
        **kwargs : Any
            Keyword arguments forwarded to the Django model implementation.
        """
        require_announcement_writer()
        self.full_clean(
            exclude=[field.name for field in self._meta.fields if field.is_relation],
            validate_unique=False,
            validate_constraints=False,
        )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Retain evidence; cancellation and correction are explicit commands.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django model implementation.
        **kwargs : Any
            Keyword arguments forwarded to the Django model implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The complete validated result; failures do not return partial evidence.

        Raises
        ------
        ValidationError
            If scope, input, state or retained evidence fails the owning contract.
        """
        del args, kwargs
        raise ValidationError("Announcement records are retained; use a correction.")


class _Evidence(_Owned):
    """Immutable human-attributed fact bound to its exact command receipt."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="announcements_%(class)s",
    )
    occurred_at = models.DateTimeField()
    command_receipt = models.ForeignKey(
        "AnnouncementCommandReceipt",
        on_delete=models.PROTECT,
        related_name="%(class)s_evidence",
    )

    class Meta:
        """Declare owned persistence constraints."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject replacement of immutable evidence even inside a writer.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django model implementation.
        **kwargs : Any
            Keyword arguments forwarded to the Django model implementation.

        Raises
        ------
        ValidationError
            If scope, input, state or retained evidence fails the owning contract.
        """
        if not self._state.adding:
            raise ValidationError("Announcement evidence is append-only.")
        super().save(*args, **kwargs)


class AnnouncementControl(_Owned):
    """One edition-local mutex, receipt sequence and current rules pointer."""

    sequence = models.PositiveBigIntegerField(default=0)
    settings_version = models.PositiveBigIntegerField(default=0)
    current_settings = models.ForeignKey(
        "AnnouncementSettingsRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_controls",
    )
    stopped = models.BooleanField(default=False)

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(fields=("edition",), name="ann_control_edition_uq")
        ]


class AnnouncementSettingsRevision(_Evidence):
    """Actual organizer confirmation of existing record-keeping rules."""

    number = models.PositiveBigIntegerField()
    policy_name = models.CharField(max_length=200)
    policy_description = models.TextField(max_length=2000, blank=True)
    policy_url = models.URLField(max_length=2000, blank=True)
    record_owner = models.CharField(max_length=200)
    review_on = models.DateField()
    channels = models.JSONField()

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition", "number"), name="ann_settings_number_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0)
                & ~models.Q(policy_name="")
                & ~models.Q(record_owner="")
                & (~models.Q(policy_url="") | ~models.Q(policy_description="")),
                name="ann_settings_shape",
            ),
        ]


class Announcement(_Owned):
    """Stable announcement identity; approval survives a pending correction."""

    version = models.PositiveBigIntegerField(default=1)
    status = models.CharField(
        max_length=24, choices=[(v, v) for v in STATUSES], default="draft"
    )
    current_revision = models.ForeignKey(
        "AnnouncementRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_announcements",
    )
    approved_revision = models.ForeignKey(
        "AnnouncementRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_announcements",
    )

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gt=0, status__in=STATUSES),
                name="ann_announcement_shape",
            )
        ]


class AnnouncementRevision(_Evidence):
    """Complete public copy and immutable correction-round author provenance."""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.PROTECT, related_name="revisions"
    )
    number = models.PositiveBigIntegerField()
    previous_revision = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="next_revision",
    )
    base_approved_revision = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="corrections",
    )
    round_id = models.UUIDField()
    settings_revision = models.ForeignKey(
        AnnouncementSettingsRevision,
        on_delete=models.PROTECT,
        related_name="announcement_revisions",
    )
    headline = models.CharField(max_length=MAX_HEADLINE)
    body = models.TextField(max_length=MAX_BODY)
    language_code = models.CharField(max_length=35)
    text_bytes = models.PositiveIntegerField()

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(
                fields=("announcement", "number"), name="ann_revision_number_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0, text_bytes__gt=0)
                & ~models.Q(headline="")
                & ~models.Q(body=""),
                name="ann_revision_shape",
            ),
        ]


class AnnouncementVariant(_Evidence):
    """Exact reviewed text with a destination snapshot, not a delivery adapter."""

    revision = models.ForeignKey(
        AnnouncementRevision, on_delete=models.PROTECT, related_name="variants"
    )
    channel_code = models.CharField(max_length=40)
    channel_label = models.CharField(max_length=100)
    channel_url = models.URLField(max_length=2000, blank=True)
    language_code = models.CharField(max_length=35)
    headline = models.CharField(max_length=MAX_HEADLINE)
    body = models.TextField(max_length=MAX_BODY)
    copy_digest = models.CharField(max_length=64)

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(
                fields=("revision", "channel_code", "language_code"),
                name="ann_variant_selection_uq",
            ),
            models.CheckConstraint(
                condition=~models.Q(headline="")
                & ~models.Q(body="")
                & models.Q(copy_digest__regex="^[0-9a-f]{64}$"),
                name="ann_variant_shape",
            ),
        ]


class AnnouncementReview(_Evidence):
    """One independent decision on an exact submitted revision."""

    revision = models.OneToOneField(
        AnnouncementRevision, on_delete=models.PROTECT, related_name="review"
    )
    decision = models.CharField(
        max_length=20,
        choices=(("approve", "Approve"), ("changes_requested", "Changes requested")),
    )
    note = models.CharField(max_length=MAX_NOTE, blank=True)

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(decision="approve")
                | (models.Q(decision="changes_requested") & ~models.Q(note="")),
                name="ann_review_shape",
            )
        ]


class AnnouncementPublicationReport(_Evidence):
    """An operator's report, with append-only corrections to mistaken reports."""

    variant = models.ForeignKey(
        AnnouncementVariant,
        on_delete=models.PROTECT,
        related_name="publication_reports",
    )
    supersedes_report = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replacement",
    )
    withdrawn = models.BooleanField(default=False)
    publication_url = models.URLField(max_length=2000, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=MAX_NOTE, blank=True)

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(
                fields=("variant",),
                condition=models.Q(supersedes_report__isnull=True),
                name="ann_report_initial_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(supersedes_report__isnull=True, withdrawn=False)
                | (models.Q(supersedes_report__isnull=False) & ~models.Q(reason="")),
                name="ann_report_shape",
            ),
        ]


class AnnouncementCommandReceipt(_Owned):
    """Immutable exact intent, result and edition sequence for retry evidence."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="announcement_receipts",
    )
    operation = models.CharField(max_length=24, choices=[(v, v) for v in OPERATIONS])
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    control_sequence = models.PositiveBigIntegerField()
    announcement = models.ForeignKey(
        Announcement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    object_id = models.UUIDField()
    resulting_version = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=MAX_NOTE, blank=True)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=80)

    class Meta:
        """Declare owned persistence constraints."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "idempotency_key"),
                name="ann_receipt_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("edition", "control_sequence"), name="ann_receipt_sequence_uq"
            ),
            models.UniqueConstraint(
                fields=("announcement", "resulting_version"),
                condition=models.Q(announcement__isnull=False),
                name="ann_receipt_object_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    control_sequence__gt=0,
                    resulting_version__gt=0,
                    operation__in=OPERATIONS,
                    request_digest__regex="^[0-9a-f]{64}$",
                ),
                name="ann_receipt_shape",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Never replace retained command intent or its result.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the Django model implementation.
        **kwargs : Any
            Keyword arguments forwarded to the Django model implementation.

        Raises
        ------
        ValidationError
            If scope, input, state or retained evidence fails the owning contract.
        """
        if not self._state.adding:
            raise ValidationError("Announcement receipts are append-only.")
        super().save(*args, **kwargs)
