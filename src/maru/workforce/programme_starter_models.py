"""Workforce-owned retained approval of fixed shared Volunteer template meaning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel
from maru.workforce.programme_starter_writer import _require_programme_starter_writer

if TYPE_CHECKING:
    from collections.abc import Iterable


class _ProgrammeStarterEvidence(UUIDTimeStampedModel):
    """Keep original retry and actual-person audit evidence in both record types."""

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
        """Share only this purpose-specific immutable evidence boundary."""

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
        """Append only in the owning command; retained evidence is never edited.

        Parameters
        ----------
        *args : Any
            Django insertion arguments after checking the writer boundary.
        **kwargs : Any
            Django insertion options after checking immutable evidence.

        Raises
        ------
        ValidationError
            Outside the owning append scope or when attempting an update.
        """
        _require_programme_starter_writer()
        if not self._state.adding:
            raise ValidationError("Programme starter evidence is retained.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Keep original intent and terminal evidence, including cancellation.

        Parameters
        ----------
        *args : Any
            Unused Django deletion arguments.
        **kwargs : Any
            Unused Django deletion options.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable Django result; retained evidence cannot be deleted.

        Raises
        ------
        ValidationError
            Always; cancellation appends a terminal decision.
        """
        del args, kwargs
        raise ValidationError("Programme starter evidence is retained.")


class ProgrammeStarterRequest(_ProgrammeStarterEvidence):
    """Retain one ordinary controller's exact fixed-template proposal."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    series = models.ForeignKey(
        "organizations.ConventionSeries", on_delete=models.PROTECT
    )
    edition = models.ForeignKey("events.EventEdition", on_delete=models.PROTECT)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_programme_starter_requests",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_programme_starter_requests",
    )
    definition_code = models.CharField(max_length=80)
    definition_version = models.PositiveIntegerField()
    definition_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest.")],
    )
    requested_at = models.DateTimeField()
    approval_deadline = models.DateTimeField()

    class Meta:
        """Keep one author/key, two distinct people and the sole admitted version."""

        ordering = ("requested_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("author", "idempotency_key"),
                name="wrk_starter_request_author_key",
            ),
            models.CheckConstraint(
                condition=~models.Q(author=models.F("approver")),
                name="wrk_starter_request_independent",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    definition_code="workforce-volunteer", definition_version=1
                ),
                name="wrk_starter_request_definition",
            ),
            models.CheckConstraint(
                condition=models.Q(approval_deadline__gt=models.F("requested_at")),
                name="wrk_starter_request_deadline",
            ),
        ]


class ProgrammeStarterDecision(_ProgrammeStarterEvidence):
    """Retain one person's own terminal action and only the exact approved meaning."""

    request = models.OneToOneField(
        ProgrammeStarterRequest, on_delete=models.PROTECT, related_name="decision"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_starter_decisions",
    )
    action = models.CharField(
        max_length=16,
        choices=(("approve", "Approve"), ("decline", "Decline"), ("cancel", "Cancel")),
    )
    decided_at = models.DateTimeField()
    template = models.ForeignKey(
        "workforce.PositionTemplate", on_delete=models.PROTECT, null=True, blank=True
    )
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle", on_delete=models.PROTECT, null=True, blank=True
    )
    created_output = models.BooleanField(default=False)

    class Meta:
        """Arbitrate terminal retries and forbid output-bearing decline/cancellation."""

        ordering = ("decided_at", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("actor", "idempotency_key"),
                name="wrk_starter_decision_actor_key",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action="approve", template__isnull=False, role_bundle__isnull=False
                )
                | models.Q(
                    action__in=("decline", "cancel"),
                    template__isnull=True,
                    role_bundle__isnull=True,
                    created_output=False,
                ),
                name="wrk_starter_decision_output",
            ),
        ]
