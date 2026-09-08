"""Owned Scheduling identities, immutable manifests and minimized evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel

from .catalogs import (
    MAX_REASON_LENGTH,
    MAX_SOURCE_CHANNEL_LENGTH,
    MAX_TITLE_LENGTH,
    CandidateLifecycle,
    SchedulingCapacityMode,
    SchedulingConflictCode,
    SchedulingConflictSeverity,
    SchedulingLifecycle,
    SchedulingOperation,
    scheduling_choices,
    scheduling_values,
)
from .writer_boundary import require_scheduling_writer

if TYPE_CHECKING:
    from collections.abc import Iterable

_OWNER_RELATIONS = frozenset(
    {
        "organization",
        "edition",
        "actor",
        "created_by",
        "last_modified_by",
        "programme_item",
        "space_selection",
        "host_relationship",
        "command_receipt",
        "previous_booking",
        "venue_receipt",
    }
)
_DIGEST_VALIDATOR = RegexValidator(
    r"^[0-9a-f]{64}\Z", "Use a lower-case SHA-256 digest."
)


class _SchedulingModel(UUIDTimeStampedModel):
    """Enforce the owner ORM boundary without dereferencing foreign models."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="scheduling_%(class)s_rows",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="scheduling_%(class)s_rows",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate local fields; owner contracts and SQL prove foreign scope.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Additional fields excluded by the caller.
        validate_unique : bool, default=True
            Whether to validate local uniqueness.
        validate_constraints : bool, default=True
            Whether to validate local model constraints.
        """
        super().full_clean(
            exclude=set(exclude or ()) | _OWNER_RELATIONS,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist only inside the closed command writer scope.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.
        """
        require_scheduling_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Retain Scheduling history instead of allowing direct deletion.

        Parameters
        ----------
        *args : Any
            Ignored Django arguments.
        **kwargs : Any
            Ignored Django keyword arguments.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's unreachable deletion-result shape.

        Raises
        ------
        ValidationError
            Always; records use explicit lifecycle commands.
        """
        del args, kwargs
        raise ValidationError("Scheduling history is retained; use lifecycle commands.")


class _ImmutableSchedulingModel(_SchedulingModel):
    """Reject ORM updates to retained revision and evidence rows."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert one immutable row and reject any later update.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the owner boundary.
        **kwargs : Any
            Keyword arguments forwarded to the owner boundary.

        Raises
        ------
        ValidationError
            If this row was already persisted.
        """
        if not self._state.adding:
            raise ValidationError("Scheduling evidence is append-only.")
        super().save(*args, **kwargs)


class _AttributedSchedulingEvidence(_ImmutableSchedulingModel):
    """Retain the exact actor, time and private rationale for an owned change."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="scheduling_%(class)s_actions",
    )
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=MAX_REASON_LENGTH)

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True


class SchedulingEditionControl(_SchedulingModel):
    """Serialize one edition's owned commands and immutable receipt sequence."""

    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="scheduling_control",
    )
    aggregate_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="sch_control_version_positive",
            )
        ]


class SchedulingServiceDay(_SchedulingModel):
    """Stable identity whose latest immutable revision owns its day window."""

    aggregate_version = models.PositiveBigIntegerField()
    lifecycle = models.CharField(
        max_length=16,
        choices=scheduling_choices(SchedulingLifecycle),
        default=SchedulingLifecycle.ACTIVE.value,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    aggregate_version__gt=0,
                    lifecycle__in=scheduling_values(SchedulingLifecycle),
                ),
                name="sch_day_version_positive",
            )
        ]


class SchedulingServiceDayRevision(_AttributedSchedulingEvidence):
    """An explicit overnight-capable day window and anchored minute grid."""

    day = models.ForeignKey(
        SchedulingServiceDay, on_delete=models.PROTECT, related_name="revisions"
    )
    sequence = models.PositiveBigIntegerField()
    label = models.CharField(max_length=MAX_TITLE_LENGTH)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    precision_minutes = models.PositiveSmallIntegerField()
    edition_version = models.PositiveBigIntegerField()
    lifecycle = models.CharField(
        max_length=16,
        choices=scheduling_choices(SchedulingLifecycle),
        default=SchedulingLifecycle.ACTIVE.value,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("day_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("day", "sequence"), name="sch_day_revision_sequence_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sequence__gt=0,
                    edition_version__gt=0,
                    ends_at__gt=models.F("starts_at"),
                    precision_minutes__in=(1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60),
                    lifecycle__in=scheduling_values(SchedulingLifecycle),
                )
                & ~models.Q(label="")
                & ~models.Q(reason=""),
                name="sch_day_revision_shape",
            ),
        ]


class SchedulingOccurrence(_SchedulingModel):
    """Stable Programme occurrence retained across alternatives and reservations."""

    programme_item = models.ForeignKey(
        "programme.ProgrammeItem",
        on_delete=models.PROTECT,
        related_name="scheduling_occurrences",
    )
    aggregate_version = models.PositiveBigIntegerField()
    lifecycle = models.CharField(
        max_length=16,
        choices=scheduling_choices(SchedulingLifecycle),
        default=SchedulingLifecycle.ACTIVE.value,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    aggregate_version__gt=0,
                    lifecycle__in=scheduling_values(SchedulingLifecycle),
                ),
                name="sch_occurrence_shape",
            )
        ]


