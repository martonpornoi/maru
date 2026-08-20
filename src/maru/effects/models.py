"""Durable facts, delivery work, and append-only effect attempts."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel


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
