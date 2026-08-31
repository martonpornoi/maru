"""Durable facts, delivery work, and append-only effect attempts."""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel

MAX_EFFECT_REPLAY_REASON_LENGTH = 240
MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS = 20
MAX_EFFECT_TOTAL_ATTEMPTS = 100


class DomainEvent(UUIDTimeStampedModel):
    """Store domain event records."""

    event_name = models.CharField(max_length=160)
    schema_version = models.PositiveSmallIntegerField()
    occurred_at = models.DateTimeField()
    organization_id = models.UUIDField()
    event_edition_id = models.UUIDField(null=True, blank=True)
    aggregate_type = models.CharField(max_length=120)
    aggregate_id = models.UUIDField()
    aggregate_version = models.PositiveBigIntegerField()
    payload = models.JSONField()
    correlation_id = models.UUIDField()
    causation_id = models.UUIDField(null=True, blank=True)
    actor_kind = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True, blank=True)
    retention_class = models.CharField(max_length=80, default="domain-standard")

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("occurred_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("aggregate_type", "aggregate_id", "aggregate_version"),
                name="domain_event_aggregate_version_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "occurred_at"),
                name="effect_event_org_time_idx",
            ),
            models.Index(
                fields=("correlation_id",),
                name="effect_event_correlation_idx",
            ),
        ]

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
                "Domain events are append-only.",
                code="immutable_domain_event",
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
            "Domain events are append-only.",
            code="immutable_domain_event",
        )


