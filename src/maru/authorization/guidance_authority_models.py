"""Retained, purpose-specific Guidance qualification and authenticated decisions."""

from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from maru.authorization.guidance_writer import _require_guidance_authority_writer
from maru.core.models import UUIDTimeStampedModel


class _GuidanceEvidence(UUIDTimeStampedModel):
    """Append evidence only through the owning transaction."""

    class Meta:
        """Retain the exact immutable evidence constraints."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        _require_guidance_authority_writer()
        if not self._state.adding:
            raise ValidationError("Guidance responsibility evidence is retained.")
        self.full_clean(
            exclude={field.name for field in self._meta.fields if field.is_relation}
        )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError("Guidance responsibility evidence is retained.")


class GuidanceTeam(_GuidanceEvidence):
    """Stable edition ownership; recovery never changes historical attribution."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    edition = models.OneToOneField("events.EventEdition", on_delete=models.PROTECT)
    original_activation = models.OneToOneField(
        "events.GuidanceActivationReceipt", on_delete=models.PROTECT
    )


class GuidanceAuthoritySetupReceipt(_GuidanceEvidence):
    """Qualify only the exact outputs accepted in one two-person ceremony."""

    activation = models.OneToOneField(
        "events.GuidanceActivationReceipt", on_delete=models.PROTECT
    )
    team = models.ForeignKey(
        GuidanceTeam, on_delete=models.PROTECT, related_name="setups"
    )
    root_a = models.ForeignKey(
        "authorization.AuthorityIssuance",
        on_delete=models.PROTECT,
        related_name="guidance_setups_as_root_a",
    )
    root_b = models.ForeignKey(
        "authorization.AuthorityIssuance",
        on_delete=models.PROTECT,
        related_name="guidance_setups_as_root_b",
    )
    controller_a = models.OneToOneField(
        "authorization.RoleAssignment",
        on_delete=models.PROTECT,
        related_name="guidance_setup_as_controller_a",
    )
    controller_b = models.OneToOneField(
        "authorization.RoleAssignment",
        on_delete=models.PROTECT,
        related_name="guidance_setup_as_controller_b",
    )
    content_a = models.OneToOneField(
        "authorization.RoleAssignment",
        on_delete=models.PROTECT,
        related_name="guidance_setup_as_content_a",
    )
    content_b = models.OneToOneField(
        "authorization.RoleAssignment",
        on_delete=models.PROTECT,
        related_name="guidance_setup_as_content_b",
    )
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    correlation_id = models.UUIDField()

    class Meta:
        """Retain the exact immutable evidence constraints."""

        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(root_a=models.F("root_b")),
                name="guidance_setup_distinct_root_sources",
            ),
            models.CheckConstraint(
                condition=~models.Q(controller_a=models.F("controller_b")),
                name="guidance_setup_distinct_controllers",
            ),
            models.CheckConstraint(
                condition=~models.Q(content_a=models.F("content_b")),
                name="guidance_setup_distinct_content",
            ),
            models.CheckConstraint(
                condition=~models.Q(controller_a=models.F("content_a"))
                & ~models.Q(controller_a=models.F("content_b"))
                & ~models.Q(controller_b=models.F("content_a"))
                & ~models.Q(controller_b=models.F("content_b")),
                name="guidance_setup_separate_control_content",
            ),
        ]


class GuidanceRecipeQualification(_GuidanceEvidence):
    """Qualify one canonical organization definition under exact root decisions."""

    setup = models.ForeignKey(
        GuidanceAuthoritySetupReceipt, on_delete=models.PROTECT, related_name="recipes"
    )
    role_bundle = models.OneToOneField(
        "authorization.RoleBundle", on_delete=models.PROTECT
    )


class GuidanceAccessRequest(_GuidanceEvidence):
    """Propose a closed content recipe for an actual independent decision."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    edition = models.ForeignKey("events.EventEdition", on_delete=models.PROTECT)
    team = models.ForeignKey(GuidanceTeam, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_access_requested",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_access_to_approve",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guidance_access_proposed",
    )
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle", on_delete=models.PROTECT
    )
    actor_source = models.ForeignKey(
        "authorization.AuthorityIssuance",
        on_delete=models.PROTECT,
        related_name="guidance_access_actor_sources",
    )
    approver_source = models.ForeignKey(
        "authorization.AuthorityIssuance",
        on_delete=models.PROTECT,
        related_name="guidance_access_approver_sources",
    )
    effective_from = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    decision_deadline = models.DateTimeField()
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    reason = models.CharField(max_length=240)
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    correlation_id = models.UUIDField()

    class Meta:
        """Retain the exact immutable evidence constraints."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("requested_by", "idempotency_key"),
                name="guidance_access_actor_key_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(requested_by=models.F("approver")),
                name="guidance_access_independent_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(recipient=models.F("approver")),
                name="guidance_access_no_self_approval",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="guidance_access_request_digest",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("effective_from")),
                name="guidance_access_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="guidance_access_reason_required"
            ),
        ]


class GuidanceAccessDecision(_GuidanceEvidence):
    """Retain the named approver's answer and its exact assignment, if accepted."""

    request = models.OneToOneField(
        GuidanceAccessRequest, on_delete=models.PROTECT, related_name="decision"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    accepted = models.BooleanField()
    request_digest = models.CharField(max_length=64)
    assignment = models.OneToOneField(
        "authorization.RoleAssignment", on_delete=models.PROTECT, null=True, blank=True
    )
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    correlation_id = models.UUIDField()

    class Meta:
        """Retain the exact immutable evidence constraints."""

        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(accepted=True, assignment__isnull=False)
                | models.Q(accepted=False, assignment__isnull=True),
                name="guidance_access_answer_output_shape",
            ),
        ]


class GuidanceRevocationReceipt(_GuidanceEvidence):
    """Prove a single current Guidance controller deliberately removed access."""

    assignment = models.OneToOneField(
        "authorization.RoleAssignment", on_delete=models.PROTECT
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source = models.ForeignKey(
        "authorization.AuthorityIssuance", on_delete=models.PROTECT
    )
    revoked_at = models.DateTimeField()
    reason = models.CharField(max_length=240)
    source_audit = models.OneToOneField("audit.AuditEvent", on_delete=models.PROTECT)
    correlation_id = models.UUIDField()
