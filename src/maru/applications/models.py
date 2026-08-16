"""Versioned application definitions and provenance-preserving responses."""
# ruff: noqa: E501, PLR0912, PLR2004, SIM102

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug
from maru.identity.policies import validate_convention_subject

MAX_DEFINITION_CARDINALITY = 100
MAX_QUESTION_OPTIONS = 100
MAX_SECTIONS = 100
MAX_QUESTIONS = 500
MAX_ANSWER_BYTES = 65_536

POLICY_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_.:-]{2,119}$",
    message="Use a stable versioned policy code.",
    code="invalid_application_policy_code",
)
REFERENCE_KIND_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_.:-]{0,79}$",
    message="Use a registered reference kind.",
    code="invalid_application_reference_kind",
)


class ApplicationDefinitionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class ApplicationTargetKind(models.TextChoices):
    MERCH_SUBMISSION = "merch_submission", "Merchandise submission"
    DJ_SET = "dj_set", "DJ set"
    FURSUIT_DANCE_COMPETITION = "fursuit_dance_competition", "Fursuit Dance Competition"
    MAID_CAFE = "maid_cafe", "Maid Cafe"
    ADULT_FURSUIT_STRIPTEASE = "adult_fursuit_striptease", "Adult Fursuit Striptease"
    VOLUNTEER = "volunteer", "Volunteer"
    FEEDBACK = "feedback", "Feedback"
    IDEA = "idea", "Idea"
    DAMAGE_REPORT = "damage_report", "SecOps damage report"
    HELPER = "helper", "Time-bounded helper"


class ApplicationClassification(models.TextChoices):
    INTERNAL = "C1", "Internal"
    PERSONAL = "C2", "Personal"
    RESTRICTED = "C3", "Restricted"
    SECURITY_CRITICAL = "C4", "Security critical"


class ApplicationEligibilityKind(models.TextChoices):
    AUTHENTICATED_PERSON = "authenticated_person", "Authenticated person"
    EDITION_PARTICIPANT = "edition_participant", "Edition participant"
    REGISTERED_ATTENDEE = "registered_attendee", "Registered attendee"
    CONFIRMED_ATTENDEE = "confirmed_attendee", "Confirmed attendee"
    ACTIVE_VOLUNTEER = "active_volunteer", "Active volunteer"


class ApplicationQuestionType(models.TextChoices):
    SHORT_TEXT = "short_text", "Short text"
    LONG_TEXT = "long_text", "Long text"
    INTEGER = "integer", "Integer"
    DECIMAL = "decimal", "Decimal"
    BOOLEAN = "boolean", "Boolean"
    SINGLE_CHOICE = "single_choice", "Single choice"
    MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
    DATE = "date", "Date"
    TIME = "time", "Time"
    INSTANT = "instant", "Date and time"
    EMAIL = "email", "Email"
    PHONE = "phone", "Phone"
    URL = "url", "URL"
    ADDRESS = "address", "Address"
    PERSON_REFERENCE = "person_reference", "Person reference"
    DOMAIN_REFERENCE = "domain_reference", "Domain reference"
    SAFE_FILE = "safe_file", "Safety-checked file"


class ApplicationSourceBinding(models.TextChoices):
    NONE = "", "No automatic source"
    ACCOUNT_DISPLAY_NAME = "account.display_name", "Account display name"
    REGISTRATION_TELEGRAM = "registration.telegram", "Registration Telegram contact"


