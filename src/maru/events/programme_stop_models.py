"""Immutable stop evidence, dormant until complete owner-native admission exists."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel
from maru.events.programme_stop_writer import _require_programme_stop_writer

if TYPE_CHECKING:
    from collections.abc import Iterable


class ProgrammeStopReceipt(UUIDTimeStampedModel):
    """Bind one terminal outcome to original intent, native transition and audit.

    Cross-owner references preserve identity, not traversal authority. The owning
    command rechecks the complete preview and all native stop guards. This model
    alone never changes lifecycle, revokes access or enables a stop action.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_stop_receipts",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_stop_receipt",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_stop_receipts",
    )
    transition = models.OneToOneField(
        "events.EditionLifecycleTransition",
        on_delete=models.PROTECT,
        related_name="programme_stop_receipt",
    )
    source_audit = models.OneToOneField(
        "audit.AuditEvent",
        on_delete=models.PROTECT,
        related_name="programme_stop_receipt",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    preview_fingerprint = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    previous_lifecycle = models.CharField(
        max_length=20,
        choices=[
            (state, state.title())
            for state in ("draft", "preparing", "ready", "live", "closing")
        ],
    )
    expected_aggregate_version = models.PositiveIntegerField()
    expected_lifecycle_version = models.PositiveIntegerField()
    impact_document = models.JSONField()
    reason = models.CharField(max_length=240)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Retain one exact actor/key outcome and one terminal edition receipt."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                name="programme_stop_actor_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_aggregate_version__gte=1),
                name="programme_stop_aggregate_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    previous_lifecycle__in=(
                        "draft",
                        "preparing",
                        "ready",
                        "live",
                        "closing",
                    )
                ),
                name="programme_stop_previous_state",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="programme_stop_request_digest",
            ),
            models.CheckConstraint(
                condition=models.Q(preview_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="programme_stop_preview_digest",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="programme_stop_reason_nonempty"
            ),
        ]

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate local shape without traversing another owner's private records.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Additional local fields excluded by the Django caller.
        validate_unique : bool, default=True
            Whether to validate local uniqueness.
        validate_constraints : bool, default=True
            Whether to validate declared local constraints.
        """
        super().full_clean(
            exclude=set(exclude or ())
            | {"organization", "edition", "actor", "transition", "source_audit"},
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Admit only first insertion inside the owning stop command scope.

        Parameters
        ----------
        *args : Any
            Django persistence arguments forwarded after admission.
        **kwargs : Any
            Django persistence options forwarded after admission.

        Raises
        ------
        ValidationError
            Outside the command scope or when rewriting retained stop history.
        """
        _require_programme_stop_writer()
        if not self._state.adding:
            raise ValidationError("Programme stop receipts are immutable.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse destructive removal of accountable stop history.

        Parameters
        ----------
        *args : Any
            Unused Django deletion arguments.
        **kwargs : Any
            Unused Django deletion options.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable Django result; stop evidence is retained.

        Raises
        ------
        ValidationError
            Always, because stop receipts cannot be deleted.
        """
        del args, kwargs
        raise ValidationError("Programme stop receipts are retained.")
