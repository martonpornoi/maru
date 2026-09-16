"""Retained setup evidence; schema availability does not activate Programme."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel

if TYPE_CHECKING:
    from collections.abc import Iterable


class ProgrammeAdoptionSetupReceipt(UUIDTimeStampedModel):
    """Retain one atomic setup result, never invitation or operational authority.

    Cross-owner foreign keys preserve evidence identity. Owning commands and
    native guards, not ORM traversal, establish scope and current admission.
    No current command or runtime database writer can create this dormant row.
    """

    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipt",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipts",
    )
    series = models.ForeignKey(
        "organizations.ConventionSeries",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipts",
    )
    department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipts",
    )
    representation = models.ForeignKey(
        "organizations.OrganizationRepresentation",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_setup_receipts",
    )
    source_audit = models.OneToOneField(
        "audit.AuditEvent",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipt",
    )
    edition_creation = models.OneToOneField(
        "events.EditionCreationReceipt",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipt",
    )
    department_creation = models.OneToOneField(
        "workforce.EditionStructureCommandReceipt",
        on_delete=models.PROTECT,
        related_name="programme_setup_receipt",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    mode = models.CharField(
        max_length=40,
        choices=(
            ("new_foundation", "Create organization, series and edition"),
            ("existing_organization", "Reuse an organization"),
            ("existing_series", "Reuse an organization and series"),
        ),
    )
    foundation_fingerprint = models.CharField(max_length=64, blank=True)
    representation_version = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=240)

    class Meta:
        """Bind one result to one actor's original key and one new edition."""

        ordering = ("created_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                name="programme_setup_actor_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(representation_version__gte=1),
                name="programme_setup_representation_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(mode="new_foundation", foundation_fingerprint="")
                    | models.Q(
                        mode__in=("existing_organization", "existing_series"),
                        foundation_fingerprint__regex=r"^[0-9a-f]{64}$",
                    )
                ),
                name="programme_setup_mode_source_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="programme_setup_request_digest_shape",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="programme_setup_reason_nonempty",
            ),
        ]

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate local facts without reading other owners through relations.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Additional local fields excluded by Django's caller.
        validate_unique : bool, default=True
            Whether to validate local uniqueness.
        validate_constraints : bool, default=True
            Whether to validate declared local constraints.
        """
        super().full_clean(
            exclude=set(exclude or ())
            | {
                "edition",
                "organization",
                "series",
                "department",
                "representation",
                "actor",
                "source_audit",
                "edition_creation",
                "department_creation",
            },
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject ORM writes until an accepted setup command owns persistence.

        Parameters
        ----------
        *args : Any
            Unused Django arguments; no current writer is mounted.
        **kwargs : Any
            Unused Django options; no current writer is mounted.

        Raises
        ------
        ValidationError
            Always, because setup persistence is dormant and receipts are retained.
        """
        del args, kwargs
        raise ValidationError(
            "Programme setup receipts require an accepted setup command."
        )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of accountable setup history.

        Parameters
        ----------
        *args : Any
            Unused Django deletion arguments.
        **kwargs : Any
            Unused Django deletion options.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable Django result; setup evidence is retained.

        Raises
        ------
        ValidationError
            Always, because setup evidence cannot be deleted.
        """
        del args, kwargs
        raise ValidationError("Programme setup receipts are retained.")
