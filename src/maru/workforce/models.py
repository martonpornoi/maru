"""Edition-owned workforce structure and private onboarding evidence."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField
from django.contrib.postgres.fields.ranges import RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Func, Q, Value
from django.utils import timezone

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug
from maru.events.adoption import profile_adopts_module
from maru.identity.policies import validate_convention_subject
from maru.participation.models import validate_capacity_code
from maru.workforce.availability_inputs import (
    MAX_AVAILABILITY_WINDOWS,
    AvailabilityWindowInput,
    normalize_availability_windows,
)

MAX_ONBOARDING_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_STRUCTURE_CHANGED_FIELDS = 16
MAX_STRUCTURE_AFFECTED_DEPARTMENTS = 256
ASSIGNMENT_PROPOSAL_VERSION = 1
ASSIGNMENT_DECISION_VERSION = 2
ASSIGNMENT_END_VERSION = 3
MAX_SHIFT_HEADCOUNT = 1_024
MAX_SHIFT_BREAK_MINUTES = 24 * 60
MAX_SHIFT_REST_MINUTES = 48 * 60

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 digest.",
    code="invalid_structure_digest",
)


def _half_open_availability_interval() -> Func:
    """Return the PostgreSQL range expression used for overlap exclusion.

    Returns
    -------
    Func
        Half-open ``tstzrange`` expression over the model's interval columns.
    """
    return Func(
        F("starts_at"),
        F("ends_at"),
        Value("[)"),
        function="TSTZRANGE",
        output_field=DateTimeRangeField(),
    )


def _half_open_shift_rest_interval() -> Func:
    """Return the PostgreSQL range covering work and required post-shift rest.

    Returns
    -------
    Func
        Half-open ``tstzrange`` expression over commitment snapshot columns.
    """
    return Func(
        F("starts_at"),
        F("rest_ends_at"),
        Value("[)"),
        function="TSTZRANGE",
        output_field=DateTimeRangeField(),
    )


def onboarding_document_path(
    request: OnboardingDocumentRequest,
    filename: str,
) -> str:
    """Return onboarding document path.

    Parameters
    ----------
    request : OnboardingDocumentRequest
        The incoming HTTP request.
    filename : str
        The original file name.

    Returns
    -------
    str
        The normalized text for onboarding document path.
    """
    extension = filename.rsplit(".", maxsplit=1)[-1].lower()
    return (
        f"private/workforce/{request.edition_id}/{request.account_id}/"
        f"{request.id}.{extension}"
    )


class Department(UUIDTimeStampedModel):
    """One edition-owned unit in the convention organization tree."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_departments",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_departments",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=1_000, blank=True)
    display_order = models.PositiveIntegerField(
        db_column="position",
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(65_535)),
    )
    created_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    retired_at = models.DateTimeField(null=True, blank=True, editable=False)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_departments_retired",
    )
    retired_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "display_order", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="workforce_department_edition_code_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(display_order__lte=65_535),
                name="workforce_department_display_order_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__isnull=False,
                        last_changed_in_structure_version__isnull=False,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_department_structure_versions_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(created_in_structure_version__isnull=True)
                        | models.Q(created_in_structure_version__gt=0)
                    )
                    & (
                        models.Q(last_changed_in_structure_version__isnull=True)
                        | models.Q(last_changed_in_structure_version__gt=0)
                    )
                    & (
                        models.Q(retired_in_structure_version__isnull=True)
                        | models.Q(retired_in_structure_version__gt=0)
                    )
                ),
                name="workforce_department_structure_versions_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                        retired_in_structure_version__isnull=True,
                    )
                    | models.Q(
                        retired_at__isnull=False,
                        retired_by__isnull=False,
                        retired_in_structure_version__isnull=False,
                        last_changed_in_structure_version__isnull=False,
                        retired_in_structure_version=models.F(
                            "last_changed_in_structure_version"
                        ),
                    )
                ),
                name="workforce_department_retirement_complete",
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
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The department must match its edition scope.")
        if self.parent_id:
            if self.parent_id == self.id:
                raise ValidationError({"parent": "A department cannot contain itself."})
            parent = self.parent
            if parent is None:
                raise ValidationError({"parent": "Choose an existing department."})
            if (
                parent.organization_id != self.organization_id
                or parent.edition_id != self.edition_id
            ):
                raise ValidationError(
                    {"parent": "A parent department must be in the same edition."}
                )
            seen = {self.id}
            ancestor: Department | None = parent
            while ancestor is not None:
                if ancestor.id in seen:
                    raise ValidationError(
                        {"parent": "The department hierarchy cannot contain a cycle."}
                    )
                seen.add(ancestor.id)
                ancestor = ancestor.parent
        if self.edition_id and self.edition.lifecycle in {"archived", "cancelled"}:
            raise ValidationError(
                "Workforce structure cannot change for a closed edition.",
                code="edition_workforce_closed",
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
        self.code = self.code.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable Department label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.name} — {self.edition.name}"