class SchedulingOccurrenceRevision(_AttributedSchedulingEvidence):
    """Immutable grouping and lifecycle metadata, never an implicit recurrence."""

    occurrence = models.ForeignKey(
        SchedulingOccurrence, on_delete=models.PROTECT, related_name="revisions"
    )
    sequence = models.PositiveBigIntegerField()
    group_key = models.UUIDField(null=True, blank=True)
    group_sequence = models.PositiveIntegerField(null=True, blank=True)
    lifecycle = models.CharField(
        max_length=16, choices=scheduling_choices(SchedulingLifecycle)
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("occurrence_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("occurrence", "sequence"), name="sch_occurrence_revision_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sequence__gt=0, lifecycle__in=scheduling_values(SchedulingLifecycle)
                )
                & (
                    (models.Q(group_key__isnull=True, group_sequence__isnull=True))
                    | models.Q(
                        group_key__isnull=False,
                        group_sequence__isnull=False,
                        group_sequence__gt=0,
                    )
                )
                & ~models.Q(reason=""),
                name="sch_occurrence_revision_shape",
            ),
        ]


class SchedulingCandidate(_SchedulingModel):
    """A private draft or retained archive, never an approval or released schedule."""

    aggregate_version = models.PositiveBigIntegerField()
    lifecycle = models.CharField(
        max_length=16,
        choices=scheduling_choices(CandidateLifecycle),
        default=CandidateLifecycle.DRAFT.value,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="scheduling_candidates_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    aggregate_version__gt=0,
                    lifecycle__in=scheduling_values(CandidateLifecycle),
                ),
                name="sch_candidate_shape",
            )
        ]


class SchedulingCandidateRevision(_AttributedSchedulingEvidence):
    """Complete immutable placement manifest with explicit copy/restore provenance."""

    candidate = models.ForeignKey(
        SchedulingCandidate, on_delete=models.PROTECT, related_name="revisions"
    )
    sequence = models.PositiveBigIntegerField()
    label = models.CharField(max_length=MAX_TITLE_LENGTH)
    operation = models.CharField(
        max_length=32, choices=scheduling_choices(SchedulingOperation)
    )
    source_revision = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derived_revisions",
    )
    placement_count = models.PositiveIntegerField()
    manifest_digest = models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR])

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("candidate_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("candidate", "sequence"), name="sch_candidate_revision_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sequence__gt=0,
                    placement_count__lte=2_000,
                    operation__in=scheduling_values(SchedulingOperation),
                )
                & ~models.Q(label="")
                & ~models.Q(reason=""),
                name="sch_candidate_revision_shape",
            ),
        ]


class SchedulingPlacementRevision(_ImmutableSchedulingModel):
    """One immutable room proposal reusable by several candidate manifests."""

    introduced_in = models.ForeignKey(
        SchedulingCandidateRevision,
        on_delete=models.PROTECT,
        related_name="introduced_placements",
    )
    occurrence_revision = models.ForeignKey(
        SchedulingOccurrenceRevision,
        on_delete=models.PROTECT,
        related_name="placements",
    )
    day_revision = models.ForeignKey(
        SchedulingServiceDayRevision,
        on_delete=models.PROTECT,
        related_name="placements",
    )
    space_selection = models.ForeignKey(
        "venues.EditionSpaceSelection",
        on_delete=models.PROTECT,
        related_name="scheduling_placements",
    )
    capacity_mode = models.CharField(
        max_length=16, choices=scheduling_choices(SchedulingCapacityMode)
    )
    expected_attendance = models.PositiveIntegerField()
    setup_starts_at = models.DateTimeField()
    effective_starts_at = models.DateTimeField()
    effective_ends_at = models.DateTimeField()
    teardown_ends_at = models.DateTimeField()
    host_presence_count = models.PositiveSmallIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    expected_attendance__gt=0,
                    host_presence_count__lte=100,
                    capacity_mode__in=scheduling_values(SchedulingCapacityMode),
                    setup_starts_at__lte=models.F("effective_starts_at"),
                    effective_starts_at__lt=models.F("effective_ends_at"),
                    effective_ends_at__lte=models.F("teardown_ends_at"),
                ),
                name="sch_placement_envelope_shape",
            )
        ]


