"""Private Programme aggregates, layered evidence, and public renditions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from maru.core.models import UUIDTimeStampedModel

from .catalogs import (
    MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
    MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
    MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
    MAX_PROGRAMME_REASON_LENGTH,
    MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH,
    MAX_PROGRAMME_SOURCE_CODE_LENGTH,
    MAX_PROGRAMME_SUMMARY_LENGTH,
    MAX_PROGRAMME_TITLE_LENGTH,
    PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS,
    PROGRAMME_ITEM_SOURCE_DEFINITIONS,
    ProgrammeCommandOperation,
    ProgrammeItemKind,
    ProgrammeItemLifecycle,
    ProgrammeProvenanceKind,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
    text_choices,
)
from .writer_boundary import require_programme_writer

if TYPE_CHECKING:
    from collections.abc import Iterable

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}\Z",
    message="Use a lower-case SHA-256 digest.",
    code="invalid_programme_digest",
)
_SOURCE_CHANNEL_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_-]*\Z",
    message="Use a registered lower-case source channel.",
    code="invalid_programme_source_channel",
)

_OWNER_MANAGED_RELATION_FIELDS = frozenset(
    {
        "actor",
        "created_by",
        "edition",
        "last_modified_by",
        "organization",
        "reviewed_by",
    }
)


class _ClosedProgrammeModel(UUIDTimeStampedModel):
    """Reject ORM writes that bypass a registered Programme command."""

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
        """Validate Programme-owned fields without loading owner models.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Additional model fields the caller does not want to validate.
        validate_unique : bool, default=True
            Whether to run Django's model-level uniqueness validation.
        validate_constraints : bool, default=True
            Whether to run Django's model-level constraint validation.

        Notes
        -----
        Identity, Events, and Organizations own the referenced account and
        scope records. Commands resolve those records through their public
        query seams, and PostgreSQL guards enforce persisted coherence. Model
        validation therefore excludes those foreign relations instead of
        fetching another bounded context's private model objects.
        """
        excluded_fields = set(exclude or ())
        excluded_fields.update(_OWNER_MANAGED_RELATION_FIELDS)
        super().full_clean(
            exclude=excluded_fields,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist through the closed writer boundary.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.
        """
        require_programme_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Reject direct deletion of retained Programme records.

        Parameters
        ----------
        *args : Any
            Ignored positional arguments.
        **kwargs : Any
            Ignored keyword arguments.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's deletion shape, which is never reached.

        Raises
        ------
        ValidationError
            Always, because Programme records use lifecycle commands.
        """
        del args, kwargs
        raise ValidationError(
            "Programme records are retained; use a lifecycle command.",
            code="protected_programme_record",
        )


class _AppendOnlyProgrammeModel(_ClosedProgrammeModel):
    """Reject updates to immutable Programme history and renditions."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Create one immutable record and reject later updates.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.

        Raises
        ------
        ValidationError
            If the record was already persisted.
        """
        if not self._state.adding:
            raise ValidationError(
                "Programme history is append-only.",
                code="immutable_programme_history",
            )
        super().save(*args, **kwargs)


class ProgrammeEditionControl(_ClosedProgrammeModel):
    """Edition-scoped lock and version for canonical item creation."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_edition_controls",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_control",
    )
    aggregate_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "edition_id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="programme_control_version_pos",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition"),
                name="programme_control_scope_idx",
            )
        ]