class EditionStructureControl(UUIDTimeStampedModel):
    """One optimistic-concurrency aggregate for an edition's Department tree."""

    class Origin(models.TextChoices):
        """Enumerate supported origin values."""

        LEGACY_EXISTING = "legacy_existing", "Legacy existing"
        MANUAL = "manual", "Manual"
        BUILTIN_TEMPLATE = "builtin_template", "Built-in template"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_structure_controls",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_structure_control",
    )
    origin = models.CharField(max_length=24, choices=Origin)
    aggregate_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "edition_id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="workforce_structure_version_positive",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition"),
                name="workforce_structure_scope_idx",
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
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The structure control must match its edition scope.")

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

    def __str__(self) -> str:
        """Return the human-readable EditionStructureControl label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"Structure v{self.aggregate_version} - {self.edition}"


class EditionStructureCommandReceipt(UUIDTimeStampedModel):
    """Immutable, minimized evidence for one successful structure command."""

    class Action(models.TextChoices):
        """Enumerate supported action values."""

        TEMPLATE_APPLIED = "template_applied", "Template applied"
        DEPARTMENT_CREATED = "department_created", "Department created"
        DEPARTMENT_UPDATED = "department_updated", "Department updated"
        DEPARTMENT_RETIRED = "department_retired", "Department retired"
        DEPARTMENT_DELETED = "department_deleted", "Department deleted"
        POSITION_CREATED = "position_created", "Position created"
        POSITION_UPDATED = "position_updated", "Position updated"
        POSITION_CLOSED = "position_closed", "Position closed"
        OPPORTUNITY_UPDATED = "opportunity_updated", "Opportunity updated"

    structure = models.ForeignKey(
        EditionStructureControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_structure_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_structure_command_receipts",
    )
    action = models.CharField(max_length=24, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_structure_commands_acted",
    )
    reason = models.CharField(max_length=240)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    changed_fields = ArrayField(
        models.CharField(max_length=80),
        default=list,
        size=MAX_STRUCTURE_CHANGED_FIELDS,
    )
    affected_department_ids = ArrayField(
        models.UUIDField(),
        default=list,
        size=MAX_STRUCTURE_AFFECTED_DEPARTMENTS,
    )
    affected_position = models.ForeignKey(
        "workforce.Position",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="structure_command_receipts",
    )
    retry_key = models.UUIDField(null=True, blank=True)
    request_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )
    template_code = models.SlugField(
        max_length=80,
        blank=True,
        validators=(validate_lowercase_slug,),
    )
    template_version = models.PositiveIntegerField(null=True, blank=True)
    template_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )
    deleted_name_snapshot = models.CharField(max_length=160, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("structure", "resulting_version"),
                name="workforce_structure_receipt_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                condition=models.Q(retry_key__isnull=False),
                name="workforce_structure_retry_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(resulting_version__gt=0),
                name="workforce_structure_receipt_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    changed_fields__len__lte=MAX_STRUCTURE_CHANGED_FIELDS
                ),
                name="workforce_structure_changed_fields_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    affected_department_ids__len__lte=(
                        MAX_STRUCTURE_AFFECTED_DEPARTMENTS
                    )
                ),
                name="workforce_structure_affected_ids_bounded",
            ),
            models.CheckConstraint(
                condition=(~models.Q(reason="") & ~models.Q(source_channel="")),
                name="workforce_structure_receipt_evidence_nonblank",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "resulting_version"),
                name="wrk_receipt_scope_ver_idx",
            ),
            models.Index(
                fields=("edition", "action", "created_at"),
                name="wrk_receipt_action_idx",
            ),
            models.Index(
                fields=("affected_position", "resulting_version"),
                name="wrk_receipt_position_ver_idx",
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
        if self.structure_id and (
            self.structure.organization_id != self.organization_id
            or self.structure.edition_id != self.edition_id
            or self.resulting_version > self.structure.aggregate_version
        ):
            raise ValidationError("The structure receipt must match its aggregate.")
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The structure receipt must match its edition scope.")

        if (
            self.actor_id is None
            or self.correlation_id is None
            or not self.reason
            or not self.reason.strip()
            or not self.source_channel
            or not self.source_channel.strip()
        ):
            raise ValidationError(
                "A structure command requires actor, reason, correlation, and source."
            )

        uses_retry = self.action in {
            self.Action.TEMPLATE_APPLIED,
            self.Action.DEPARTMENT_CREATED,
            self.Action.POSITION_CREATED,
        }
        has_retry_key = self.retry_key is not None
        has_request_digest = bool(self.request_digest)
        if (uses_retry and not (has_retry_key and has_request_digest)) or (
            not uses_retry and (has_retry_key or has_request_digest)
        ):
            raise ValidationError(
                "Only template, Department, and Position creation receipts use "
                "retry evidence."
            )
        is_template = self.action == self.Action.TEMPLATE_APPLIED
        template_field_presence = (
            bool(self.template_code),
            self.template_version is not None,
            bool(self.template_digest),
        )
        if (
            is_template
            and (
                not all(template_field_presence)
                or self.template_version is None
                or self.template_version < 1
            )
        ) or (not is_template and any(template_field_presence)):
            raise ValidationError(
                "Template provenance is complete only for a template application."
            )
        is_deletion = self.action == self.Action.DEPARTMENT_DELETED
        if is_deletion != bool(self.deleted_name_snapshot):
            raise ValidationError(
                "Only Department deletion retains the deleted name snapshot."
            )
        affected_count_by_action: dict[str, int] = {
            self.Action.TEMPLATE_APPLIED: 22,
            self.Action.DEPARTMENT_CREATED: 1,
            self.Action.DEPARTMENT_UPDATED: 1,
            self.Action.DEPARTMENT_RETIRED: 1,
            self.Action.DEPARTMENT_DELETED: 1,
            self.Action.POSITION_CREATED: 1,
            self.Action.POSITION_UPDATED: 1,
            self.Action.POSITION_CLOSED: 1,
            self.Action.OPPORTUNITY_UPDATED: 1,
        }
        expected_affected_count = affected_count_by_action.get(self.action)
        if expected_affected_count is not None and (
            len(self.affected_department_ids) != expected_affected_count
        ):
            raise ValidationError(
                "The structure command has an invalid affected Department count."
            )
        if len(self.affected_department_ids) != len(set(self.affected_department_ids)):
            raise ValidationError("Affected Department identifiers must be unique.")
        is_position_action = self.action in {
            self.Action.POSITION_CREATED,
            self.Action.POSITION_UPDATED,
            self.Action.POSITION_CLOSED,
            self.Action.OPPORTUNITY_UPDATED,
        }
        if is_position_action != (self.affected_position_id is not None):
            raise ValidationError(
                "Only Position and opportunity commands name an affected Position."
            )
        if len(self.changed_fields) != len(set(self.changed_fields)):
            raise ValidationError("Changed field names must be unique.")
        if not self.changed_fields:
            raise ValidationError("A structure command must name its changed fields.")

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
                "Structure command receipts are immutable.",
                code="immutable_structure_command_receipt",
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
        del args, kwargs
        raise ValidationError(
            "Structure command receipts are immutable.",
            code="immutable_structure_command_receipt",
        )


class OnboardingDocumentType(UUIDTimeStampedModel):
    """Immutable version of an agreement or onboarding evidence request."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="onboarding_document_types",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="onboarding_document_types",
    )
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    version = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=1_000)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.DRAFT,
    )
    max_bytes = models.PositiveIntegerField(
        default=MAX_ONBOARDING_DOCUMENT_BYTES,
        validators=(
            MinValueValidator(1_024),
            MaxValueValidator(MAX_ONBOARDING_DOCUMENT_BYTES),
        ),
    )
    retention_notice = models.CharField(
        max_length=500,
        default=(
            "Retained only for onboarding, access, dispute, and approved "
            "post-edition recordkeeping purposes."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_document_types_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code", "version"),
                name="workforce_document_type_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "code"),
                condition=Q(status="active"),
                name="workforce_one_active_document_type",
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
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The document type must match its edition scope.")

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
        self.code = self.code.lower()
        if not self._state.adding:
            current = type(self).objects.filter(id=self.id).values("status").first()
            if current and current["status"] in {
                self.Status.ACTIVE,
                self.Status.RETIRED,
            }:
                allowed = (
                    current["status"] == self.Status.ACTIVE
                    and self.status == self.Status.RETIRED
                )
                if not allowed:
                    raise ValidationError(
                        "Active agreement versions are immutable.",
                        code="immutable_onboarding_document_type",
                    )
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable OnboardingDocumentType label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.name} v{self.version} — {self.edition.name}"


class PositionTemplate(UUIDTimeStampedModel):
    """Organization-owned reusable position meaning and authority mapping."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="position_templates",
    )
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    version = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=1_000)
    default_headcount = models.PositiveSmallIntegerField(
        default=1,
        validators=(MinValueValidator(1), MaxValueValidator(500)),
    )
    default_capacity_codes = models.JSONField(default=list)
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        on_delete=models.PROTECT,
        related_name="position_templates",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="position_templates_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code", "version"),
                name="workforce_position_template_version_unique",
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
        if (
            self.role_bundle_id
            and self.role_bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"role_bundle": "The role bundle must belong to this organization."}
            )
        codes = list(self.default_capacity_codes)
        if not codes:
            raise ValidationError(
                {"default_capacity_codes": "Add at least one capacity code."}
            )
        if len(codes) != len(set(codes)):
            raise ValidationError(
                {"default_capacity_codes": "Capacity codes must be unique."}
            )
        for code in codes:
            validate_capacity_code(str(code))

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
        self.code = self.code.lower()
        self.default_capacity_codes = [
            str(code).lower() for code in self.default_capacity_codes
        ]
        if not self._state.adding:
            current = type(self).objects.filter(id=self.id).values("status").first()
            if current and current["status"] in {
                self.Status.PUBLISHED,
                self.Status.RETIRED,
            }:
                allowed = (
                    current["status"] == self.Status.PUBLISHED
                    and self.status == self.Status.RETIRED
                )
                if not allowed:
                    raise ValidationError(
                        "Published position templates are immutable.",
                        code="immutable_position_template",
                    )
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable PositionTemplate label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.name} v{self.version} — {self.organization.name}"


class Position(UUIDTimeStampedModel):
    """One edition position with explicit headcount and reporting line."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        PLANNED = "planned", "Planned"
        OPEN = "open", "Open"
        FILLED = "filled", "Filled"
        CLOSED = "closed", "Closed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_positions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_positions",
    )
    template = models.ForeignKey(
        PositionTemplate,
        on_delete=models.PROTECT,
        related_name="positions",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="positions",
    )
    reports_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="direct_reports",
    )
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        on_delete=models.PROTECT,
        related_name="workforce_positions",
    )
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=2_000)
    headcount = models.PositiveSmallIntegerField(
        default=1,
        validators=(MinValueValidator(1), MaxValueValidator(500)),
    )
    capacity_codes = models.JSONField(default=list)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PLANNED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_positions_created",
    )
    created_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_positions_closed",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "department__display_order", "title", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="workforce_position_edition_code_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__gt=0,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_position_structure_versions_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(closed_at__isnull=True, closed_by__isnull=True)
                    | models.Q(
                        status="closed",
                        closed_at__isnull=False,
                        closed_by__isnull=False,
                    )
                ),
                name="workforce_position_closure_evidence_complete",
            ),
        ]

    def clean(self) -> None:  # noqa: PLR0912
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The position must match its edition scope.")
        if self.department_id and (
            self.department.organization_id != self.organization_id
            or self.department.edition_id != self.edition_id
        ):
            raise ValidationError(
                {"department": "The department must be in the same edition."}
            )
        if self.template_id and self.template.organization_id != self.organization_id:
            raise ValidationError(
                {"template": "The template must belong to this organization."}
            )
        if (
            self.template_id
            and self.role_bundle_id
            and self.template.role_bundle_id != self.role_bundle_id
        ):
            raise ValidationError(
                {"role_bundle": "The role bundle must match the Position template."}
            )
        if (
            self.role_bundle_id
            and self.role_bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"role_bundle": "The role bundle must belong to this organization."}
            )
        if self.reports_to_id:
            if self.reports_to_id == self.id:
                raise ValidationError(
                    {"reports_to": "A position cannot report to itself."}
                )
            reports_to = self.reports_to
            if reports_to is None:
                raise ValidationError({"reports_to": "Choose an existing position."})
            if (
                reports_to.organization_id != self.organization_id
                or reports_to.edition_id != self.edition_id
            ):
                raise ValidationError(
                    {"reports_to": "The manager position must be in the same edition."}
                )
            seen = {self.id}
            manager: Position | None = reports_to
            while manager is not None:
                if manager.id in seen:
                    raise ValidationError(
                        {"reports_to": "The position hierarchy cannot contain a cycle."}
                    )
                seen.add(manager.id)
                manager = manager.reports_to
        codes = list(self.capacity_codes)
        if not codes:
            raise ValidationError({"capacity_codes": "Add at least one capacity code."})
        if len(codes) != len(set(codes)):
            raise ValidationError({"capacity_codes": "Capacity codes must be unique."})
        for code in codes:
            validate_capacity_code(str(code))
        if self.created_in_structure_version is not None and (
            self.last_changed_in_structure_version is None
            or self.last_changed_in_structure_version
            < self.created_in_structure_version
        ):
            raise ValidationError(
                "Position structure-version evidence must be complete."
            )
        if (self.closed_at is None) != (self.closed_by_id is None):
            raise ValidationError("Position closure evidence must be complete.")
        if self.closed_at is not None and self.status != self.Status.CLOSED:
            raise ValidationError("Only a closed Position may retain closure evidence.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.code = self.code.lower()
        self.capacity_codes = [str(code).lower() for code in self.capacity_codes]
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
            "Positions close with history instead of being deleted.",
            code="protected_workforce_position",
        )

    def __str__(self) -> str:
        """Return the human-readable Position label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.title} — {self.edition.name}"


class PositionDocumentRequirement(UUIDTimeStampedModel):
    """One approved document version required before assignment activation."""

    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="document_requirements",
    )
    document_type = models.ForeignKey(
        OnboardingDocumentType,
        on_delete=models.PROTECT,
        related_name="position_requirements",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("position_id", "document_type__name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("position", "document_type"),
                name="workforce_position_document_unique",
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
        if (
            self.position_id
            and self.document_type_id
            and (
                self.position.organization_id != self.document_type.organization_id
                or self.position.edition_id != self.document_type.edition_id
            )
        ):
            raise ValidationError(
                "A position document requirement must use the same edition."
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


class VolunteerOpportunity(UUIDTimeStampedModel):
    """The application publication paired with every position."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"
        WITHDRAWN = "withdrawn", "Withdrawn"

    position = models.OneToOneField(
        Position,
        on_delete=models.PROTECT,
        related_name="opportunity",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.DRAFT,
    )
    headline = models.CharField(max_length=200)
    description = models.CharField(max_length=2_000)
    applications_open_at = models.DateTimeField(null=True, blank=True)
    applications_close_at = models.DateTimeField(null=True, blank=True)
    visible_when_filled = models.BooleanField(default=True)
    created_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_structure_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("position__edition_id", "position__title", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__gt=0,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_opportunity_structure_versions_consistent",
            )
        ]

    @property
    def active_assignment_count(self) -> int:
        """Return active assignment count.

        Returns
        -------
        int
            The computed number of active assignment records.
        """
        return self.position.assignments.filter(
            status=PositionAssignment.Status.ACTIVE
        ).count()

    @property
    def is_filled(self) -> bool:
        """Return whether filled.

        Returns
        -------
        bool
            `True` when filled; otherwise `False`.
        """
        return self.active_assignment_count >= self.position.headcount

    @property
    def accepts_applications(self) -> bool:
        """Return whether accepts applications.

        Returns
        -------
        bool
            `True` when Compute accepts applications; otherwise `False`.
        """
        now = timezone.now()
        return (
            self.status == self.Status.PUBLISHED
            and not self.is_filled
            and (self.applications_open_at is None or self.applications_open_at <= now)
            and (self.applications_close_at is None or self.applications_close_at > now)
        )

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.applications_open_at
            and self.applications_close_at
            and self.applications_close_at <= self.applications_open_at
        ):
            raise ValidationError(
                {"applications_close_at": "Closing must be after opening."}
            )
        if self.created_in_structure_version is not None and (
            self.last_changed_in_structure_version is None
            or self.last_changed_in_structure_version
            < self.created_in_structure_version
        ):
            raise ValidationError(
                "Opportunity structure-version evidence must be complete."
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

    def __str__(self) -> str:
        """Return the human-readable VolunteerOpportunity label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"Applications: {self.position}"


class VolunteerApplication(UUIDTimeStampedModel):
    """One attendee expression of interest; never an authority grant."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    opportunity = models.ForeignKey(
        VolunteerOpportunity,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="volunteer_applications",
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.SUBMITTED,
    )
    motivation = models.TextField(max_length=2_000)
    submitted_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="volunteer_applications_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("-submitted_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "account"),
                name="workforce_one_application_per_opportunity_account",
            )
        ]

    def clean(self) -> None:
        """Validate and normalize the record."""
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        if self.account_id:
            validate_convention_subject(self.account)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable VolunteerApplication label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.account} — {self.opportunity.position.title}"


