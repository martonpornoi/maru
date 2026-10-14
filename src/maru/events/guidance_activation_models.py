"""Retained human decisions and one atomic Guidance adoption result."""

from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel
from maru.events.guidance_setup_writer import _require_guidance_setup_writer


class _GuidanceActivationEvidence(UUIDTimeStampedModel):
    """Retain the actual request, answers and result without editable approval flags."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        _require_guidance_setup_writer()
        if not self._state.adding:
            raise ValidationError("Guidance activation evidence is retained.")
        self.full_clean(
            exclude={field.name for field in self._meta.fields if field.is_relation}
        )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError("Guidance activation evidence is retained.")


class GuidanceActivationRequest(_GuidanceActivationEvidence):
    """Freeze the exact two-person plan before either person accepts it."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    edition = models.ForeignKey("events.EventEdition", on_delete=models.PROTECT)
    representation = models.ForeignKey(
        "organizations.OrganizationRepresentation", on_delete=models.PROTECT
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_activation_requests_proposed",
    )
    operator_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_activation_requests_as_a",
    )
    operator_b = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_activation_requests_as_b",
    )
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    expected_edition_version = models.PositiveBigIntegerField()
    expected_adoption_revision = models.PositiveBigIntegerField()
    source_profile_code = models.CharField(max_length=40)
    source_profile_version = models.PositiveIntegerField()
    target_profile_code = models.CharField(max_length=40)
    target_profile_version = models.PositiveIntegerField()
    source_manifest_digest = models.CharField(max_length=64)
    target_manifest_digest = models.CharField(max_length=64)
    representation_version = models.PositiveBigIntegerField()
    purpose = models.CharField(
        max_length=16,
        choices=(
            ("initial", "Start Guidance"),
            ("recovery", "Restore Guidance responsibility"),
        ),
    )
    reason = models.CharField(max_length=240)
    expires_at = models.DateTimeField()
    correlation_id = models.UUIDField()

    class Meta:
        """Keep the original actor key and the independent pair exact."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("proposed_by", "idempotency_key"),
                name="guidance_activation_request_key_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(operator_a=models.F("operator_b")),
                name="guidance_activation_distinct_operators",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="guidance_activation_request_digest",
            ),
            models.CheckConstraint(
                condition=models.Q(purpose__in=("initial", "recovery")),
                name="guidance_activation_request_purpose",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_edition_version__gte=1),
                name="guidance_activation_source_version",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="guidance_activation_request_reason",
            ),
        ]


class GuidanceActivationDecision(_GuidanceActivationEvidence):
    """Retain one actual person's self-acceptance and conditional cross-approval."""

    request = models.ForeignKey(
        GuidanceActivationRequest, on_delete=models.PROTECT, related_name="decisions"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    accepted = models.BooleanField()
    request_digest = models.CharField(max_length=64)
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    correlation_id = models.UUIDField()

    class Meta:
        """A person answers this exact immutable proposal at most once."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("request", "actor"), name="guidance_activation_one_answer"
            )
        ]


class GuidanceActivationReceipt(_GuidanceActivationEvidence):
    """Bind the accepted profile change to the complete qualified authority setup."""

    request = models.OneToOneField(
        GuidanceActivationRequest, on_delete=models.PROTECT, related_name="receipt"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    edition = models.ForeignKey("events.EventEdition", on_delete=models.PROTECT)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    result_edition_version = models.PositiveBigIntegerField()
    result_adoption_revision = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()

    class Meta:
        """Each adoption revision has exactly one retained result."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("edition", "result_adoption_revision"),
                name="guidance_activation_revision_unique",
            )
        ]