class OutboxMessage(UUIDTimeStampedModel):
    """Store outbox message records."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        QUARANTINED = "quarantined", "Quarantined"
        CANCELLED = "cancelled", "Cancelled"

    event = models.ForeignKey(
        DomainEvent,
        on_delete=models.PROTECT,
        related_name="outbox_messages",
    )
    organization_id = models.UUIDField()
    destination = models.CharField(max_length=120)
    workload_pool = models.CharField(max_length=80)
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.PENDING,
    )
    available_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=8)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=120, blank=True)
    replay_count = models.PositiveIntegerField(default=0)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("available_at", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "destination"),
                name="outbox_event_destination_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="outbox_max_attempts_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__lte=MAX_EFFECT_TOTAL_ATTEMPTS),
                name="outbox_max_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=models.F("max_attempts")),
                name="outbox_attempts_within_maximum",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="processing",
                        claimed_at__isnull=False,
                        lease_expires_at__isnull=False,
                        lease_token__isnull=False,
                        completed_at__isnull=True,
                    )
                    | (
                        ~models.Q(status="processing")
                        & models.Q(
                            lease_expires_at__isnull=True,
                            lease_token__isnull=True,
                        )
                    )
                ),
                name="outbox_lease_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=(
                            "succeeded",
                            "quarantined",
                            "cancelled",
                        ),
                        completed_at__isnull=False,
                    )
                    | models.Q(
                        status__in=("pending", "processing"),
                        completed_at__isnull=True,
                    )
                ),
                name="outbox_completion_matches_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization_id",
                    "workload_pool",
                    "status",
                    "available_at",
                ),
                name="outbox_tenant_claim_idx",
            ),
            models.Index(
                fields=("status", "lease_expires_at"),
                name="outbox_expired_lease_idx",
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
        if (
            self.event_id
            and self.organization_id
            and self.event.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"organization_id": "Outbox tenant must match its domain event."}
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
            "Outbox messages require a controlled retention workflow.",
            code="protected_outbox_message",
        )


class EffectReplayReceipt(UUIDTimeStampedModel):
    """Retain one immutable, tenant-bound operator replay decision."""

    outbox_message = models.ForeignKey(
        OutboxMessage,
        on_delete=models.PROTECT,
        related_name="replay_receipts",
    )
    organization_id = models.UUIDField()
    actor_id = models.UUIDField()
    reason = models.CharField(max_length=MAX_EFFECT_REPLAY_REASON_LENGTH)
    additional_attempts = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS),
        ]
    )
    previous_max_attempts = models.PositiveIntegerField()
    new_max_attempts = models.PositiveIntegerField()
    replay_count = models.PositiveIntegerField()
    correlation_id = models.UUIDField(db_index=True)
    retention_class = models.CharField(
        max_length=80,
        default="operations-extended",
        editable=False,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("outbox_message_id", "replay_count", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("outbox_message", "replay_count"),
                name="effect_replay_count_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(additional_attempts__gte=1)
                    & models.Q(
                        additional_attempts__lte=(MAX_EFFECT_REPLAY_ADDITIONAL_ATTEMPTS)
                    )
                ),
                name="effect_replay_additional_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    new_max_attempts=(
                        models.F("previous_max_attempts")
                        + models.F("additional_attempts")
                    )
                ),
                name="effect_replay_attempt_limit_arithmetic",
            ),
            models.CheckConstraint(
                condition=models.Q(new_max_attempts__lte=MAX_EFFECT_TOTAL_ATTEMPTS),
                name="effect_replay_total_attempts_bounded",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "outbox_message", "-replay_count"),
                name="effect_replay_org_message_idx",
            )
        ]

    def clean(self) -> None:
        """Require evidence to describe the locked pre-replay message state.

        Raises
        ------
        ValidationError
            If the receipt is not tenant-bound or does not describe the next
            valid bounded replay transition.
        """
        super().clean()
        if not self.outbox_message_id:
            return
        message = self.outbox_message
        errors: dict[str, str] = {}
        if message.organization_id != self.organization_id:
            errors["organization_id"] = (
                "Replay receipt tenant must match its outbox message."
            )
        if message.status != OutboxMessage.Status.QUARANTINED:
            errors["outbox_message"] = (
                "Replay evidence can be appended only for quarantined work."
            )
        if message.max_attempts != self.previous_max_attempts:
            errors["previous_max_attempts"] = (
                "Replay evidence must retain the locked prior attempt limit."
            )
        if self.new_max_attempts != (
            self.previous_max_attempts + self.additional_attempts
        ):
            errors["new_max_attempts"] = (
                "Replay evidence attempt limits must match the requested increase."
            )
        if self.new_max_attempts > MAX_EFFECT_TOTAL_ATTEMPTS:
            errors["new_max_attempts"] = (
                "Replay evidence cannot exceed the total attempt safety limit."
            )
        if self.replay_count != message.replay_count + 1:
            errors["replay_count"] = (
                "Replay evidence must describe the next replay transition."
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            errors["reason"] = "A replay reason is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and append the replay receipt.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If an existing receipt would be mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Effect replay receipts are append-only.",
                code="immutable_effect_replay_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of retained replay rationale.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            This method never returns because replay evidence is immutable.

        Raises
        ------
        ValidationError
            Always, because replay evidence is append-only.
        """
        _ = args, kwargs
        raise ValidationError(
            "Effect replay receipts are append-only.",
            code="immutable_effect_replay_receipt",
        )


class EffectAttempt(UUIDTimeStampedModel):
    """Store effect attempt records."""

    class Outcome(models.TextChoices):
        """Enumerate supported outcome values."""

        SUCCEEDED = "succeeded", "Succeeded"
        TRANSIENT_FAILURE = "transient_failure", "Transient failure"
        PERMANENT_FAILURE = "permanent_failure", "Permanent failure"
        EXHAUSTED = "exhausted", "Exhausted"

    outbox_message = models.ForeignKey(
        OutboxMessage,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    attempt_number = models.PositiveIntegerField()
    lease_token = models.UUIDField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    outcome = models.CharField(max_length=30, choices=Outcome)
    error_code = models.CharField(max_length=120, blank=True)
    handler_code = models.CharField(max_length=160)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("outbox_message_id", "attempt_number")
        constraints = [
            models.UniqueConstraint(
                fields=("outbox_message", "attempt_number"),
                name="effect_attempt_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(finished_at__gte=models.F("started_at")),
                name="effect_attempt_finished_after_start",
            ),
        ]

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
                "Effect attempts are append-only.",
                code="immutable_effect_attempt",
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
            "Effect attempts are append-only.",
            code="immutable_effect_attempt",
        )