class OnboardingDocumentRequest(UUIDTimeStampedModel):
    """Private requested/uploaded/reviewed agreement evidence."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        REQUESTED = "requested", "Requested"
        SUBMITTED = "submitted", "Submitted for review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Changes required"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="onboarding_document_requests",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="onboarding_document_requests",
    )
    document_type = models.ForeignKey(
        OnboardingDocumentType,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_document_requests",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.REQUESTED,
    )
    instructions = models.CharField(max_length=1_000, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_document_requests_created",
    )
    requested_at = models.DateTimeField()
    document = models.FileField(
        upload_to=onboarding_document_path,
        blank=True,
        max_length=255,
    )
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    byte_count = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    scanner_code = models.CharField(max_length=80, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="onboarding_document_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "status", "due_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("document_type", "account"),
                name="workforce_document_request_account_type_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status"),
                name="workforce_document_review_idx",
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
        if self.account_id:
            validate_convention_subject(self.account)
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The document request must match its edition.")
        if self.document_type_id and (
            self.document_type.organization_id != self.organization_id
            or self.document_type.edition_id != self.edition_id
        ):
            raise ValidationError(
                {"document_type": "The agreement version must use the same edition."}
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
            "Onboarding documents require the retention workflow.",
            code="protected_onboarding_document",
        )

    def __str__(self) -> str:
        """Return the human-readable OnboardingDocumentRequest label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.document_type.name} — {self.account}"


