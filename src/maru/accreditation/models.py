"""Edition credentials, revocation, offline manifests, and reconciliation."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from maru.core.models import UUIDTimeStampedModel


class Credential(UUIDTimeStampedModel):
    """Store credential records."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        ISSUED = "issued", "Issued"
        REPLACED = "replaced", "Replaced"
        REVOKED = "revoked", "Revoked"

    registration = models.ForeignKey(
        "registration.Registration",
        on_delete=models.PROTECT,
        related_name="credentials",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    account_id = models.UUIDField()
    public_id = models.CharField(max_length=32)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.ISSUED,
    )
    issue_sequence = models.PositiveIntegerField()
    label_snapshot = models.CharField(max_length=160)
    issued_at = models.DateTimeField()
    issued_by_id = models.UUIDField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_id = models.UUIDField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("registration_id", "issue_sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition_id", "public_id"),
                name="credential_public_id_unique",
            ),
            models.UniqueConstraint(
                fields=("registration", "issue_sequence"),
                name="credential_issue_sequence_unique",
            ),
            models.UniqueConstraint(
                fields=("registration",),
                condition=models.Q(status="issued"),
                name="one_active_credential_per_registration",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "public_id"),
                name="accred_credential_lookup_idx",
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
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
            or self.registration.account_id != self.account_id
        ):
            raise ValidationError(
                "Credential scope must match the registration.",
                code="credential_scope_mismatch",
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
            "Credentials are revoked or replaced, never deleted.",
            code="protected_credential",
        )


class CredentialEvent(UUIDTimeStampedModel):
    """Store credential event records."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        ISSUED = "issued", "Issued"
        REPRINTED = "reprinted", "Reprinted"
        REVOKED = "revoked", "Revoked"
        VERIFIED = "verified", "Verified"
        DENIED = "denied", "Denied"

    credential = models.ForeignKey(
        Credential,
        on_delete=models.PROTECT,
        related_name="events",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    kind = models.CharField(max_length=16, choices=Kind)
    occurred_at = models.DateTimeField()
    actor_kind = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True, blank=True)
    reason_code = models.CharField(max_length=80)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("occurred_at", "id")

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
                "Credential events are append-only.",
                code="immutable_credential_event",
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
            "Credential events are append-only.",
            code="protected_credential_event",
        )


class RelayDevice(UUIDTimeStampedModel):
    """Store relay device records."""

    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    code = models.SlugField(max_length=80)
    label = models.CharField(max_length=160)
    signing_secret_env_var = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True)
    last_sequence = models.PositiveBigIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition_id", "code"),
                name="relay_device_code_unique",
            )
        ]


class OfflineCredentialManifest(UUIDTimeStampedModel):
    """Store offline credential manifest records."""

    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    sequence = models.PositiveBigIntegerField()
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    generated_at = models.DateTimeField()
    generated_by_id = models.UUIDField()
    credential_count = models.PositiveIntegerField()
    payload = models.JSONField()
    payload_digest = models.CharField(max_length=64)
    signature = models.CharField(max_length=64)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition_id", "sequence"),
                name="offline_manifest_sequence_unique",
            )
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
                "Offline manifests are immutable.",
                code="immutable_offline_manifest",
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
            "Offline manifests require the accreditation retention workflow.",
            code="protected_offline_manifest",
        )


class OfflineCheckInOperation(UUIDTimeStampedModel):
    """Store offline check in operation records."""

    class Outcome(models.TextChoices):
        """Enumerate supported outcome values."""

        APPLIED = "applied", "Applied"
        DUPLICATE = "duplicate", "Duplicate"
        CONFLICT = "conflict", "Conflict"
        REJECTED = "rejected", "Rejected"

    device = models.ForeignKey(
        RelayDevice,
        on_delete=models.PROTECT,
        related_name="check_in_operations",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    operation_id = models.UUIDField()
    device_sequence = models.PositiveBigIntegerField()
    manifest_sequence = models.PositiveBigIntegerField()
    credential_public_id = models.CharField(max_length=32)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    outcome = models.CharField(max_length=16, choices=Outcome)
    safe_result_code = models.CharField(max_length=80)
    credential = models.ForeignKey(
        Credential,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offline_operations",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        verbose_name = "offline check-in operation"
        verbose_name_plural = "offline check-in operations"
        ordering = ("device_id", "device_sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("device", "operation_id"),
                name="offline_operation_idempotency_unique",
            ),
            models.UniqueConstraint(
                fields=("device", "device_sequence"),
                name="offline_device_sequence_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "outcome", "received_at"),
                name="accred_offline_conflict_idx",
            )
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
                "Offline check-in evidence is append-only.",
                code="immutable_offline_operation",
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
            "Offline check-in evidence is append-only.",
            code="protected_offline_operation",
        )
