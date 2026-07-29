"""Append-only security audit events and integrity checkpoints."""

from typing import Any, cast

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel

MAX_SAFE_METADATA_TEXT_LENGTH = 160
SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 hex digest.",
    code="invalid_digest",
)

SAFE_METADATA_TYPES: dict[str, type[object] | tuple[type[object], ...]] = {
    "access_purpose": str,
    "client_kind": str,
    "export_classification": str,
    "http_method": str,
    "policy_version": str,
    "remote_provider": str,
    "route_name": str,
    "target_count": int,
}
SAFE_METADATA_KEYS = frozenset(SAFE_METADATA_TYPES)


def validate_safe_metadata(value: dict[str, object]) -> None:
    if not isinstance(value, dict):
        raise ValidationError(
            "Audit metadata must be an object.",
            code="unsafe_audit_metadata",
        )
    unknown = set(value).difference(SAFE_METADATA_KEYS)
    if unknown:
        raise ValidationError(
            f"Audit metadata key is not allowlisted: {sorted(unknown)[0]}",
            code="unsafe_audit_metadata",
        )
    for key, item in value.items():
        expected_type = SAFE_METADATA_TYPES[key]
        if not isinstance(item, expected_type) or (
            expected_type is int and isinstance(item, bool)
        ):
            raise ValidationError(
                f"Audit metadata value has the wrong type: {key}",
                code="unsafe_audit_metadata",
            )
        if isinstance(item, str) and len(item) > MAX_SAFE_METADATA_TEXT_LENGTH:
            raise ValidationError(
                f"Audit metadata value is too long: {key}",
                code="unsafe_audit_metadata",
            )
        if key == "target_count":
            target_count = cast(int, item)
            if target_count >= 0:
                continue
            raise ValidationError(
                "Audit target count cannot be negative.",
                code="unsafe_audit_metadata",
            )


class AuditIntegrityBatch(UUIDTimeStampedModel):
    sequence = models.PositiveBigIntegerField(unique=True)
    previous_digest = models.CharField(max_length=64, validators=[SHA256_VALIDATOR])
    digest = models.CharField(max_length=64, validators=[SHA256_VALIDATOR])
    event_count = models.PositiveIntegerField()

    class Meta:
        ordering = ("sequence",)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Audit integrity batches are immutable.",
                code="immutable_audit_batch",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Audit integrity batches are immutable.",
            code="immutable_audit_batch",
        )


class AuditEvent(UUIDTimeStampedModel):
    class Outcome(models.TextChoices):
        ALLOW = "allow", "Allow"
        DENY = "deny", "Deny"
        ERROR = "error", "Error"

    schema_version = models.PositiveSmallIntegerField(default=1)
    occurred_at = models.DateTimeField()
    principal_kind = models.CharField(max_length=40)
    principal_id = models.UUIDField(null=True, blank=True)
    principal_context_id = models.UUIDField(null=True, blank=True)
    organization_id = models.UUIDField(null=True, blank=True)
    event_edition_id = models.UUIDField(null=True, blank=True)
    capability_code = models.CharField(max_length=120)
    operation = models.CharField(max_length=160)
    target_type = models.CharField(max_length=120)
    target_id = models.UUIDField(null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome)
    reason_code = models.CharField(max_length=120)
    obligations = ArrayField(
        models.CharField(max_length=120),
        default=list,
        blank=True,
    )
    changed_fields = ArrayField(
        models.CharField(max_length=120),
        default=list,
        blank=True,
    )
    correlation_id = models.UUIDField()
    causation_id = models.UUIDField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    idempotency_key_hash = models.CharField(
        max_length=64,
        blank=True,
        validators=[SHA256_VALIDATOR],
    )
    source_channel = models.CharField(max_length=40)
    delegated = models.BooleanField(default=False)
    elevated = models.BooleanField(default=False)
    break_glass = models.BooleanField(default=False)
    safe_metadata = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_safe_metadata],
    )
    retention_class = models.CharField(max_length=80, default="security-standard")
    integrity_batch = models.ForeignKey(
        AuditIntegrityBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )

    class Meta:
        ordering = ("occurred_at", "id")
        indexes = [
            models.Index(
                fields=("organization_id", "occurred_at"),
                name="audit_org_occurred_idx",
            ),
            models.Index(
                fields=("principal_id", "occurred_at"),
                name="audit_principal_occurred_idx",
            ),
            models.Index(
                fields=("correlation_id",),
                name="audit_correlation_idx",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Audit events are append-only.",
                code="immutable_audit_event",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Audit events are append-only.",
            code="immutable_audit_event",
        )