class PositionAssignment(UUIDTimeStampedModel):
    """A proposed or active edition responsibility and its authority evidence."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"
        ENDED = "ended", "Ended"

    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_assignments",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_assignments",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_assignments",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PROPOSED,
    )
    effective_from = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_assignments_proposed",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workforce_assignments_approved",
    )
    reason = models.CharField(max_length=500)
    command_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_assignments_decided",
    )
    decision_at = models.DateTimeField(null=True, blank=True, editable=False)
    decision_reason = models.CharField(max_length=240, blank=True, editable=False)
    role_assignment = models.OneToOneField(
        "authorization.RoleAssignment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workforce_assignment",
    )
    participation_capacity = models.ForeignKey(
        "participation.ParticipationCapacity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workforce_assignments",
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_assignments_ended",
    )
    end_reason = models.CharField(max_length=240, blank=True, editable=False)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "position__title", "account_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("position", "account"),
                condition=Q(status__in=("proposed", "active")),
                name="workforce_one_open_assignment_per_position_account",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(command_version__isnull=True)
                    | models.Q(command_version__gt=0)
                ),
                name="workforce_assignment_command_version_positive",
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
        if self.account_id:
            validate_convention_subject(self.account)
        if self.position_id and (
            self.position.organization_id != self.organization_id
            or self.position.edition_id != self.edition_id
        ):
            raise ValidationError("The assignment must match its position scope.")
        if self.expires_at and self.expires_at <= self.effective_from:
            raise ValidationError({"expires_at": "Expiry must follow activation."})
        if self.approved_by_id and self.approved_by_id == self.proposed_by_id:
            raise ValidationError(
                {"approved_by": "A different controller must approve assignment."}
            )
        participation_adopted = profile_adopts_module(
            self.edition.adoption_profile_code,
            "participation",
        )
        capacity_matches_profile = (
            participation_adopted and bool(self.participation_capacity_id)
        ) or (not participation_adopted and not self.participation_capacity_id)
        if self.status == self.Status.ACTIVE and (
            not self.approved_by_id
            or not self.role_assignment_id
            or not capacity_matches_profile
        ):
            raise ValidationError(
                "Active assignments require approval and profile-matched evidence."
            )
        if self.command_version is not None:
            has_decision = bool(
                self.decision_by_id
                and self.decision_at
                and self.decision_reason.strip()
            )
            has_any_decision = bool(
                self.decision_by_id or self.decision_at or self.decision_reason
            )
            if self.status == self.Status.PROPOSED and (
                self.command_version != 1
                or self.approved_by_id
                or self.role_assignment_id
                or self.participation_capacity_id
                or has_any_decision
                or self.ended_at
                or self.ended_by_id
                or self.end_reason
            ):
                raise ValidationError(
                    "A governed proposal cannot contain decision or ending evidence."
                )
            if self.status == self.Status.REJECTED and (
                self.command_version < ASSIGNMENT_DECISION_VERSION
                or not has_decision
                or self.approved_by_id
                or self.role_assignment_id
                or self.participation_capacity_id
                or self.ended_at
                or self.ended_by_id
                or self.end_reason
            ):
                raise ValidationError(
                    "A rejected assignment requires only complete decision evidence."
                )
            if self.status in {self.Status.ACTIVE, self.Status.ENDED} and (
                self.command_version < ASSIGNMENT_DECISION_VERSION
                or not has_decision
                or self.decision_by_id != self.approved_by_id
                or not self.approved_by_id
                or not self.role_assignment_id
                or not capacity_matches_profile
            ):
                raise ValidationError(
                    "A governed assignment requires complete profile-matched "
                    "approval evidence."
                )
            has_end = bool(
                self.ended_at and self.ended_by_id and self.end_reason.strip()
            )
            has_any_end = bool(self.ended_at or self.ended_by_id or self.end_reason)
            if self.status == self.Status.ACTIVE and has_any_end:
                raise ValidationError(
                    "An active assignment cannot contain ending evidence."
                )
            if self.status == self.Status.ENDED and (
                self.command_version < ASSIGNMENT_END_VERSION or not has_end
            ):
                raise ValidationError(
                    "A governed ended assignment requires complete ending evidence."
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
            "Assignments end with retained evidence instead of being deleted.",
            code="protected_workforce_assignment",
        )

    def __str__(self) -> str:
        """Return the human-readable PositionAssignment label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return f"{self.account} — {self.position.title}"


