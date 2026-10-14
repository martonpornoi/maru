"""Owned immutable guidance, independent decisions and current availability."""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel

from .catalog import MAX_BODY, MAX_NOTE, MAX_TITLE, OPERATIONS, STATUSES
from .writer_boundary import require_guidance_writer


class _Owned(UUIDTimeStampedModel):
    """All domain rows retain exact organization and event ownership."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="knowledge_%(class)s",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="knowledge_%(class)s",
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
        require_guidance_writer()
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
        raise ValidationError("Guidance records are retained; use a correction.")


class _Evidence(_Owned):
    """Immutable human-attributed fact bound to its exact command receipt."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="knowledge_%(class)s",
    )
    occurred_at = models.DateTimeField()
    command_receipt = models.ForeignKey(
        "GuidanceCommandReceipt",
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
            raise ValidationError("Guidance evidence is append-only.")
        super().save(*args, **kwargs)


class GuidanceControl(_Owned):
    """Edition mutex and complete command sequence for safe stop/resume previews."""

    sequence = models.PositiveBigIntegerField(default=0)
    settings_version = models.PositiveBigIntegerField(default=0)
    current_settings = models.ForeignKey(
        "GuidanceSettingsRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_controls",
    )
    stopped = models.BooleanField(default=False)

    class Meta:
        """Keep exactly one owner control per edition."""

        constraints = [
            models.UniqueConstraint(fields=("edition",), name="kno_control_edition_uq")
        ]


class GuidanceSettingsRevision(_Evidence):
    """Immutable confirmation of existing rules, without automatic disposal claims."""

    number = models.PositiveBigIntegerField()
    policy_name = models.CharField(max_length=200)
    policy_description = models.TextField(max_length=2000, blank=True)
    policy_url = models.URLField(max_length=2000, blank=True)
    record_owner = models.CharField(max_length=200)
    review_on = models.DateField()

    class Meta:
        """Require readable rules and one exact revision at each settings cursor."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition", "number"), name="kno_settings_number_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0)
                & ~models.Q(policy_name="")
                & ~models.Q(record_owner="")
                & (~models.Q(policy_url="") | ~models.Q(policy_description="")),
                name="kno_settings_shape",
            ),
        ]


class GuidanceItem(_Owned):
    """One language's working copy and separately retained reader availability."""

    version = models.PositiveBigIntegerField(default=1)
    status = models.CharField(
        max_length=24, choices=[(v, v) for v in STATUSES], default="draft"
    )
    language_code = models.CharField(max_length=35)
    withdrawn = models.BooleanField(default=False)
    current_revision = models.ForeignKey(
        "GuidanceRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="working_items",
    )
    published_revision = models.ForeignKey(
        "GuidanceRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_items",
    )
    approved_revision = models.ForeignKey(
        "GuidanceRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="last_approved_items",
    )

    class Meta:
        """Keep publication and withdrawal consistent without losing approvals."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gt=0, status__in=STATUSES)
                & ~models.Q(language_code=""),
                name="kno_item_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(withdrawn=False)
                | models.Q(published_revision__isnull=True),
                name="kno_withdrawn_unpublished",
            ),
        ]


class GuidanceRevision(_Evidence):
    """Exact text and metadata with accepted team and authorship-round evidence."""

    item = models.ForeignKey(
        GuidanceItem, on_delete=models.PROTECT, related_name="revisions"
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
        related_name="replacements",
    )
    round_id = models.UUIDField()
    settings_revision = models.ForeignKey(
        GuidanceSettingsRevision,
        on_delete=models.PROTECT,
        related_name="guidance_revisions",
    )
    team_id = models.UUIDField()
    team_activation_receipt_id = models.UUIDField()
    team_label = models.CharField(max_length=160)
    title = models.CharField(max_length=MAX_TITLE)
    body = models.TextField(max_length=MAX_BODY)
    language_code = models.CharField(max_length=35)
    review_by = models.DateField(null=True, blank=True)
    placements = models.JSONField(default=list, blank=True)
    text_bytes = models.PositiveIntegerField()

    class Meta:
        """Bind each command to one exact immutable version."""

        constraints = [
            models.UniqueConstraint(
                fields=("item", "number"), name="kno_revision_number_uq"
            ),
            models.UniqueConstraint(
                fields=("command_receipt",), name="kno_revision_receipt_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0, text_bytes__gt=0)
                & ~models.Q(title="")
                & ~models.Q(body="")
                & ~models.Q(team_label=""),
                name="kno_revision_shape",
            ),
        ]


class GuidanceReview(_Evidence):
    """An independent decision on submitted text and its complete metadata."""

    revision = models.OneToOneField(
        GuidanceRevision, on_delete=models.PROTECT, related_name="review"
    )
    decision = models.CharField(
        max_length=20,
        choices=(("approve", "Approve"), ("changes_requested", "Changes requested")),
    )
    note = models.CharField(max_length=MAX_NOTE, blank=True)

    class Meta:
        """Requested changes always retain an actionable explanation."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(decision="approve")
                | (models.Q(decision="changes_requested") & ~models.Q(note="")),
                name="kno_review_shape",
            ),
        ]


class GuidanceCommandReceipt(_Owned):
    """Immutable intent and result linked to native audit and event evidence."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_receipts",
    )
    operation = models.CharField(max_length=24, choices=[(v, v) for v in OPERATIONS])
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    control_sequence = models.PositiveBigIntegerField()
    item = models.ForeignKey(
        GuidanceItem,
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
        """Serialize scoped retries, complete edition order and item version order."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "idempotency_key"),
                name="kno_receipt_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("edition", "control_sequence"), name="kno_receipt_sequence_uq"
            ),
            models.UniqueConstraint(
                fields=("item", "resulting_version"),
                condition=models.Q(item__isnull=False),
                name="kno_receipt_item_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    control_sequence__gt=0,
                    resulting_version__gt=0,
                    operation__in=OPERATIONS,
                    request_digest__regex="^[0-9a-f]{64}$",
                ),
                name="kno_receipt_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    operation__in=("settings_update", "stop", "resume"),
                    item__isnull=True,
                )
                | (
                    ~models.Q(operation__in=("settings_update", "stop", "resume"))
                    & models.Q(item__isnull=False)
                ),
                name="kno_receipt_aggregate_kind",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject any replacement of retained retry intent or command result.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model writer.
        **kwargs : Any
            Named arguments forwarded to Django's model writer.

        Raises
        ------
        ValidationError
            If an existing immutable receipt is being changed.
        """
        if not self._state.adding:
            raise ValidationError("Guidance receipts are append-only.")
        super().save(*args, **kwargs)