class ProgrammeItem(_ClosedProgrammeModel):
    """Canonical private item identity with no layer-specific prose."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_items",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_items",
    )
    kind = models.CharField(
        max_length=32,
        choices=text_choices(ProgrammeItemKind),
    )
    provenance_kind = models.CharField(
        max_length=32,
        choices=text_choices(ProgrammeProvenanceKind),
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=text_choices(ProgrammeItemLifecycle),
        default=ProgrammeItemLifecycle.ACTIVE.value,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_items_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_items_modified",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="programme_item_version_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=tuple(member.value for member in ProgrammeItemKind)
                ),
                name="programme_item_kind_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    provenance_kind__in=tuple(
                        member.value for member in ProgrammeProvenanceKind
                    )
                ),
                name="programme_item_provenance_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    lifecycle__in=tuple(
                        member.value for member in ProgrammeItemLifecycle
                    )
                ),
                name="programme_item_lifecycle_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "lifecycle"),
                name="programme_item_scope_idx",
            )
        ]

    def __str__(self) -> str:
        """Return a private title-free label for this item.

        Returns
        -------
        str
            Stable kind and UUID label.
        """
        return f"{self.kind} Programme item {self.id}"


class ProgrammeItemSourceBinding(_AppendOnlyProgrammeModel):
    """Exact structural provenance for every canonical Programme item."""

    item = models.OneToOneField(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="source_binding",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_item_source_bindings",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_item_source_bindings",
    )
    binding_code = models.CharField(
        max_length=MAX_PROGRAMME_SOURCE_CODE_LENGTH,
        choices=tuple((code, code) for code in PROGRAMME_ITEM_SOURCE_DEFINITIONS),
    )
    source_object_id = models.UUIDField(null=True, blank=True)
    source_version = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "item_id")
        constraints = [
            models.UniqueConstraint(
                fields=("binding_code", "source_object_id"),
                condition=models.Q(source_object_id__isnull=False),
                name="programme_item_source_object_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        binding_code="programme.source.organizer-core@1",
                        source_object_id__isnull=True,
                        source_version__isnull=True,
                    )
                    | models.Q(
                        binding_code="programme.source.applications-accepted@1",
                        source_object_id__isnull=False,
                        source_version__gt=0,
                    )
                ),
                name="programme_item_source_shape",
            ),
        ]

    def clean(self) -> None:
        """Require exact scope, provenance, and source-reference shape.

        Raises
        ------
        ValidationError
            If this binding is free-form or outside the item's scope.
        """
        super().clean()
        item = self.item if self.item_id else None
        if item is not None and (
            item.organization_id != self.organization_id
            or item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme provenance must remain in the item's exact scope.",
                code="programme_source_scope_mismatch",
            )
        definition = PROGRAMME_ITEM_SOURCE_DEFINITIONS.get(self.binding_code)
        if definition is None:
            raise ValidationError(
                {"binding_code": "Choose a registered Programme item source."}
            )
        if item is not None and item.provenance_kind != definition.provenance_kind:
            raise ValidationError(
                "Programme provenance kind must match its structural source.",
                code="programme_source_provenance_mismatch",
            )
        has_object = self.source_object_id is not None
        has_version = self.source_version is not None and self.source_version > 0
        if definition.requires_object != (has_object and has_version):
            raise ValidationError(
                "Programme source references must use the registered shape.",
                code="programme_source_shape_invalid",
            )
        if not definition.requires_object and (
            self.source_object_id is not None or self.source_version is not None
        ):
            raise ValidationError(
                "Organizer-core provenance cannot carry an external identity.",
                code="programme_source_identity_forbidden",
            )


class ProgrammeWorkingRevision(_AppendOnlyProgrammeModel):
    """Private Programme-department copy under active development."""

    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="working_revisions",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_working_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_working_revisions",
    )
    sequence = models.PositiveBigIntegerField()
    item_version = models.PositiveBigIntegerField()
    internal_title = models.CharField(max_length=MAX_PROGRAMME_TITLE_LENGTH)
    working_summary = models.TextField(
        max_length=MAX_PROGRAMME_SUMMARY_LENGTH,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_working_revisions_authored",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("item_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "sequence"),
                name="programme_working_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("item", "item_version"),
                name="programme_working_item_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0, item_version__gt=0),
                name="programme_working_versions_pos",
            ),
            models.CheckConstraint(
                condition=~models.Q(internal_title="") & ~models.Q(reason=""),
                name="programme_working_evidence_required",
            ),
        ]

    def clean(self) -> None:
        """Require this revision to remain in its item's exact scope.

        Raises
        ------
        ValidationError
            If the duplicated organizer or edition differs from the item.
        """
        super().clean()
        if self.item_id and (
            self.item.organization_id != self.organization_id
            or self.item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme working copy must remain in its item's exact scope.",
                code="programme_working_scope_mismatch",
            )


class ProgrammeDeliveryRevision(_AppendOnlyProgrammeModel):
    """Private operational delivery facts kept separate from working copy."""

    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="delivery_revisions",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_delivery_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_delivery_revisions",
    )
    sequence = models.PositiveBigIntegerField()
    item_version = models.PositiveBigIntegerField()
    technical_requirements = models.TextField(
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        blank=True,
    )
    accessibility_delivery = models.TextField(
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        blank=True,
    )
    media_consent_notes = models.TextField(
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_delivery_revisions_authored",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("item_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "sequence"),
                name="programme_delivery_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("item", "item_version"),
                name="programme_delivery_item_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0, item_version__gt=0),
                name="programme_delivery_versions_pos",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(technical_requirements="")
                    | ~models.Q(accessibility_delivery="")
                    | ~models.Q(media_consent_notes="")
                )
                & ~models.Q(reason=""),
                name="programme_delivery_evidence_required",
            ),
        ]

    def clean(self) -> None:
        """Require this revision to remain in its item's exact scope.

        Raises
        ------
        ValidationError
            If the duplicated organizer or edition differs from the item.
        """
        super().clean()
        if self.item_id and (
            self.item.organization_id != self.organization_id
            or self.item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme delivery facts must remain in the item's exact scope.",
                code="programme_delivery_scope_mismatch",
            )
        if not any(
            (
                self.technical_requirements,
                self.accessibility_delivery,
                self.media_consent_notes,
            )
        ):
            raise ValidationError(
                "Record at least one delivery fact.",
                code="programme_delivery_empty",
            )


class ProgrammeDepartmentDiscussionEntry(_AppendOnlyProgrammeModel):
    """Private Programme-department discussion retained apart from content."""

    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="department_discussion_entries",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_department_discussion_entries",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_department_discussion_entries",
    )
    sequence = models.PositiveBigIntegerField()
    item_version = models.PositiveBigIntegerField()
    body = models.TextField(max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_department_discussion_entries_authored",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("item_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "sequence"),
                name="programme_discussion_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("item", "item_version"),
                name="programme_discussion_item_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0, item_version__gt=0)
                & ~models.Q(body="")
                & ~models.Q(reason=""),
                name="programme_discussion_evidence_required",
            ),
        ]

    def clean(self) -> None:
        """Require this entry to remain in its item's exact scope.

        Raises
        ------
        ValidationError
            If the duplicated organizer or edition differs from the item.
        """
        super().clean()
        if self.item_id and (
            self.item.organization_id != self.organization_id
            or self.item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme discussion must remain in the item's exact scope.",
                code="programme_discussion_scope_mismatch",
            )


class ProgrammeReadinessRequirement(_ClosedProgrammeModel):
    """Current applicability and version cursor for one readiness concern."""

    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="readiness_requirements",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirements",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirements",
    )
    concern = models.CharField(
        max_length=32,
        choices=text_choices(ProgrammeReadinessConcern),
    )
    disposition = models.CharField(
        max_length=24,
        choices=text_choices(ProgrammeReadinessDisposition),
    )
    requirement_version = models.PositiveBigIntegerField(default=1, editable=False)
    dependency_version = models.PositiveBigIntegerField(default=0, editable=False)
    item_version = models.PositiveBigIntegerField(editable=False)
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirements_modified",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("item_id", "concern", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "concern"),
                name="programme_readiness_concern_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    concern__in=tuple(
                        member.value for member in ProgrammeReadinessConcern
                    )
                ),
                name="programme_readiness_concern_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    disposition__in=tuple(
                        member.value for member in ProgrammeReadinessDisposition
                    )
                ),
                name="programme_readiness_disposition_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    requirement_version__gt=0,
                    dependency_version__gte=0,
                    item_version__gt=0,
                ),
                name="programme_readiness_versions_valid",
            ),
        ]

    def clean(self) -> None:
        """Require this concern to remain in its item's exact scope.

        Raises
        ------
        ValidationError
            If the duplicated organizer or edition differs from the item.
        """
        super().clean()
        if self.item_id and (
            self.item.organization_id != self.organization_id
            or self.item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme readiness must remain in the item's exact scope.",
                code="programme_readiness_scope_mismatch",
            )


class ProgrammeReadinessRequirementRevision(_AppendOnlyProgrammeModel):
    """Append-only explanation for one readiness requirement revision."""

    requirement = models.ForeignKey(
        ProgrammeReadinessRequirement,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="readiness_requirement_revisions",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirement_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirement_revisions",
    )
    sequence = models.PositiveBigIntegerField()
    item_version = models.PositiveBigIntegerField()
    disposition = models.CharField(
        max_length=24,
        choices=text_choices(ProgrammeReadinessDisposition),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_readiness_requirement_revisions_authored",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("requirement_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("requirement", "sequence"),
                name="programme_requirement_revision_sequence_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0, item_version__gt=0)
                & ~models.Q(reason=""),
                name="programme_requirement_revision_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    disposition__in=tuple(
                        member.value for member in ProgrammeReadinessDisposition
                    )
                ),
                name="programme_requirement_revision_closed",
            ),
        ]

    def clean(self) -> None:
        """Require exact requirement, item, organizer, and edition scope.

        Raises
        ------
        ValidationError
            If this revision is not attached to its exact requirement scope.
        """
        super().clean()
        requirement = self.requirement if self.requirement_id else None
        if requirement is not None and (
            requirement.item_id != self.item_id
            or requirement.organization_id != self.organization_id
            or requirement.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Requirement history must remain in its exact readiness scope.",
                code="programme_requirement_revision_scope_mismatch",
            )


class ProgrammeReadinessEvidence(_AppendOnlyProgrammeModel):
    """Version-bound evidence for one Programme readiness concern."""

    requirement = models.ForeignKey(
        ProgrammeReadinessRequirement,
        on_delete=models.PROTECT,
        related_name="evidence_entries",
    )
    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="readiness_evidence",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_readiness_evidence",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_readiness_evidence",
    )
    sequence = models.PositiveBigIntegerField()
    item_version = models.PositiveBigIntegerField()
    requirement_version = models.PositiveBigIntegerField()
    dependency_version = models.PositiveBigIntegerField()
    state = models.CharField(
        max_length=16,
        choices=text_choices(ProgrammeReadinessEvidenceState),
    )
    source_code = models.CharField(
        max_length=MAX_PROGRAMME_SOURCE_CODE_LENGTH,
        choices=tuple((code, code) for code in PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS),
    )
    source_object_id = models.UUIDField(null=True, blank=True)
    source_version = models.PositiveBigIntegerField(null=True, blank=True)
    evidence_note = models.TextField(
        max_length=MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_readiness_evidence_authored",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("requirement_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("requirement", "sequence"),
                name="programme_readiness_evidence_sequence_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sequence__gt=0,
                    item_version__gt=0,
                    requirement_version__gt=0,
                    dependency_version__gte=0,
                )
                & ~models.Q(reason=""),
                name="programme_readiness_evidence_versions_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=tuple(
                        member.value for member in ProgrammeReadinessEvidenceState
                    )
                ),
                name="programme_readiness_evidence_state_closed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_code="programme.evidence.operator-attestation@1",
                        source_object_id__isnull=True,
                        source_version__isnull=True,
                    )
                    | models.Q(
                        source_code__in=(
                            "programme.evidence.public-rendition@1",
                            "programme.evidence.working-revision@1",
                            "programme.evidence.delivery-revision@1",
                        ),
                        source_object_id__isnull=False,
                        source_version__gt=0,
                    )
                ),
                name="programme_readiness_evidence_source_shape",
            ),
        ]

    def clean(self) -> None:
        """Require exact scope and a registered evidence-source shape.

        Raises
        ------
        ValidationError
            If evidence is free-form or attached outside its requirement scope.
        """
        super().clean()
        requirement = self.requirement if self.requirement_id else None
        if requirement is not None and (
            requirement.item_id != self.item_id
            or requirement.organization_id != self.organization_id
            or requirement.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Readiness evidence must remain in its exact requirement scope.",
                code="programme_readiness_evidence_scope_mismatch",
            )
        definition = PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS.get(self.source_code)
        if definition is None:
            raise ValidationError(
                {"source_code": "Choose a registered Programme evidence source."}
            )
        has_object = self.source_object_id is not None
        has_version = self.source_version is not None and self.source_version > 0
        if definition.requires_object != (has_object and has_version):
            raise ValidationError(
                "Readiness evidence sources must use the registered shape.",
                code="programme_evidence_source_shape_invalid",
            )
        if not definition.requires_object and (
            self.source_object_id is not None or self.source_version is not None
        ):
            raise ValidationError(
                "Operator attestation cannot carry an external identity.",
                code="programme_evidence_identity_forbidden",
            )


class ProgrammePublicRendition(_AppendOnlyProgrammeModel):
    """Immutable fields explicitly reviewed for future public disclosure."""

    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="public_renditions",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_public_renditions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_public_renditions",
    )
    rendition_number = models.PositiveBigIntegerField()
    source_item_version = models.PositiveBigIntegerField()
    source_working_revision = models.ForeignKey(
        ProgrammeWorkingRevision,
        on_delete=models.PROTECT,
        related_name="public_renditions",
    )
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    public_title = models.CharField(max_length=MAX_PROGRAMME_TITLE_LENGTH)
    public_summary = models.TextField(
        max_length=MAX_PROGRAMME_SUMMARY_LENGTH,
        blank=True,
    )
    public_content_note = models.CharField(
        max_length=MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_public_renditions_reviewed",
    )
    reviewed_at = models.DateTimeField()
    review_reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("item_id", "rendition_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "rendition_number"),
                name="programme_public_rendition_number_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    rendition_number__gt=0,
                    source_item_version__gt=0,
                )
                & ~models.Q(public_title="")
                & ~models.Q(review_reason=""),
                name="programme_public_rendition_valid",
            ),
        ]

    def clean(self) -> None:
        """Require exact scope and an unbroken immutable rendition chain.

        Raises
        ------
        ValidationError
            If the source or superseded rendition belongs elsewhere.
        """
        super().clean()
        if self.item_id and (
            self.item.organization_id != self.organization_id
            or self.item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Public rendition must remain in its item's exact scope.",
                code="programme_public_scope_mismatch",
            )
        source = (
            self.source_working_revision if self.source_working_revision_id else None
        )
        if source is not None and (
            source.item_id != self.item_id
            or source.organization_id != self.organization_id
            or source.edition_id != self.edition_id
            or source.item_version != self.source_item_version
        ):
            raise ValidationError(
                "Public rendition source must be an exact working revision.",
                code="programme_public_source_mismatch",
            )
        previous = self.supersedes if self.supersedes_id else None
        if self.rendition_number == 1 and previous is not None:
            raise ValidationError(
                "The first public rendition cannot supersede another rendition.",
                code="programme_public_first_supersedes",
            )
        if self.rendition_number > 1 and (
            previous is None
            or previous.item_id != self.item_id
            or previous.organization_id != self.organization_id
            or previous.edition_id != self.edition_id
            or previous.rendition_number + 1 != self.rendition_number
        ):
            raise ValidationError(
                "A public rendition must supersede the immediately prior rendition.",
                code="programme_public_chain_invalid",
            )


class ProgrammeCommandReceipt(_AppendOnlyProgrammeModel):
    """Immutable idempotency and optimistic-concurrency evidence."""

    control = models.ForeignKey(
        ProgrammeEditionControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    item = models.ForeignKey(
        ProgrammeItem,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_command_receipts",
    )
    operation = models.CharField(
        max_length=32,
        choices=text_choices(ProgrammeCommandOperation),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_commands_acted",
    )
    reason = models.CharField(max_length=MAX_PROGRAMME_REASON_LENGTH)
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(_SHA256_VALIDATOR,),
    )
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH,
        validators=(_SOURCE_CHANNEL_VALIDATOR,),
    )
    result_object_id = models.UUIDField()
    expected_version = models.PositiveBigIntegerField()
    resulting_control_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    resulting_item_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "idempotency_key"),
                name="programme_command_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("item", "resulting_item_version"),
                condition=~models.Q(
                    operation=ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD.value
                ),
                name="programme_command_item_version_uq",
            ),
            models.UniqueConstraint(
                fields=("control", "resulting_control_version"),
                condition=models.Q(resulting_control_version__isnull=False),
                name="programme_command_control_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    operation__in=tuple(
                        member.value for member in ProgrammeCommandOperation
                    )
                ),
                name="programme_command_operation_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    expected_version__gte=0,
                    resulting_item_version__gt=0,
                )
                & ~models.Q(reason="")
                & ~models.Q(source_channel=""),
                name="programme_command_evidence_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        operation=ProgrammeCommandOperation.ITEM_CREATE.value,
                        resulting_control_version__gt=0,
                    )
                    | (
                        ~models.Q(operation=ProgrammeCommandOperation.ITEM_CREATE.value)
                        & models.Q(resulting_control_version__isnull=True)
                    )
                ),
                name="programme_command_control_shape",
            ),
        ]

    def clean(self) -> None:
        """Require exact scope and coherent resulting-version evidence.

        Raises
        ------
        ValidationError
            If the receipt crosses scope or carries an invalid version shape.
        """
        super().clean()
        if self.control_id and (
            self.control.organization_id != self.organization_id
            or self.control.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme receipt control is outside its exact edition scope.",
                code="programme_receipt_control_scope_mismatch",
            )
        item = self.item if self.item_id else None
        if item is not None and (
            item.organization_id != self.organization_id
            or item.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Programme receipt item is outside its exact edition scope.",
                code="programme_receipt_item_scope_mismatch",
            )
        if self.operation == ProgrammeCommandOperation.ITEM_CREATE.value:
            if (
                self.resulting_control_version is None
                or self.resulting_control_version != self.expected_version + 1
                or self.resulting_item_version != 1
            ):
                raise ValidationError(
                    "Item creation must advance the edition control from v0 or later.",
                    code="programme_receipt_create_version_invalid",
                )
            if item is not None and (
                item.created_by_id != self.actor_id
                or item.last_modified_by_id != self.actor_id
            ):
                raise ValidationError(
                    "Item creation must be attributed to its creator and modifier.",
                    code="programme_receipt_create_actor_mismatch",
                )
        elif self.operation == ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD.value:
            if (
                self.resulting_control_version is not None
                or self.resulting_item_version != self.expected_version
            ):
                raise ValidationError(
                    "Public-copy approval must preserve the current item version.",
                    code="programme_receipt_public_version_invalid",
                )
        elif (
            self.resulting_control_version is not None
            or self.resulting_item_version != self.expected_version + 1
        ):
            raise ValidationError(
                "Item changes must advance only the expected item version.",
                code="programme_receipt_item_version_invalid",
            )
        elif item is not None and item.last_modified_by_id != self.actor_id:
            raise ValidationError(
                "Item changes must be attributed to the current modifier.",
                code="programme_receipt_item_actor_mismatch",
            )


__all__ = [
    "ProgrammeCommandReceipt",
    "ProgrammeDeliveryRevision",
    "ProgrammeDepartmentDiscussionEntry",
    "ProgrammeEditionControl",
    "ProgrammeItem",
    "ProgrammeItemSourceBinding",
    "ProgrammePublicRendition",
    "ProgrammeReadinessEvidence",
    "ProgrammeReadinessRequirement",
    "ProgrammeReadinessRequirementRevision",
    "ProgrammeWorkingRevision",
]