class PositionAssignmentCommandReceipt(UUIDTimeStampedModel):
    """Immutable reason and retry evidence for one assignment state change."""

    class Action(models.TextChoices):
        """Enumerate supported assignment command actions."""

        PROPOSED = "proposed", "Assignment proposed"
        APPROVED = "approved", "Assignment approved"
        REJECTED = "rejected", "Assignment rejected"
        ENDED = "ended", "Assignment ended"

    assignment = models.ForeignKey(
        PositionAssignment,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_assignment_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_assignment_command_receipts",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="assignment_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_assignment_commands_acted",
    )
    action = models.CharField(max_length=16, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=240)
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("assignment_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("assignment", "resulting_version"),
                name="workforce_assignment_receipt_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_assignment_retry_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(resulting_version__gt=0),
                name="workforce_assignment_receipt_version_positive",
            ),
            models.CheckConstraint(
                condition=(~models.Q(reason="") & ~models.Q(source_channel="")),
                name="workforce_assignment_receipt_evidence_nonblank",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="wrk_assignment_action_idx",
            ),
            models.Index(
                fields=("position", "created_at"),
                name="wrk_assignment_pos_idx",
            ),
        ]

    def clean(self) -> None:
        """Validate exact scope and command-version evidence.

        Raises
        ------
        ValidationError
            If the receipt does not match its resulting assignment or lacks
            required retained evidence.
        """
        super().clean()
        assignment = self.assignment if self.assignment_id else None
        if assignment is None or (
            assignment.organization_id != self.organization_id
            or assignment.edition_id != self.edition_id
            or assignment.position_id != self.position_id
            or assignment.command_version != self.resulting_version
        ):
            raise ValidationError(
                "The assignment receipt must match its resulting assignment state."
            )
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The assignment receipt must match its edition.")
        if not self.reason.strip() or not self.source_channel.strip():
            raise ValidationError(
                "An assignment command requires a retained reason and source."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and insert this append-only command receipt.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the model implementation.
        **kwargs : Any
            Keyword arguments forwarded to the model implementation.

        Raises
        ------
        ValidationError
            If an update is attempted or receipt evidence is invalid.
        """
        if not self._state.adding:
            raise ValidationError(
                "Assignment command receipts are immutable.",
                code="immutable_assignment_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of retained assignment command evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments that would otherwise reach model deletion.
        **kwargs : Any
            Keyword arguments that would otherwise reach model deletion.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable Django deletion counts retained for method compatibility.

        Raises
        ------
        ValidationError
            Always, because assignment command evidence is immutable.
        """
        del args, kwargs
        raise ValidationError(
            "Assignment command receipts are immutable.",
            code="immutable_assignment_command_receipt",
        )


class PersonAvailabilityPlan(UUIDTimeStampedModel):
    """One person's current edition availability statement."""

    class Status(models.TextChoices):
        """Enumerate owner-controlled disclosure states."""

        DRAFT = "draft", "Private draft"
        SUBMITTED = "submitted", "Shared with organizers"
        WITHDRAWN = "withdrawn", "Withdrawn"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="person_availability_plans",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="person_availability_plans",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_availability_plans",
    )
    status = models.CharField(max_length=16, choices=Status)
    time_zone = models.CharField(max_length=63)
    command_version = models.PositiveBigIntegerField(editable=False)
    window_count = models.PositiveSmallIntegerField(default=0, editable=False)
    window_set_digest = models.CharField(
        max_length=64,
        validators=(_SHA256_VALIDATOR,),
        editable=False,
    )
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    withdrawn_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        """Configure the one-plan-per-person edition aggregate."""

        ordering = ("edition_id", "account_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "edition", "account"),
                name="workforce_avail_plan_unique",
            ),
            models.CheckConstraint(
                condition=Q(command_version__gt=0),
                name="workforce_avail_version_pos",
            ),
            models.CheckConstraint(
                condition=Q(window_count__lte=MAX_AVAILABILITY_WINDOWS),
                name="workforce_avail_count_bound",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="draft",
                        submitted_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        status="submitted",
                        submitted_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        status="withdrawn",
                        submitted_at__isnull=True,
                        withdrawn_at__isnull=False,
                        window_count=0,
                    )
                ),
                name="workforce_avail_state_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status"),
                name="wrk_avail_plan_state_idx",
            )
        ]

    def clean(self) -> None:
        """Validate person, scope, and state evidence.

        Raises
        ------
        ValidationError
            If person, tenant, version, count, or lifecycle evidence is invalid.
        """
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The availability plan must match its edition.")
        if self.command_version < 1:
            raise ValidationError(
                {"command_version": "Availability version must be positive."}
            )
        if self.window_count > MAX_AVAILABILITY_WINDOWS:
            raise ValidationError(
                {"window_count": "The availability period limit was exceeded."}
            )
        if self.status == self.Status.DRAFT and (
            self.submitted_at is not None or self.withdrawn_at is not None
        ):
            raise ValidationError("A private draft cannot contain sharing evidence.")
        if self.status == self.Status.SUBMITTED and (
            self.submitted_at is None or self.withdrawn_at is not None
        ):
            raise ValidationError("A shared plan requires complete sharing evidence.")
        if self.status == self.Status.WITHDRAWN and (
            self.submitted_at is not None
            or self.withdrawn_at is None
            or self.window_count != 0
        ):
            raise ValidationError(
                "A withdrawn plan must remove every current exact period."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the governed current plan.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion outside the approved retention workflow.

        Parameters
        ----------
        *args : Any
            Positional deletion arguments.
        **kwargs : Any
            Keyword deletion arguments.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable framework-compatible deletion result.

        Raises
        ------
        ValidationError
            Always, because ordinary commands retain the minimized plan shell.
        """
        del args, kwargs
        raise ValidationError(
            "Availability plans require the approved retention workflow.",
            code="protected_person_availability_plan",
        )


class PersonAvailabilityWindow(UUIDTimeStampedModel):
    """One current exact available or preferred interval in a person's plan."""

    class Preference(models.TextChoices):
        """Enumerate supported planning signals."""

        AVAILABLE = "available", "Available"
        PREFERRED = "preferred", "Preferred"

    plan = models.ForeignKey(
        PersonAvailabilityPlan,
        on_delete=models.CASCADE,
        related_name="windows",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    preference = models.CharField(max_length=16, choices=Preference)
    created_by_version = models.PositiveBigIntegerField(editable=False)

    class Meta:
        """Order and constrain current half-open availability intervals."""

        ordering = ("plan_id", "starts_at", "ends_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="workforce_avail_window_order",
            ),
            models.CheckConstraint(
                condition=Q(created_by_version__gt=0),
                name="workforce_avail_window_ver",
            ),
            ExclusionConstraint(
                name="workforce_avail_no_overlap",
                expressions=(
                    ("plan", RangeOperators.EQUAL),
                    (_half_open_availability_interval(), RangeOperators.OVERLAPS),
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=("plan", "starts_at"),
                name="wrk_avail_window_start_idx",
            )
        ]

    def clean(self) -> None:
        """Validate the plan version and exact edition calendar horizon.

        Raises
        ------
        ValidationError
            If the period is stale or outside the canonical interval contract.
        """
        super().clean()
        if self.plan_id and self.created_by_version != self.plan.command_version:
            raise ValidationError(
                "An availability period must belong to the current plan version."
            )
        if self.plan_id:
            normalize_availability_windows(
                (
                    AvailabilityWindowInput(
                        starts_at=self.starts_at,
                        ends_at=self.ends_at,
                        preference=self.preference,
                    ),
                ),
                starts_on=self.plan.edition.starts_on,
                ends_on=self.plan.edition.ends_on,
                time_zone=self.plan.time_zone,
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist one current period.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse an isolated period deletion outside a plan replacement.

        Parameters
        ----------
        *args : Any
            Positional deletion arguments.
        **kwargs : Any
            Keyword deletion arguments.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable framework-compatible deletion result.

        Raises
        ------
        ValidationError
            Always, because the complete plan is the command boundary.
        """
        del args, kwargs
        raise ValidationError(
            "Replace or withdraw the complete availability plan.",
            code="protected_person_availability_window",
        )


class PersonAvailabilityCommandReceipt(UUIDTimeStampedModel):
    """Immutable minimized evidence for one owner availability command."""

    class Action(models.TextChoices):
        """Enumerate complete-plan command actions."""

        DRAFT_SAVED = "draft_saved", "Private draft saved"
        SUBMITTED = "submitted", "Availability shared"
        WITHDRAWN = "withdrawn", "Availability withdrawn"

    plan = models.ForeignKey(
        PersonAvailabilityPlan,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="person_availability_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="person_availability_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_availability_commands_acted",
    )
    action = models.CharField(max_length=16, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    resulting_status = models.CharField(
        max_length=16,
        choices=PersonAvailabilityPlan.Status,
    )
    window_count = models.PositiveSmallIntegerField()
    window_set_digest = models.CharField(
        max_length=64,
        validators=(_SHA256_VALIDATOR,),
    )
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Keep one exact receipt per plan version and owner retry key."""

        ordering = ("plan_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("plan", "resulting_version"),
                name="workforce_avail_receipt_ver",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_avail_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="workforce_avail_receipt_pos",
            ),
            models.CheckConstraint(
                condition=Q(window_count__lte=MAX_AVAILABILITY_WINDOWS),
                name="workforce_avail_receipt_cnt",
            ),
            models.CheckConstraint(
                condition=~Q(source_channel=""),
                name="workforce_avail_source_set",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="wrk_avail_action_idx",
            )
        ]

    def clean(self) -> None:
        """Validate that minimized evidence matches its resulting plan.

        Raises
        ------
        ValidationError
            If actor, scope, state, version, count, or digest does not match.
        """
        super().clean()
        plan = self.plan if self.plan_id else None
        if plan is None or (
            plan.organization_id != self.organization_id
            or plan.edition_id != self.edition_id
            or plan.account_id != self.actor_id
            or plan.command_version != self.resulting_version
            or plan.status != self.resulting_status
            or plan.window_count != self.window_count
            or plan.window_set_digest != self.window_set_digest
        ):
            raise ValidationError(
                "Availability command evidence must match its resulting plan."
            )
        actions_by_status: dict[str, str] = {
            PersonAvailabilityPlan.Status.DRAFT: self.Action.DRAFT_SAVED,
            PersonAvailabilityPlan.Status.SUBMITTED: self.Action.SUBMITTED,
            PersonAvailabilityPlan.Status.WITHDRAWN: self.Action.WITHDRAWN,
        }
        expected_action = actions_by_status[plan.status]
        if self.action != expected_action or not self.source_channel.strip():
            raise ValidationError(
                "Availability command action or source does not match the plan."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and insert append-only command evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django.
        **kwargs : Any
            Keyword arguments forwarded to Django.

        Raises
        ------
        ValidationError
            If an existing receipt is mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Availability command receipts are immutable.",
                code="immutable_availability_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of minimized command evidence.

        Parameters
        ----------
        *args : Any
            Positional deletion arguments.
        **kwargs : Any
            Keyword deletion arguments.

        Returns
        -------
        tuple[int, dict[str, int]]
            Unreachable framework-compatible deletion result.

        Raises
        ------
        ValidationError
            Always, because command evidence is append-only.
        """
        del args, kwargs
        raise ValidationError(
            "Availability command receipts are immutable.",
            code="immutable_availability_command_receipt",
        )


class ShiftDemand(UUIDTimeStampedModel):
    """One edition-owned request for people to cover a timed Position."""

    class Status(models.TextChoices):
        """Enumerate the organizer-controlled demand lifecycle."""

        DRAFT = "draft", "Draft"
        OPEN = "open", "Open for claims"
        LOCKED = "locked", "Coverage locked"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="shift_demands",
    )
    title = models.CharField(max_length=160)
    location_label = models.CharField(max_length=160)
    briefing = models.CharField(max_length=1_000)
    supervision_note = models.CharField(max_length=500, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    required_headcount = models.PositiveSmallIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(MAX_SHIFT_HEADCOUNT)),
    )
    break_minutes = models.PositiveSmallIntegerField(
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(MAX_SHIFT_BREAK_MINUTES)),
    )
    minimum_rest_minutes = models.PositiveSmallIntegerField(
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(MAX_SHIFT_REST_MINUTES)),
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.DRAFT,
    )
    command_version = models.PositiveBigIntegerField(editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands_created",
    )
    published_at = models.DateTimeField(null=True, blank=True, editable=False)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands_published",
    )
    locked_at = models.DateTimeField(null=True, blank=True, editable=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands_locked",
    )
    locked_headcount = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    lock_reason = models.CharField(max_length=240, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands_completed",
    )
    completion_reason = models.CharField(max_length=240, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demands_cancelled",
    )
    cancellation_reason = models.CharField(max_length=240, blank=True, editable=False)

    class Meta:
        """Constrain exact-edition demand identity, state, and calendar order."""

        ordering = ("edition_id", "starts_at", "title", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="workforce_shift_time_order",
            ),
            models.CheckConstraint(
                condition=Q(
                    required_headcount__gte=1,
                    required_headcount__lte=MAX_SHIFT_HEADCOUNT,
                ),
                name="workforce_shift_headcount_bound",
            ),
            models.CheckConstraint(
                condition=Q(break_minutes__lte=MAX_SHIFT_BREAK_MINUTES),
                name="workforce_shift_break_bound",
            ),
            models.CheckConstraint(
                condition=Q(minimum_rest_minutes__lte=MAX_SHIFT_REST_MINUTES),
                name="workforce_shift_rest_bound",
            ),
            models.CheckConstraint(
                condition=Q(command_version__gt=0),
                name="workforce_shift_version_pos",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status", "starts_at"),
                name="wrk_shift_demand_state_idx",
            ),
            models.Index(
                fields=("position", "starts_at"),
                name="wrk_shift_demand_pos_idx",
            ),
        ]

    def clean(self) -> None:
        """Validate exact scope, time, bounds, and current state evidence.

        Raises
        ------
        ValidationError
            If scope, calendar, limits, or lifecycle evidence is inconsistent.
        """
        super().clean()
        if self.position_id and (
            self.position.organization_id != self.organization_id
            or self.position.edition_id != self.edition_id
        ):
            raise ValidationError("The Shift must match its Position scope.")
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The Shift must match its edition scope.")
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "The Shift must end after it starts."})
        if not self.title.strip() or not self.location_label.strip():
            raise ValidationError("A Shift requires a title and operational place.")
        if not self.briefing.strip():
            raise ValidationError({"briefing": "Explain what the person should do."})
        if self.break_minutes * 60 >= (self.ends_at - self.starts_at).total_seconds():
            raise ValidationError(
                {"break_minutes": "Break time must be shorter than the Shift."}
            )
        if self.command_version < 1:
            raise ValidationError(
                {"command_version": "Shift version must be positive."}
            )
        published = bool(self.published_at and self.published_by_id)
        locked = bool(
            self.locked_at
            and self.locked_by_id
            and self.locked_headcount is not None
            and self.lock_reason.strip()
        )
        completed = bool(
            self.completed_at
            and self.completed_by_id
            and self.completion_reason.strip()
        )
        cancelled = bool(
            self.cancelled_at
            and self.cancelled_by_id
            and self.cancellation_reason.strip()
        )
        if self.status == self.Status.DRAFT and any(
            (published, locked, completed, cancelled)
        ):
            raise ValidationError("A draft Shift cannot contain later-state evidence.")
        if self.status == self.Status.OPEN and (
            not published or locked or completed or cancelled
        ):
            raise ValidationError("An open Shift requires only publication evidence.")
        if self.status == self.Status.LOCKED and (
            not published or not locked or completed or cancelled
        ):
            raise ValidationError(
                "A locked Shift requires publication and lock evidence."
            )
        if self.status == self.Status.COMPLETED and (
            not published or not locked or not completed or cancelled
        ):
            raise ValidationError("A completed Shift requires complete lock evidence.")
        if self.status == self.Status.CANCELLED and (not cancelled or completed):
            raise ValidationError("A cancelled Shift requires cancellation evidence.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the governed Shift demand.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse ordinary deletion of retained Shift demand.

        Parameters
        ----------
        *args : Any
            Unused positional deletion arguments accepted for model parity.
        **kwargs : Any
            Unused keyword deletion arguments accepted for model parity.

        Returns
        -------
        tuple[int, dict[str, int]]
            Framework-compatible deletion counts; unreachable because deletion
            always raises.

        Raises
        ------
        ValidationError
            Always, because Shift demand ends through cancellation or completion.
        """
        del args, kwargs
        raise ValidationError(
            "Shifts are cancelled or completed instead of deleted.",
            code="protected_shift_demand",
        )

    def __str__(self) -> str:
        """Return the human-readable Shift demand label.

        Returns
        -------
        str
            Shift title and edition label.
        """
        return f"{self.title} — {self.edition}"


class ShiftDemandCommandReceipt(UUIDTimeStampedModel):
    """Immutable reason and retry evidence for one Shift-demand command."""

    class Action(models.TextChoices):
        """Enumerate supported demand commands."""

        CREATED = "created", "Shift created"
        UPDATED = "updated", "Draft updated"
        OPENED = "opened", "Claims opened"
        LOCKED = "locked", "Coverage locked"
        REOPENED = "reopened", "Coverage reopened"
        COMPLETED = "completed", "Shift completed"
        CANCELLED = "cancelled", "Shift cancelled"

    demand = models.ForeignKey(
        ShiftDemand,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_shift_demand_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_shift_demand_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_shift_demand_commands_acted",
    )
    action = models.CharField(max_length=16, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    resulting_status = models.CharField(max_length=16, choices=ShiftDemand.Status)
    reason = models.CharField(max_length=240)
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Keep one exact receipt per version and organizer retry key."""

        ordering = ("demand_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("demand", "resulting_version"),
                name="workforce_shift_demand_receipt_ver",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_shift_demand_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="workforce_shift_demand_receipt_pos",
            ),
            models.CheckConstraint(
                condition=(~Q(reason="") & ~Q(source_channel="")),
                name="workforce_shift_demand_evidence_set",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="wrk_shift_demand_action_idx",
            )
        ]

    def clean(self) -> None:
        """Validate exact resulting demand evidence.

        Raises
        ------
        ValidationError
            If scope, version, state, reason, or source disagrees with demand.
        """
        super().clean()
        demand = self.demand if self.demand_id else None
        if demand is None or (
            demand.organization_id != self.organization_id
            or demand.edition_id != self.edition_id
            or demand.command_version != self.resulting_version
            or demand.status != self.resulting_status
        ):
            raise ValidationError("Shift demand evidence must match its result.")
        if not self.reason.strip() or not self.source_channel.strip():
            raise ValidationError("Shift demand evidence requires reason and source.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and insert append-only demand evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.

        Raises
        ------
        ValidationError
            If an existing receipt is mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Shift demand receipts are immutable.",
                code="immutable_shift_demand_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of append-only demand evidence.

        Parameters
        ----------
        *args : Any
            Unused positional deletion arguments accepted for model parity.
        **kwargs : Any
            Unused keyword deletion arguments accepted for model parity.

        Returns
        -------
        tuple[int, dict[str, int]]
            Framework-compatible deletion counts; unreachable because deletion
            always raises.

        Raises
        ------
        ValidationError
            Always, because command receipts are immutable evidence.
        """
        del args, kwargs
        raise ValidationError(
            "Shift demand receipts are immutable.",
            code="immutable_shift_demand_receipt",
        )


class ShiftCommitment(UUIDTimeStampedModel):
    """One person's retained claim and organizer-confirmed Shift commitment."""

    class Status(models.TextChoices):
        """Enumerate the person and organizer commitment lifecycle."""

        CLAIMED = "claimed", "Claimed"
        CONFIRMED = "confirmed", "Confirmed"
        REMOVED = "removed", "Removed"
        COMPLETED = "completed", "Completed"

    class RemovalKind(models.TextChoices):
        """Identify who or what ended an active commitment."""

        WITHDRAWN = "withdrawn", "Withdrawn by person"
        ORGANIZER = "organizer", "Removed by organizer"
        CANCELLED = "cancelled", "Removed when Shift was cancelled"

    demand = models.ForeignKey(
        ShiftDemand,
        on_delete=models.PROTECT,
        related_name="commitments",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments",
    )
    position_assignment = models.ForeignKey(
        PositionAssignment,
        on_delete=models.PROTECT,
        related_name="shift_commitments",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments",
    )
    status = models.CharField(max_length=16, choices=Status)
    starts_at = models.DateTimeField(editable=False)
    ends_at = models.DateTimeField(editable=False)
    rest_ends_at = models.DateTimeField(editable=False)
    availability_plan = models.ForeignKey(
        PersonAvailabilityPlan,
        on_delete=models.PROTECT,
        related_name="shift_commitments",
    )
    availability_version = models.PositiveBigIntegerField(editable=False)
    command_version = models.PositiveBigIntegerField(editable=False)
    claimed_at = models.DateTimeField(editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments_confirmed",
    )
    confirmation_reason = models.CharField(max_length=240, blank=True, editable=False)
    removed_at = models.DateTimeField(null=True, blank=True, editable=False)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments_removed",
    )
    removal_kind = models.CharField(
        max_length=16,
        blank=True,
        choices=RemovalKind,
        editable=False,
    )
    removal_reason = models.CharField(max_length=240, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitments_completed",
    )
    completion_reason = models.CharField(max_length=240, blank=True, editable=False)

    class Meta:
        """Constrain active uniqueness and work-plus-rest overlap globally."""

        ordering = ("edition_id", "starts_at", "account_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("demand", "account"),
                condition=Q(status__in=("claimed", "confirmed")),
                name="workforce_shift_one_active_claim",
            ),
            ExclusionConstraint(
                name="workforce_shift_no_active_overlap",
                expressions=(
                    ("account", RangeOperators.EQUAL),
                    (_half_open_shift_rest_interval(), RangeOperators.OVERLAPS),
                ),
                condition=Q(status__in=("claimed", "confirmed")),
            ),
            models.CheckConstraint(
                condition=(
                    Q(ends_at__gt=F("starts_at")) & Q(rest_ends_at__gte=F("ends_at"))
                ),
                name="workforce_shift_commitment_time_order",
            ),
            models.CheckConstraint(
                condition=Q(
                    command_version__gt=0,
                    availability_version__gt=0,
                ),
                name="workforce_shift_commitment_versions_pos",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status", "starts_at"),
                name="wrk_shift_commit_state_idx",
            ),
            models.Index(
                fields=("account", "status", "starts_at"),
                name="wrk_shift_commit_person_idx",
            ),
        ]

    def clean(self) -> None:
        """Validate scope, snapshots, owner identity, and state evidence.

        Raises
        ------
        ValidationError
            If the retained commitment is internally inconsistent.
        """
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)
        demand = self.demand if self.demand_id else None
        assignment = self.position_assignment if self.position_assignment_id else None
        plan = self.availability_plan if self.availability_plan_id else None
        if demand is None or (
            demand.organization_id != self.organization_id
            or demand.edition_id != self.edition_id
            or demand.starts_at != self.starts_at
            or demand.ends_at != self.ends_at
        ):
            raise ValidationError("The commitment must match its Shift snapshot.")
        if assignment is None or (
            assignment.organization_id != self.organization_id
            or assignment.edition_id != self.edition_id
            or assignment.position_id != demand.position_id
            or assignment.account_id != self.account_id
        ):
            raise ValidationError("The commitment must match an exact Position holder.")
        if plan is None or (
            plan.organization_id != self.organization_id
            or plan.edition_id != self.edition_id
            or plan.account_id != self.account_id
        ):
            raise ValidationError("The commitment Availability evidence is mismatched.")
        if self.rest_ends_at < self.ends_at:
            raise ValidationError("Required rest cannot end before the Shift.")
        if self.command_version < 1 or self.availability_version < 1:
            raise ValidationError("Commitment versions must be positive.")
        confirmed = bool(
            self.confirmed_at
            and self.confirmed_by_id
            and self.confirmation_reason.strip()
        )
        removed = bool(
            self.removed_at
            and self.removed_by_id
            and self.removal_kind
            and self.removal_reason.strip()
        )
        completed = bool(
            self.completed_at
            and self.completed_by_id
            and self.completion_reason.strip()
        )
        if self.status == self.Status.CLAIMED and any((confirmed, removed, completed)):
            raise ValidationError("A claim cannot contain later-state evidence.")
        if self.status == self.Status.CONFIRMED and (
            not confirmed or removed or completed
        ):
            raise ValidationError("A confirmed commitment requires confirmation only.")
        if self.status == self.Status.REMOVED and (not removed or completed):
            raise ValidationError("A removed commitment requires removal evidence.")
        if self.status == self.Status.COMPLETED and (
            not confirmed or removed or not completed
        ):
            raise ValidationError(
                "A completed commitment requires confirmation evidence."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the governed Shift commitment.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse ordinary deletion of retained Shift commitment.

        Parameters
        ----------
        *args : Any
            Unused positional deletion arguments accepted for model parity.
        **kwargs : Any
            Unused keyword deletion arguments accepted for model parity.

        Returns
        -------
        tuple[int, dict[str, int]]
            Framework-compatible deletion counts; unreachable because deletion
            always raises.

        Raises
        ------
        ValidationError
            Always, because commitments end through governed commands.
        """
        del args, kwargs
        raise ValidationError(
            "Shift commitments are removed or completed instead of deleted.",
            code="protected_shift_commitment",
        )

    def __str__(self) -> str:
        """Return the human-readable Shift commitment label.

        Returns
        -------
        str
            Person and Shift title label.
        """
        return f"{self.account} — {self.demand.title}"


class ShiftCommitmentCommandReceipt(UUIDTimeStampedModel):
    """Immutable reason and retry evidence for one commitment command."""

    class Action(models.TextChoices):
        """Enumerate supported commitment commands."""

        CLAIMED = "claimed", "Shift claimed"
        CONFIRMED = "confirmed", "Claim confirmed"
        WITHDRAWN = "withdrawn", "Claim withdrawn"
        REMOVED = "removed", "Claim removed"
        COMPLETED = "completed", "Commitment completed"
        CANCELLED = "cancelled", "Removed by cancellation"

    commitment = models.ForeignKey(
        ShiftCommitment,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    demand = models.ForeignKey(
        ShiftDemand,
        on_delete=models.PROTECT,
        related_name="commitment_command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitment_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitment_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workforce_shift_commitment_commands_acted",
    )
    action = models.CharField(max_length=16, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    resulting_status = models.CharField(max_length=16, choices=ShiftCommitment.Status)
    reason = models.CharField(max_length=240)
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Keep one exact receipt per version and actor retry key."""

        ordering = ("commitment_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("commitment", "resulting_version"),
                name="workforce_shift_commit_receipt_ver",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_shift_commit_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="workforce_shift_commit_receipt_pos",
            ),
            models.CheckConstraint(
                condition=(~Q(reason="") & ~Q(source_channel="")),
                name="workforce_shift_commit_evidence_set",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="wrk_shift_commit_action_idx",
            )
        ]

    def clean(self) -> None:
        """Validate exact resulting commitment evidence.

        Raises
        ------
        ValidationError
            If scope, version, state, reason, or source disagrees with result.
        """
        super().clean()
        commitment = self.commitment if self.commitment_id else None
        if commitment is None or (
            commitment.demand_id != self.demand_id
            or commitment.organization_id != self.organization_id
            or commitment.edition_id != self.edition_id
            or commitment.command_version != self.resulting_version
            or commitment.status != self.resulting_status
        ):
            raise ValidationError("Shift commitment evidence must match its result.")
        if not self.reason.strip() or not self.source_channel.strip():
            raise ValidationError("Commitment evidence requires reason and source.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and insert append-only commitment evidence.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.

        Raises
        ------
        ValidationError
            If an existing receipt is mutated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Shift commitment receipts are immutable.",
                code="immutable_shift_commitment_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse deletion of append-only commitment evidence.

        Parameters
        ----------
        *args : Any
            Unused positional deletion arguments accepted for model parity.
        **kwargs : Any
            Unused keyword deletion arguments accepted for model parity.

        Returns
        -------
        tuple[int, dict[str, int]]
            Framework-compatible deletion counts; unreachable because deletion
            always raises.

        Raises
        ------
        ValidationError
            Always, because command receipts are immutable evidence.
        """
        del args, kwargs
        raise ValidationError(
            "Shift commitment receipts are immutable.",
            code="immutable_shift_commitment_receipt",
        )
