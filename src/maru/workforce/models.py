"""Edition-owned workforce structure and private onboarding evidence."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug
from maru.identity.policies import validate_convention_subject
from maru.participation.models import validate_capacity_code

MAX_ONBOARDING_DOCUMENT_BYTES = 10 * 1024 * 1024


def onboarding_document_path(
    request: OnboardingDocumentRequest,
    filename: str,
) -> str:
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
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("edition_id", "position", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="workforce_department_edition_code_unique",
            )
        ]

    def clean(self) -> None:
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
        self.code = self.code.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} — {self.edition.name}"


class OnboardingDocumentType(UUIDTimeStampedModel):
    """Immutable version of an agreement or onboarding evidence request."""

    class Status(models.TextChoices):
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
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The document type must match its edition scope.")

    def save(self, *args: Any, **kwargs: Any) -> None:
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
        return f"{self.name} v{self.version} — {self.edition.name}"


class PositionTemplate(UUIDTimeStampedModel):
    """Organization-owned reusable position meaning and authority mapping."""

    class Status(models.TextChoices):
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
        ordering = ("organization_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code", "version"),
                name="workforce_position_template_version_unique",
            )
        ]

    def clean(self) -> None:
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
        return f"{self.name} v{self.version} — {self.organization.name}"


class Position(UUIDTimeStampedModel):
    """One edition position with explicit headcount and reporting line."""

    class Status(models.TextChoices):
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

    class Meta:
        ordering = ("edition_id", "department__position", "title", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code"),
                name="workforce_position_edition_code_unique",
            )
        ]

    def clean(self) -> None:  # noqa: PLR0912
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

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.code.lower()
        self.capacity_codes = [str(code).lower() for code in self.capacity_codes]
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Positions close with history instead of being deleted.",
            code="protected_workforce_position",
        )

    def __str__(self) -> str:
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
        ordering = ("position_id", "document_type__name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("position", "document_type"),
                name="workforce_position_document_unique",
            )
        ]

    def clean(self) -> None:
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
        self.full_clean()
        super().save(*args, **kwargs)


class VolunteerOpportunity(UUIDTimeStampedModel):
    """The application publication paired with every position."""

    class Status(models.TextChoices):
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

    class Meta:
        ordering = ("position__edition_id", "position__title", "id")

    @property
    def active_assignment_count(self) -> int:
        return self.position.assignments.filter(
            status=PositionAssignment.Status.ACTIVE
        ).count()

    @property
    def is_filled(self) -> bool:
        return self.active_assignment_count >= self.position.headcount

    @property
    def accepts_applications(self) -> bool:
        now = timezone.now()
        return (
            self.status == self.Status.PUBLISHED
            and not self.is_filled
            and (self.applications_open_at is None or self.applications_open_at <= now)
            and (self.applications_close_at is None or self.applications_close_at > now)
        )

    def clean(self) -> None:
        super().clean()
        if (
            self.applications_open_at
            and self.applications_close_at
            and self.applications_close_at <= self.applications_open_at
        ):
            raise ValidationError(
                {"applications_close_at": "Closing must be after opening."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Applications: {self.position}"


class VolunteerApplication(UUIDTimeStampedModel):
    """One attendee expression of interest; never an authority grant."""

    class Status(models.TextChoices):
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
        ordering = ("-submitted_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "account"),
                name="workforce_one_application_per_opportunity_account",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.account_id:
            validate_convention_subject(self.account)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.account} — {self.opportunity.position.title}"


class OnboardingDocumentRequest(UUIDTimeStampedModel):
    """Private requested/uploaded/reviewed agreement evidence."""

    class Status(models.TextChoices):
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
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Onboarding documents require the retention workflow.",
            code="protected_onboarding_document",
        )

    def __str__(self) -> str:
        return f"{self.document_type.name} — {self.account}"


class PositionAssignment(UUIDTimeStampedModel):
    """A proposed or active edition responsibility and its authority evidence."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
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

    class Meta:
        ordering = ("edition_id", "position__title", "account_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("position", "account"),
                condition=Q(status__in=("proposed", "active")),
                name="workforce_one_open_assignment_per_position_account",
            )
        ]

    def clean(self) -> None:
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
        if self.status == self.Status.ACTIVE and (
            not self.approved_by_id
            or not self.role_assignment_id
            or not self.participation_capacity_id
        ):
            raise ValidationError(
                "Active assignments require approval, role, and capacity evidence."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Assignments end with retained evidence instead of being deleted.",
            code="protected_workforce_assignment",
        )

    def __str__(self) -> str:
        return f"{self.account} — {self.position.title}"
