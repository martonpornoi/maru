"""Retained Programme approval intent and outcome, not operational role grants."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.authorization.catalog import ScopeLevel
from maru.core.models import UUIDTimeStampedModel

if TYPE_CHECKING:
    from collections.abc import Iterable


class _ProgrammeRoleEvidence(UUIDTimeStampedModel):
    """Share only the two approval records' retained retry and audit boundary."""

    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    reason = models.CharField(max_length=240)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    source_audit = models.OneToOneField(
        "audit.AuditEvent",
        on_delete=models.PROTECT,
        related_name="%(class)s_evidence",
    )

    class Meta:
        """Keep the shared evidence boundary abstract and purpose-specific."""

        abstract = True

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate local fields without traversing other owners' records.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Additional fields omitted by the Django caller.
        validate_unique : bool, default=True
            Whether to check applicable local uniqueness.
        validate_constraints : bool, default=True
            Whether to check applicable local constraints.
        """
        super().full_clean(
            exclude=set(exclude or ())
            | {field.name for field in self._meta.fields if field.is_relation},
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Refuse direct ORM persistence of dormant approval evidence.

        Parameters
        ----------
        *args : Any
            Unused Django persistence arguments.
        **kwargs : Any
            Unused Django persistence options.

        Raises
        ------
        ValidationError
            Always until the owning atomic approval commands are installed.
        """
        del args, kwargs
        raise ValidationError("Programme role evidence requires its owning command.")

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Retain original requests and decisions, including rejected proposals.

        Parameters
        ----------
        *args : Any
            Unused Django deletion arguments.
        **kwargs : Any
            Unused Django deletion options.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable Django result: evidence is retained.

        Raises
        ------
        ValidationError
            Always; cancellation appends a decision instead of deleting intent.
        """
        del args, kwargs
        raise ValidationError("Programme role evidence is retained.")


class ProgrammeRoleRequest(_ProgrammeRoleEvidence):
    """Retain exact scoped access proposed for a named person's own decision."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    programme_edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_role_requests",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="targeted_programme_role_requests",
    )
    department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    resource_binding = models.ForeignKey(
        "authorization.ScopedResourceBinding",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    scope_level = models.CharField(
        max_length=16,
        choices=tuple((level.value, level.name.title()) for level in ScopeLevel),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_programme_role_requests",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_programme_role_requests",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recipient_programme_role_requests",
    )
    recipe_code = models.CharField(max_length=64)
    recipe_version = models.PositiveIntegerField()
    recipe_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    requested_at = models.DateTimeField()
    approval_deadline = models.DateTimeField()
    not_before = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Fence original author/key, independent people and exact scope shapes."""

        ordering = ("requested_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("author", "idempotency_key"),
                name="programme_role_request_author_key",
            ),
            models.CheckConstraint(
                condition=~models.Q(approver=models.F("author"))
                & ~models.Q(approver=models.F("recipient")),
                name="programme_role_request_independent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope_level="organization",
                        edition__isnull=True,
                        department__isnull=True,
                        resource_binding__isnull=True,
                    )
                    | models.Q(
                        scope_level="edition",
                        edition__isnull=False,
                        department__isnull=True,
                        resource_binding__isnull=True,
                    )
                    | models.Q(
                        scope_level="department",
                        edition__isnull=False,
                        department__isnull=False,
                        resource_binding__isnull=True,
                    )
                    | models.Q(
                        scope_level="resource",
                        edition__isnull=False,
                        department__isnull=False,
                        resource_binding__isnull=False,
                    )
                ),
                name="programme_role_request_scope_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(edition__isnull=True)
                | models.Q(edition=models.F("programme_edition")),
                name="programme_role_request_context",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(not_before__isnull=True)
                | models.Q(expires_at__gt=models.F("not_before")),
                name="programme_role_request_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(approval_deadline__gt=models.F("requested_at")),
                name="programme_role_request_deadline",
            ),
            models.CheckConstraint(
                condition=models.Q(recipe_version__gte=1),
                name="programme_role_recipe_positive",
            ),
        ]


class ProgrammeRoleDecisionRecord(_ProgrammeRoleEvidence):
    """Retain one actual terminal decision and only its exact approved output."""

    request = models.OneToOneField(
        ProgrammeRoleRequest,
        on_delete=models.PROTECT,
        related_name="decision",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_role_decisions",
    )
    action = models.CharField(
        max_length=16,
        choices=(("approve", "Approve"), ("decline", "Decline"), ("cancel", "Cancel")),
    )
    decided_at = models.DateTimeField()
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    role_assignment = models.OneToOneField(
        "authorization.RoleAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="programme_approval_decision",
    )

    class Meta:
        """Permit no grant-bearing rejection or duplicate terminal retry key."""

        ordering = ("decided_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                name="programme_role_decision_actor_key",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action="approve",
                    role_bundle__isnull=False,
                    role_assignment__isnull=False,
                )
                | models.Q(
                    action__in=("decline", "cancel"),
                    role_bundle__isnull=True,
                    role_assignment__isnull=True,
                ),
                name="programme_role_decision_output",
            ),
        ]