class ApplicationState(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


class AnswerSource(models.TextChoices):
    APPLICANT = "applicant", "Applicant"
    STAFF_CORRECTION = "staff_correction", "Staff correction"
    SYSTEM_SOURCE = "system_source", "Authoritative source binding"


class ReviewDecisionKind(models.TextChoices):
    START_REVIEW = "start_review", "Start review"
    REQUEST_CHANGES = "request_changes", "Request changes"
    ACCEPT = "accept", "Accept"
    REJECT = "reject", "Reject"


class ReviewerBasis(models.TextChoices):
    IMMUTABLE_ROLE = "immutable_role", "Immutable role version"
    NAMED_PERSON = "named_person", "Named person"


class ApplicationDefinition(UUIDTimeStampedModel):
    """One immutable-on-activation edition definition version."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_definitions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_definitions",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    version = models.PositiveIntegerField()
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    status = models.CharField(
        max_length=16,
        choices=ApplicationDefinitionStatus,
        default=ApplicationDefinitionStatus.DRAFT,
    )
    target_adapter_kind = models.CharField(max_length=48, choices=ApplicationTargetKind)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=4_000)
    purpose = models.CharField(max_length=500)
    classification = models.CharField(
        max_length=2,
        choices=ApplicationClassification,
        default=ApplicationClassification.PERSONAL,
    )
    eligibility_kind = models.CharField(
        max_length=32,
        choices=ApplicationEligibilityKind,
        default=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
    )
    max_submissions_per_person = models.PositiveSmallIntegerField(
        default=1,
        validators=(
            MinValueValidator(1),
            MaxValueValidator(MAX_DEFINITION_CARDINALITY),
        ),
    )
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    applicant_edit_until = models.DateTimeField()
    minimum_age = models.PositiveSmallIntegerField(
        default=0, validators=(MaxValueValidator(120),)
    )
    audience_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    retention_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    age_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_definitions_created",
    )
    activated_at = models.DateTimeField(null=True, blank=True, editable=False)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="application_definitions_activated",
    )
    retired_at = models.DateTimeField(null=True, blank=True, editable=False)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="application_definitions_retired",
    )

    class Meta:
        ordering = ("edition_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code", "version"),
                name="applications_definition_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "code"),
                condition=Q(status=ApplicationDefinitionStatus.ACTIVE),
                name="applications_definition_one_active",
            ),
            models.CheckConstraint(
                condition=Q(version__gt=0) & Q(aggregate_version__gt=0),
                name="applications_definition_versions_positive",
            ),
            models.CheckConstraint(
                condition=Q(max_submissions_per_person__gte=1)
                & Q(max_submissions_per_person__lte=MAX_DEFINITION_CARDINALITY),
                name="applications_definition_cardinality_bounded",
            ),
            models.CheckConstraint(
                condition=Q(minimum_age__lte=120),
                name="applications_definition_age_bounded",
            ),
            models.CheckConstraint(
                condition=Q(opens_at__lt=models.F("closes_at"))
                & Q(applicant_edit_until__lte=models.F("closes_at")),
                name="applications_definition_windows_ordered",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=ApplicationDefinitionStatus.DRAFT,
                        activated_at__isnull=True,
                        activated_by__isnull=True,
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                    )
                    | Q(
                        status=ApplicationDefinitionStatus.ACTIVE,
                        activated_at__isnull=False,
                        activated_by__isnull=False,
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                    )
                    | Q(
                        status=ApplicationDefinitionStatus.RETIRED,
                        activated_at__isnull=False,
                        activated_by__isnull=False,
                        retired_at__isnull=False,
                        retired_by__isnull=False,
                    )
                ),
                name="applications_definition_lifecycle_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status", "opens_at"),
                name="app_definition_scope_idx",
            )
        ]

    @property
    def is_sensitive(self) -> bool:
        return self.classification in {
            ApplicationClassification.RESTRICTED,
            ApplicationClassification.SECURITY_CRITICAL,
        } or self.target_adapter_kind in {
            ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
            ApplicationTargetKind.DAMAGE_REPORT,
        }

    @property
    def requires_explicit_age_policy(self) -> bool:
        return (
            self.target_adapter_kind == ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE
        )

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The application definition must match its edition.")
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError(
                {"closes_at": "Closing time must follow opening time."}
            )
        if (
            self.applicant_edit_until
            and self.closes_at
            and self.applicant_edit_until > self.closes_at
        ):
            raise ValidationError(
                {
                    "applicant_edit_until": "The applicant edit deadline cannot follow closing."
                }
            )
        if self.requires_explicit_age_policy and self.minimum_age < 18:
            raise ValidationError(
                {"minimum_age": "The adult application requires a minimum age of 18."},
                code="adult_application_minimum_age_required",
            )
        forbidden = {"default", "generic", "standard"}
        if self.status != ApplicationDefinitionStatus.DRAFT and (
            self.is_sensitive
            or self.target_adapter_kind
            in {
                ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
                ApplicationTargetKind.DAMAGE_REPORT,
            }
        ):
            if (
                not self.audience_policy_code
                or self.audience_policy_code in forbidden
                or not self.retention_policy_code
                or self.retention_policy_code in forbidden
            ):
                raise ValidationError(
                    "Restricted, adult, and case workflows require explicit versioned audience and retention policies.",
                    code="explicit_sensitive_application_policy_required",
                )
        if (
            self.status != ApplicationDefinitionStatus.DRAFT
            and self.requires_explicit_age_policy
            and (not self.age_policy_code or self.age_policy_code in forbidden)
        ):
            raise ValidationError(
                {"age_policy_code": "Choose an explicit versioned adult-age policy."},
                code="explicit_adult_age_policy_required",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.code.lower()
        if self.pk and not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).first()
            if (
                previous is not None
                and previous.status != ApplicationDefinitionStatus.DRAFT
            ):
                retirement_fields = {
                    "status",
                    "retired_at",
                    "retired_by_id",
                    "aggregate_version",
                    "updated_at",
                }
                changed = {
                    field.attname
                    for field in self._meta.concrete_fields
                    if getattr(previous, field.attname) != getattr(self, field.attname)
                }
                if (
                    previous.status != ApplicationDefinitionStatus.ACTIVE
                    or not changed <= retirement_fields
                ):
                    raise ValidationError(
                        "Active and retired definition versions are immutable.",
                        code="immutable_application_definition",
                    )
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationOwnerDepartment(UUIDTimeStampedModel):
    definition = models.ForeignKey(
        ApplicationDefinition,
        on_delete=models.PROTECT,
        related_name="owner_department_links",
    )
    department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="owned_application_definitions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "department"),
                name="applications_owner_department_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.definition_id
            and self.department_id
            and (
                self.department.organization_id != self.definition.organization_id
                or self.department.edition_id != self.definition.edition_id
                or self.department.retired_at is not None
            )
        ):
            raise ValidationError(
                {"department": "Choose a current Department in the same edition."}
            )
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Owner Departments are frozen on activation.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationReviewerRole(UUIDTimeStampedModel):
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="reviewer_roles"
    )
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        on_delete=models.PROTECT,
        related_name="application_review_queues",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "role_bundle"),
                name="applications_reviewer_role_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.definition_id and self.role_bundle_id:
            if self.definition.status != ApplicationDefinitionStatus.DRAFT:
                raise ValidationError("Reviewer roles are frozen on activation.")
            if self.role_bundle.organization_id != self.definition.organization_id:
                raise ValidationError(
                    {"role_bundle": "The role belongs to another organizer."}
                )
            required = {"applications.review"}
            if self.definition.is_sensitive:
                required.add("applications.review_sensitive")
            if not required <= set(self.role_bundle.capability_codes):
                raise ValidationError(
                    {
                        "role_bundle": "The immutable role version lacks required review capabilities."
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationReviewerPerson(UUIDTimeStampedModel):
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="reviewer_people"
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="named_application_review_queues",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "account"),
                name="applications_reviewer_person_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Named reviewers are frozen on activation.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationSection(UUIDTimeStampedModel):
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="sections"
    )
    key = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    title = models.CharField(max_length=160)
    help_text = models.TextField(blank=True, max_length=2_000)
    position = models.PositiveSmallIntegerField(validators=(MaxValueValidator(65_535),))

    class Meta:
        ordering = ("definition_id", "position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "key"), name="applications_section_key_unique"
            ),
            models.UniqueConstraint(
                fields=("definition", "position"),
                name="applications_section_position_unique",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Sections are immutable after activation.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)


def _validate_options(field_type: str, options: object) -> None:
    if not isinstance(options, list) or len(options) > MAX_QUESTION_OPTIONS:
        raise ValidationError({"options": "Options must be a bounded list."})
    choice = field_type in {
        ApplicationQuestionType.SINGLE_CHOICE,
        ApplicationQuestionType.MULTIPLE_CHOICE,
    }
    if choice and len(options) < 2:
        raise ValidationError(
            {"options": "Choice fields require at least two options."}
        )
    if not choice and options:
        raise ValidationError({"options": "Only choice fields may define options."})
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, dict) or set(option) != {"code", "label"}:
            raise ValidationError(
                {"options": "Each option requires only code and label."}
            )
        code = option.get("code")
        label = option.get("label")
        if (
            not isinstance(code, str)
            or not isinstance(label, str)
            or not code
            or len(code) > 80
            or not label.strip()
            or len(label) > 160
            or code in seen
        ):
            raise ValidationError(
                {"options": "Option codes and labels must be bounded and unique."}
            )
        seen.add(code)


class ApplicationQuestion(UUIDTimeStampedModel):
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="questions"
    )
    section = models.ForeignKey(
        ApplicationSection, on_delete=models.PROTECT, related_name="questions"
    )
    key = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    field_type = models.CharField(max_length=32, choices=ApplicationQuestionType)
    label = models.CharField(max_length=200)
    help_text = models.TextField(blank=True, max_length=2_000)
    position = models.PositiveSmallIntegerField(validators=(MaxValueValidator(65_535),))
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)
    minimum_length = models.PositiveIntegerField(null=True, blank=True)
    maximum_length = models.PositiveIntegerField(null=True, blank=True)
    minimum_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    maximum_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    maximum_choices = models.PositiveSmallIntegerField(null=True, blank=True)
    reference_kind = models.CharField(
        max_length=80, blank=True, validators=(REFERENCE_KIND_VALIDATOR,)
    )
    source_binding = models.CharField(
        max_length=32, choices=ApplicationSourceBinding, blank=True
    )
    condition = models.JSONField(default=dict, blank=True)
    purpose = models.CharField(max_length=500)
    classification = models.CharField(max_length=2, choices=ApplicationClassification)
    applicant_visible = models.BooleanField(default=True)
    applicant_writable = models.BooleanField(default=True)
    staff_visible = models.BooleanField(default=True)
    staff_writable = models.BooleanField(default=False)
    reviewer_visible = models.BooleanField(default=True)
    public_after_approval = models.BooleanField(default=False)
    api_projection = models.BooleanField(default=True)
    retention_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )

    class Meta:
        ordering = ("definition_id", "section__position", "position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "key"), name="applications_question_key_unique"
            ),
            models.UniqueConstraint(
                fields=("section", "position"),
                name="applications_question_position_unique",
            ),
            models.CheckConstraint(
                condition=Q(minimum_length__isnull=True)
                | Q(maximum_length__isnull=True)
                | Q(minimum_length__lte=models.F("maximum_length")),
                name="applications_question_length_ordered",
            ),
            models.CheckConstraint(
                condition=Q(minimum_value__isnull=True)
                | Q(maximum_value__isnull=True)
                | Q(minimum_value__lte=models.F("maximum_value")),
                name="applications_question_numeric_ordered",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Questions are immutable after activation.")
        if (
            self.section_id
            and self.definition_id
            and self.section.definition_id != self.definition_id
        ):
            raise ValidationError(
                {"section": "The section belongs to another definition."}
            )
        _validate_options(self.field_type, self.options)
        if (
            self.minimum_length is not None
            and self.maximum_length is not None
            and self.minimum_length > self.maximum_length
        ):
            raise ValidationError(
                {"maximum_length": "Maximum length must not be smaller."}
            )
        if (
            self.minimum_value is not None
            and self.maximum_value is not None
            and self.minimum_value > self.maximum_value
        ):
            raise ValidationError(
                {"maximum_value": "Maximum value must not be smaller."}
            )
        if self.field_type == ApplicationQuestionType.MULTIPLE_CHOICE:
            if self.maximum_choices is None or not 1 <= self.maximum_choices <= len(
                self.options
            ):
                raise ValidationError(
                    {"maximum_choices": "Choose a bound within the option set."}
                )
        elif self.maximum_choices is not None:
            raise ValidationError(
                {"maximum_choices": "Only multiple choice uses this bound."}
            )
        reference_types = {
            ApplicationQuestionType.PERSON_REFERENCE,
            ApplicationQuestionType.DOMAIN_REFERENCE,
        }
        if (self.field_type in reference_types) != bool(self.reference_kind):
            raise ValidationError(
                {"reference_kind": "Reference fields require one registered kind."}
            )
        if self.source_binding and self.applicant_writable:
            raise ValidationError(
                {"applicant_writable": "Automatically sourced values are read-only."}
            )
        if not isinstance(self.condition, dict):
            raise ValidationError({"condition": "Condition must be an object."})
        if self.condition:
            if set(self.condition) != {"question_key", "operator", "value"}:
                raise ValidationError({"condition": "Condition fields are closed."})
            if self.condition.get("operator") not in {
                "equals",
                "not_equals",
                "contains",
            }:
                raise ValidationError(
                    {"condition": "Choose a registered condition operator."}
                )
        if (
            self.definition.status != ApplicationDefinitionStatus.DRAFT
            and self.classification
            in {
                ApplicationClassification.RESTRICTED,
                ApplicationClassification.SECURITY_CRITICAL,
            }
            and not (
                self.retention_policy_code or self.definition.retention_policy_code
            )
        ):
            raise ValidationError(
                {
                    "retention_policy_code": "Sensitive fields require explicit retention."
                }
            )
        if (
            self.public_after_approval
            and self.classification != ApplicationClassification.INTERNAL
        ):
            raise ValidationError(
                {
                    "public_after_approval": "Only a separately reviewed C1 rendition may be public."
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationSubmission(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="submissions"
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    ordinal = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=24, choices=ApplicationState, default=ApplicationState.DRAFT
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    decided_at = models.DateTimeField(null=True, blank=True, editable=False)
    withdrawn_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "account", "ordinal"),
                name="applications_submission_ordinal_unique",
            ),
            models.CheckConstraint(
                condition=Q(ordinal__gt=0) & Q(aggregate_version__gt=0),
                name="applications_submission_versions_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state=ApplicationState.DRAFT,
                        submitted_at__isnull=True,
                        decided_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        state__in=(
                            ApplicationState.SUBMITTED,
                            ApplicationState.UNDER_REVIEW,
                            ApplicationState.CHANGES_REQUESTED,
                        ),
                        submitted_at__isnull=False,
                        decided_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        state__in=(
                            ApplicationState.ACCEPTED,
                            ApplicationState.REJECTED,
                        ),
                        submitted_at__isnull=False,
                        decided_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | Q(state=ApplicationState.WITHDRAWN, withdrawn_at__isnull=False)
                ),
                name="applications_submission_state_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "state", "created_at"),
                name="app_submission_queue_idx",
            ),
            models.Index(
                fields=("account", "edition", "created_at"),
                name="app_submission_owner_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.definition_id and (
            self.definition.organization_id != self.organization_id
            or self.definition.edition_id != self.edition_id
        ):
            raise ValidationError("The submission must match its definition scope.")
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The submission must match its edition scope.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationFileReceipt(UUIDTimeStampedModel):
    """Trusted evidence for an object-storage upload that passed safety checks."""

    class Status(models.TextChoices):
        CLEAN = "clean", "Clean"
        REJECTED = "rejected", "Rejected"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    status = models.CharField(max_length=16, choices=Status)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=120)
    storage_key = models.CharField(max_length=500)
    scanner_receipt = models.CharField(max_length=240)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "storage_key"),
                name="applications_file_storage_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0)
                & ~Q(scanner_receipt="")
                & ~Q(storage_key=""),
                name="applications_file_evidence_required",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The file receipt must match its edition scope.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValidationError({"sha256": "Use a lower-case SHA-256 digest."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("File safety receipts are immutable.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError("File receipts require the retention workflow.")


class ApplicationAnswerRevision(UUIDTimeStampedModel):
    submission = models.ForeignKey(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="answer_revisions"
    )
    question = models.ForeignKey(
        ApplicationQuestion, on_delete=models.PROTECT, related_name="answer_revisions"
    )
    sequence = models.PositiveIntegerField()
    question_key = models.SlugField(max_length=80, editable=False)
    question_type = models.CharField(
        max_length=32, choices=ApplicationQuestionType, editable=False
    )
    classification = models.CharField(
        max_length=2, choices=ApplicationClassification, editable=False
    )
    value = models.JSONField(null=True)
    source = models.CharField(max_length=24, choices=AnswerSource)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_answer_revisions",
    )
    reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("submission_id", "question_key", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "question", "sequence"),
                name="applications_answer_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="applications_answer_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    source__in=(AnswerSource.APPLICANT, AnswerSource.SYSTEM_SOURCE),
                    reason="",
                )
                | (Q(source=AnswerSource.STAFF_CORRECTION) & ~Q(reason="")),
                name="applications_answer_staff_reason_required",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.submission_id
            and self.question_id
            and self.question.definition_id != self.submission.definition_id
        ):
            raise ValidationError(
                {"question": "The question belongs to another definition."}
            )
        if self.question_id and (
            self.question_key != self.question.key
            or self.question_type != self.question.field_type
            or self.classification != self.question.classification
        ):
            raise ValidationError("Answer question snapshots must be authoritative.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Answer revisions are append-only.", code="immutable_application_answer"
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Answer revisions are append-only.", code="protected_application_answer"
        )


class ApplicationReviewDecision(UUIDTimeStampedModel):
    submission = models.ForeignKey(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="review_decisions"
    )
    sequence = models.PositiveIntegerField()
    decision = models.CharField(max_length=24, choices=ReviewDecisionKind)
    from_state = models.CharField(max_length=24, choices=ApplicationState)
    to_state = models.CharField(max_length=24, choices=ApplicationState)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_review_decisions",
    )
    reviewer_basis = models.CharField(max_length=24, choices=ReviewerBasis)
    reviewer_role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="application_review_decisions",
    )
    reason = models.CharField(max_length=500)

    class Meta:
        ordering = ("submission_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "sequence"),
                name="applications_review_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0) & ~Q(reason=""),
                name="applications_review_evidence_required",
            ),
            models.CheckConstraint(
                condition=Q(
                    reviewer_basis=ReviewerBasis.IMMUTABLE_ROLE,
                    reviewer_role_bundle__isnull=False,
                )
                | Q(
                    reviewer_basis=ReviewerBasis.NAMED_PERSON,
                    reviewer_role_bundle__isnull=True,
                ),
                name="applications_review_basis_complete",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Review decisions are append-only.", code="immutable_application_review"
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Review decisions are append-only.", code="protected_application_review"
        )


class ApplicationTargetRecord(UUIDTimeStampedModel):
    """Closed discriminated adapter receipt, never an untyped response sheet."""

    submission = models.OneToOneField(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="target_record"
    )
    adapter_kind = models.CharField(max_length=48, choices=ApplicationTargetKind)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_targets_created",
    )

    def clean(self) -> None:
        super().clean()
        if self.submission_id and (
            self.submission.state != ApplicationState.ACCEPTED
            or self.adapter_kind != self.submission.definition.target_adapter_kind
        ):
            raise ValidationError(
                "The target adapter must match one accepted application."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Typed target receipts are immutable.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError("Typed target receipts are retained.")


class ApplicationCommandReceipt(UUIDTimeStampedModel):
    class Action(models.TextChoices):
        DEFINITION_CREATED = "definition_created", "Definition created"
        SUCCESSOR_CREATED = "successor_created", "Successor created"
        DEFINITION_CONFIGURED = "definition_configured", "Definition configured"
        SECTION_ADDED = "section_added", "Section added"
        QUESTION_ADDED = "question_added", "Question added"
        DEFINITION_ACTIVATED = "definition_activated", "Definition activated"
        DEFINITION_RETIRED = "definition_retired", "Definition retired"
        SUBMISSION_STARTED = "submission_started", "Submission started"
        ANSWER_REVISED = "answer_revised", "Answer revised"
        APPLICATION_SUBMITTED = "application_submitted", "Application submitted"
        REVIEW_DECIDED = "review_decided", "Review decided"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    action = models.CharField(max_length=32, choices=Action)
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    definition = models.ForeignKey(
        ApplicationDefinition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    submission = models.ForeignKey(
        ApplicationSubmission,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    target_id = models.UUIDField(null=True, blank=True)
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="applications_command_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0) & ~Q(source_channel=""),
                name="applications_command_evidence_required",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Application command receipts are append-only.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError("Application command receipts are retained.")
