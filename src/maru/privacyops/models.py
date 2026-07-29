"""Tracked privacy requests, archive corrections, and disposal evidence."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel


class SubjectRightsRequest(UUIDTimeStampedModel):
    class Kind(models.TextChoices):
        ACCESS = "access", "Access"
        CORRECTION = "correction", "Correction"
        PORTABILITY = "portability", "Portability"
        RESTRICTION = "restriction", "Restriction"
        OBJECTION = "objection", "Objection"
        DELETION = "deletion", "Deletion"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        IDENTITY_CHECK = "identity_check", "Identity check"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        DENIED = "denied", "Denied"

    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="subject_rights_requests",
    )
    organization_id = models.UUIDField(null=True, blank=True)
    kind = models.CharField(max_length=24, choices=Kind)
    status = models.CharField(
        max_length=24,
        choices=Status,
        default=Status.RECEIVED,
    )
    requested_at = models.DateTimeField()
    request_summary = models.CharField(max_length=1000)
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_outcome_summary = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ("-requested_at", "-id")


class PostEditionCorrection(UUIDTimeStampedModel):
    """Append-only correction overlay; archived source facts stay unchanged."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    account_id = models.UUIDField()
    target_type = models.CharField(max_length=120)
    target_id = models.UUIDField()
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PROPOSED,
    )
    changed_fields = models.JSONField()
    reason = models.CharField(max_length=1000)
    requested_by_id = models.UUIDField()
    requested_at = models.DateTimeField()
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ("requested_at", "id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "target_type", "target_id"),
                name="privacy_correction_target_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            current = type(self).objects.filter(id=self.id).values("status").first()
            if current and current["status"] != self.Status.PROPOSED:
                raise ValidationError(
                    "Decided corrections are immutable.",
                    code="immutable_post_edition_correction",
                )
        self.full_clean()
        super().save(*args, **kwargs)


class RetentionPolicy(UUIDTimeStampedModel):
    """Versioned purpose/jurisdiction policy, not a blanket account TTL."""

    class Disposition(models.TextChoices):
        DELETE = "delete", "Delete"
        MINIMIZE = "minimize", "Minimize"
        RETAIN = "retain", "Retain with legal basis"

    organization_id = models.UUIDField()
    jurisdiction_code = models.CharField(max_length=40)
    data_category = models.CharField(max_length=80)
    version = models.PositiveIntegerField()
    retention_days = models.PositiveIntegerField()
    disposition = models.CharField(max_length=16, choices=Disposition)
    lawful_basis = models.CharField(max_length=240)
    approved_by_id = models.UUIDField()
    approved_at = models.DateTimeField()
    active = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "retention policies"
        ordering = ("organization_id", "data_category", "version")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "organization_id",
                    "jurisdiction_code",
                    "data_category",
                    "version",
                ),
                name="retention_policy_version_unique",
            ),
            models.UniqueConstraint(
                fields=("organization_id", "jurisdiction_code", "data_category"),
                condition=models.Q(active=True),
                name="one_active_retention_policy",
            ),
        ]


class DisposalReceipt(UUIDTimeStampedModel):
    """Append-only proof of deletion, minimization, or justified retention."""

    organization_id = models.UUIDField()
    edition_id = models.UUIDField(null=True, blank=True)
    policy = models.ForeignKey(
        RetentionPolicy,
        on_delete=models.PROTECT,
        related_name="disposal_receipts",
    )
    target_type = models.CharField(max_length=120)
    target_id = models.UUIDField()
    disposition = models.CharField(max_length=16, choices=RetentionPolicy.Disposition)
    applied_at = models.DateTimeField()
    applied_by_id = models.UUIDField(null=True, blank=True)
    safe_result_code = models.CharField(max_length=80)
    downstream_receipts = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("applied_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "target_type", "target_id"),
                name="privacy_disposal_target_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Disposal receipts are append-only.",
                code="immutable_disposal_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)


POST_EDITION_CORRECTION_STATUS_CHOICES = PostEditionCorrection.Status.choices
SUBJECT_RIGHTS_REQUEST_KIND_CHOICES = SubjectRightsRequest.Kind.choices
SUBJECT_RIGHTS_REQUEST_STATUS_CHOICES = SubjectRightsRequest.Status.choices