class SchedulingCandidateMember(_ImmutableSchedulingModel):
    """Explicit manifest membership prevents an edit from mutating another draft."""

    revision = models.ForeignKey(
        SchedulingCandidateRevision, on_delete=models.PROTECT, related_name="members"
    )
    placement = models.ForeignKey(
        SchedulingPlacementRevision,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    occurrence = models.ForeignKey(
        SchedulingOccurrence,
        on_delete=models.PROTECT,
        related_name="candidate_memberships",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("revision_id", "occurrence_id")
        constraints = [
            models.UniqueConstraint(
                fields=("revision", "occurrence"), name="sch_manifest_occurrence_uq"
            ),
            models.UniqueConstraint(
                fields=("revision", "placement"), name="sch_manifest_placement_uq"
            ),
        ]


class SchedulingPlacementHostPresence(_ImmutableSchedulingModel):
    """Required work presence, not a copied personal availability window."""

    placement = models.ForeignKey(
        SchedulingPlacementRevision,
        on_delete=models.PROTECT,
        related_name="host_presences",
    )
    host_relationship = models.ForeignKey(
        "programme.ProgrammeHostRelationship",
        on_delete=models.PROTECT,
        related_name="scheduling_presences",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("placement", "host_relationship"), name="sch_placement_host_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="sch_host_presence_positive",
            ),
        ]


class SchedulingEvaluation(_AttributedSchedulingEvidence):
    """Minimized point-in-time dependency proof, not candidate approval."""

    revision = models.ForeignKey(
        SchedulingCandidateRevision,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )
    dependency_digest = models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR])
    source_evidence = models.JSONField(default=list)
    conflict_count = models.PositiveIntegerField()
    is_complete = models.BooleanField()


class SchedulingConflict(_ImmutableSchedulingModel):
    """Closed explainable outcome without source content or private calendars."""

    evaluation = models.ForeignKey(
        SchedulingEvaluation, on_delete=models.PROTECT, related_name="conflicts"
    )
    occurrence = models.ForeignKey(
        SchedulingOccurrence,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="conflicts",
    )
    other_occurrence = models.ForeignKey(
        SchedulingOccurrence,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="peer_conflicts",
    )
    source_code = models.CharField(max_length=100)
    code = models.CharField(
        max_length=64, choices=scheduling_choices(SchedulingConflictCode)
    )
    severity = models.CharField(
        max_length=16, choices=scheduling_choices(SchedulingConflictSeverity)
    )
    fingerprint = models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR])

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("evaluation", "fingerprint"), name="sch_conflict_fingerprint_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    severity__in=scheduling_values(SchedulingConflictSeverity)
                ),
                name="sch_conflict_severity_closed",
            ),
        ]


class SchedulingWarningAcknowledgement(_AttributedSchedulingEvidence):
    """An explicit reason for one exact warning under unchanged dependencies."""

    conflict = models.OneToOneField(
        SchedulingConflict, on_delete=models.PROTECT, related_name="acknowledgement"
    )


class SchedulingReservationIntent(_AttributedSchedulingEvidence):
    """Exact in-transaction physical intent, completed by reciprocal owner receipts."""

    command_receipt = models.OneToOneField(
        "SchedulingCommandReceipt",
        on_delete=models.PROTECT,
        related_name="reservation_intent",
    )
    venue_receipt = models.OneToOneField(
        "venues.VenueCommandReceipt",
        on_delete=models.PROTECT,
        related_name="scheduling_reservation_intent",
    )
    candidate_revision = models.ForeignKey(
        SchedulingCandidateRevision,
        on_delete=models.PROTECT,
        related_name="reservation_intents",
    )
    occurrence = models.ForeignKey(
        SchedulingOccurrence,
        on_delete=models.PROTECT,
        related_name="reservation_intents",
    )
    placement = models.ForeignKey(
        SchedulingPlacementRevision,
        on_delete=models.PROTECT,
        related_name="reservation_intents",
    )
    operation = models.CharField(
        max_length=32,
        choices=(
            (SchedulingOperation.RESERVATION_REPLACE.value, "Replace reservation"),
            (SchedulingOperation.RESERVATION_CANCEL.value, "Cancel reservation"),
        ),
    )
    previous_booking = models.ForeignKey(
        "venues.VenueBooking",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="scheduling_successor_intents",
    )
    expected_booking_version = models.PositiveBigIntegerField(default=0)
    # Reserved future identity, like Applications' accepted conversion source;
    # the reciprocal Venue binding and deferred guards complete it atomically.
    target_booking_id = models.UUIDField(null=True, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(previous_booking__isnull=True, expected_booking_version=0)
                    | models.Q(
                        previous_booking__isnull=False, expected_booking_version__gt=0
                    )
                )
                & (
                    models.Q(
                        operation="reservation_replace", target_booking_id__isnull=False
                    )
                    | models.Q(
                        operation="reservation_cancel",
                        target_booking_id__isnull=True,
                        previous_booking__isnull=False,
                    )
                ),
                name="sch_reservation_intent_shape",
            ),
        ]


class SchedulingCommandReceipt(_AttributedSchedulingEvidence):
    """One immutable retry and evidence record for each control-version increment."""

    operation = models.CharField(
        max_length=32, choices=scheduling_choices(SchedulingOperation)
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=[_DIGEST_VALIDATOR])
    control_version = models.PositiveBigIntegerField()
    result_object_id = models.UUIDField()
    resulting_version = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=MAX_SOURCE_CHANNEL_LENGTH)

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "idempotency_key"),
                name="sch_command_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("edition", "control_version"), name="sch_command_version_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    control_version__gt=0,
                    resulting_version__gt=0,
                    operation__in=scheduling_values(SchedulingOperation),
                )
                & ~models.Q(reason=""),
                name="sch_command_receipt_shape",
            ),
        ]
