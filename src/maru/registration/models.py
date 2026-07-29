"""Registration configuration, commerce, and operational history."""

from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_currency_codes, validate_lowercase_slug
from maru.participation.models import validate_capacity_code
from maru.registration.profile_choices import (
    MAX_BIO_LENGTH,
    OTHER_PRONOUN_CODE,
    PRONOUN_CODES,
    pronoun_display,
    validate_spoken_language_codes,
)

MAX_QUESTION_OPTION_LENGTH = 120
MINIMUM_CHOICE_OPTIONS = 2
MINIMUM_PAYMENT_WINDOW_MINUTES = 15
MAXIMUM_PAYMENT_WINDOW_MINUTES = 60 * 24 * 30
COUNTRY_CODE_LENGTH = 2


class TemplateStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"


class ConfigurationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class QuestionFieldType(models.TextChoices):
    SHORT_TEXT = "short_text", "Short text"
    LONG_TEXT = "long_text", "Long text"
    BOOLEAN = "boolean", "Yes or no"
    SINGLE_CHOICE = "single_choice", "Single choice"
    MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
    INTEGER = "integer", "Whole number"


class QuestionClassification(models.TextChoices):
    INTERNAL = "C1", "Internal"
    PERSONAL = "C2", "Personal"


class QuestionVisibility(models.TextChoices):
    ATTENDEE_AND_STAFF = "attendee_and_staff", "Attendee and registration staff"
    REGISTRATION_STAFF = "registration_staff", "Registration staff only"


def _validate_question_options(
    *,
    field_type: str,
    options: object,
) -> None:
    if not isinstance(options, list) or any(
        not isinstance(option, str)
        or not option.strip()
        or len(option) > MAX_QUESTION_OPTION_LENGTH
        for option in options
    ):
        raise ValidationError(
            {"options": "Options must be a list of short non-empty labels."},
            code="invalid_question_options",
        )
    normalized = [option.strip() for option in options]
    if len(set(normalized)) != len(normalized):
        raise ValidationError(
            {"options": "Question option labels must be unique."},
            code="duplicate_question_option",
        )
    choice_types = {
        QuestionFieldType.SINGLE_CHOICE,
        QuestionFieldType.MULTIPLE_CHOICE,
    }
    if field_type in choice_types and len(normalized) < MINIMUM_CHOICE_OPTIONS:
        raise ValidationError(
            {"options": "Choice questions require at least two options."},
            code="question_options_required",
        )
    if field_type not in choice_types and normalized:
        raise ValidationError(
            {"options": "Only choice questions may define options."},
            code="question_options_not_allowed",
        )


class RegistrationTemplate(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_templates",
    )
    series = models.ForeignKey(
        "organizations.ConventionSeries",
        on_delete=models.PROTECT,
        related_name="registration_templates",
        null=True,
        blank=True,
    )
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=TemplateStatus,
        default=TemplateStatus.DRAFT,
    )
    created_by_id = models.UUIDField()
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("organization_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("organization"),
                Lower("code"),
                "version",
                name="registration_template_code_version_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="published", published_at__isnull=False)
                    | Q(status__in=("draft", "retired"))
                ),
                name="registration_template_publish_time_matches_status",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.series_id
            and self.series is not None
            and self.organization_id
            and self.series.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"series": "The template series must belong to its organization."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.code.lower()
        if not self._state.adding:
            current = type(self).objects.filter(pk=self.pk).first()
            if current is not None and current.status == TemplateStatus.PUBLISHED:
                allowed = {"status", "updated_at"}
                update_fields = set(kwargs.get("update_fields") or ())
                if self.status != TemplateStatus.RETIRED or (
                    update_fields and not update_fields <= allowed
                ):
                    raise ValidationError(
                        "Published registration templates are immutable.",
                        code="immutable_registration_template",
                    )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration templates use versioning and retirement.",
            code="protected_registration_template",
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} — {self.organization.name}"


class AbstractQuestion(UUIDTimeStampedModel):
    key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    label = models.CharField(max_length=200)
    help_text = models.TextField(blank=True)
    field_type = models.CharField(max_length=24, choices=QuestionFieldType)
    required = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    options = models.JSONField(default=list, blank=True)
    purpose = models.CharField(max_length=240)
    visibility = models.CharField(
        max_length=30,
        choices=QuestionVisibility,
        default=QuestionVisibility.ATTENDEE_AND_STAFF,
    )
    classification = models.CharField(
        max_length=2,
        choices=QuestionClassification,
        default=QuestionClassification.PERSONAL,
    )
    condition_question_key = models.SlugField(max_length=80, blank=True)
    condition_value = models.CharField(max_length=120, blank=True)

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        _validate_question_options(
            field_type=self.field_type,
            options=self.options,
        )
        if bool(self.condition_question_key) != bool(self.condition_value):
            raise ValidationError(
                "A conditional question requires both a source key and value.",
                code="incomplete_question_condition",
            )
        if self.condition_question_key == self.key:
            raise ValidationError(
                {"condition_question_key": "A question cannot depend on itself."},
                code="recursive_question_condition",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.lower()
        self.condition_question_key = self.condition_question_key.lower()
        self.full_clean()
        super().save(*args, **kwargs)


class RegistrationTemplateSection(UUIDTimeStampedModel):
    template = models.ForeignKey(
        RegistrationTemplate,
        on_delete=models.PROTECT,
        related_name="sections",
    )
    key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "key"),
                name="registration_template_section_key_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Only draft templates may change sections.",
                code="immutable_registration_template",
            )
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Published template sections are immutable.",
                code="immutable_registration_template",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.template.name}: {self.title}"


class RegistrationTemplateQuestion(AbstractQuestion):
    section = models.ForeignKey(
        RegistrationTemplateSection,
        on_delete=models.PROTECT,
        related_name="questions",
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        RegistrationTemplate,
        on_delete=models.PROTECT,
        related_name="questions",
    )

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "key"),
                name="registration_template_question_key_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Only draft templates may change questions.",
                code="immutable_registration_template",
            )
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if (
            self.section_id
            and self.section is not None
            and self.section.template_id != self.template_id
        ):
            raise ValidationError(
                {"section": "The section must belong to this template."}
            )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Published template questions are immutable.",
                code="immutable_registration_template",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.template.name}: {self.label}"


class AbstractProduct(UUIDTimeStampedModel):
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    price_minor = models.PositiveBigIntegerField(default=0)
    capacity = models.PositiveIntegerField()
    position = models.PositiveIntegerField(default=0)
    entitlement_code = models.SlugField(
        max_length=80,
        validators=[validate_lowercase_slug],
    )
    entitlement_name = models.CharField(max_length=160)
    sales_open_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional product-specific opening time.",
    )
    sales_close_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional product-specific closing time.",
    )
    required_capacity_codes = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Optional active participation-capacity codes. A person needs at "
            "least one of them to select this product."
        ),
    )
    eligibility_explanation = models.CharField(
        max_length=240,
        blank=True,
        help_text="Attendee-facing explanation for a restricted offer.",
    )
    waitlist_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Allow an eligible person to join the waitlist when capacity is full."
        ),
    )
    payment_window_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=(
            MinValueValidator(MINIMUM_PAYMENT_WINDOW_MINUTES),
            MaxValueValidator(MAXIMUM_PAYMENT_WINDOW_MINUTES),
        ),
        help_text="Optional override for the edition's default payment deadline.",
    )

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        if (
            self.sales_open_at is not None
            and self.sales_close_at is not None
            and self.sales_close_at <= self.sales_open_at
        ):
            raise ValidationError(
                {"sales_close_at": "Product sales must close after they open."},
                code="product_sales_period_invalid",
            )
        codes = self.required_capacity_codes
        if not isinstance(codes, list) or any(
            not isinstance(code, str) or not code for code in codes
        ):
            raise ValidationError(
                {
                    "required_capacity_codes": (
                        "Capacity eligibility must be a list of stable codes."
                    )
                },
                code="invalid_product_capacity_codes",
            )
        if len(set(codes)) != len(codes):
            raise ValidationError(
                {
                    "required_capacity_codes": (
                        "Capacity eligibility codes must be unique."
                    )
                },
                code="duplicate_product_capacity_code",
            )
        for code in codes:
            validate_capacity_code(code)
        if codes and not self.eligibility_explanation.strip():
            raise ValidationError(
                {
                    "eligibility_explanation": (
                        "Restricted products need an attendee-facing explanation."
                    )
                },
                code="product_eligibility_explanation_required",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.code.lower()
        self.entitlement_code = self.entitlement_code.lower()
        if isinstance(self.required_capacity_codes, list):
            self.required_capacity_codes = [
                str(code).lower() for code in self.required_capacity_codes
            ]
        self.full_clean()
        super().save(*args, **kwargs)


class RegistrationTemplateProduct(AbstractProduct):
    template = models.ForeignKey(
        RegistrationTemplate,
        on_delete=models.PROTECT,
        related_name="products",
    )

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "code"),
                name="registration_template_product_code_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Only draft templates may change products.",
                code="immutable_registration_template",
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.template.status != TemplateStatus.DRAFT:
            raise ValidationError(
                "Published template products are immutable.",
                code="immutable_registration_template",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.template.name}: {self.name}"


class RegistrationConfiguration(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_configurations",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="registration_configurations",
    )
    name = models.CharField(max_length=160)
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ConfigurationStatus,
        default=ConfigurationStatus.DRAFT,
    )
    source_template = models.ForeignKey(
        RegistrationTemplate,
        on_delete=models.PROTECT,
        related_name="derived_configurations",
        null=True,
        blank=True,
    )
    source_edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="copied_registration_configurations",
        null=True,
        blank=True,
    )
    review_required = models.BooleanField(default=True)
    review_note = models.TextField(blank=True)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    minimum_age = models.PositiveSmallIntegerField(
        default=18,
        validators=(MinValueValidator(0), MaxValueValidator(120)),
        help_text=(
            "Absolute minimum age. Values below 18 require an enabled, reviewed "
            "guardian policy before activation."
        ),
    )
    default_payment_window_minutes = models.PositiveIntegerField(
        default=24 * 60,
        validators=(
            MinValueValidator(MINIMUM_PAYMENT_WINDOW_MINUTES),
            MaxValueValidator(MAXIMUM_PAYMENT_WINDOW_MINUTES),
        ),
        help_text=(
            "Time allowed to complete payment after a place is reserved or offered."
        ),
    )
    waitlist_enabled = models.BooleanField(
        default=True,
        help_text="Allow eligible attendees to wait when admission capacity is full.",
    )
    automatic_waitlist_promotion = models.BooleanField(
        default=True,
        help_text="Offer released places to the oldest eligible waitlist entry.",
    )
    created_by_id = models.UUIDField()
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "version"),
                name="registration_configuration_edition_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition",),
                condition=Q(status="active"),
                name="one_active_registration_configuration_per_edition",
            ),
            models.CheckConstraint(
                condition=Q(closes_at__gt=models.F("opens_at")),
                name="registration_configuration_closes_after_open",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="registration_configuration_capacity_positive",
            ),
            models.CheckConstraint(
                condition=Q(minimum_age__gte=0, minimum_age__lte=120),
                name="registration_configuration_adult_age_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="active", activated_at__isnull=False)
                    | Q(status__in=("draft", "retired"))
                ),
                name="registration_configuration_activation_matches_status",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.organization_id and self.edition_id:
            if self.edition.organization_id != self.organization_id:
                raise ValidationError(
                    {"edition": "The edition must belong to the organization."}
                )
            if self.edition.lifecycle in {"archived", "cancelled"}:
                raise ValidationError(
                    {"edition": "Registration cannot change for this edition."},
                    code="edition_registration_closed",
                )
        if (
            self.source_template_id
            and self.source_template is not None
            and self.source_template.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"source_template": "Template and target must share an organization."}
            )
        if (
            self.source_edition_id
            and self.source_edition is not None
            and self.source_edition.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"source_edition": "Source and target must share an organization."}
            )
        validate_currency_codes([self.currency])

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.currency = self.currency.upper()
        if not self._state.adding:
            current_status = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            if current_status in {
                ConfigurationStatus.ACTIVE,
                ConfigurationStatus.RETIRED,
            }:
                allowed_transition = (
                    current_status == ConfigurationStatus.ACTIVE
                    and self.status == ConfigurationStatus.RETIRED
                )
                if not allowed_transition:
                    raise ValidationError(
                        "Active registration configuration versions are immutable.",
                        code="immutable_registration_configuration",
                    )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration configurations use versioning and retirement.",
            code="protected_registration_configuration",
        )

    def __str__(self) -> str:
        return f"{self.edition.name}: {self.name} v{self.version}"


class RegistrationSection(UUIDTimeStampedModel):
    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="sections",
    )
    key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("configuration", "key"),
                name="registration_section_configuration_key_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Only draft registration versions may change sections.",
                code="immutable_registration_configuration",
            )
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Active registration sections are immutable.",
                code="immutable_registration_configuration",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.title}"


class RegistrationQuestion(AbstractQuestion):
    section = models.ForeignKey(
        RegistrationSection,
        on_delete=models.PROTECT,
        related_name="questions",
        null=True,
        blank=True,
    )
    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="questions",
    )

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("configuration", "key"),
                name="registration_question_configuration_key_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Only draft registration versions may change questions.",
                code="immutable_registration_configuration",
            )
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if (
            self.section_id
            and self.section is not None
            and self.section.configuration_id != self.configuration_id
        ):
            raise ValidationError(
                {"section": "The section must belong to this configuration."}
            )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Active registration questions are immutable.",
                code="immutable_registration_configuration",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.label}"


class AdmissionProduct(AbstractProduct):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        HIDDEN = "hidden", "Hidden"

    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="products",
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.AVAILABLE,
    )

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("configuration", "code"),
                name="registration_product_configuration_code_unique",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="registration_product_capacity_positive",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Only draft registration versions may change products.",
                code="immutable_registration_configuration",
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Active registration products are immutable.",
                code="immutable_registration_configuration",
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.name}"


class Registration(UUIDTimeStampedModel):
    class State(models.TextChoices):
        GUARDIAN_PENDING = "guardian_pending", "Guardian consent pending"
        WAITLISTED = "waitlisted", "Waitlisted"
        PAYMENT_PENDING = "payment_pending", "Payment pending"
        CONFIRMED = "confirmed", "Confirmed"
        CHECKED_IN = "checked_in", "Checked in"
        EXPIRED = "expired", "Payment expired"
        CANCELLED = "cancelled", "Cancelled"

    class ConfirmationBasis(models.TextChoices):
        FREE = "free", "No payment required"
        PROVIDER = "provider", "Payment provider"
        WAIVER = "waiver", "Authorized waiver"

    class SubmissionSource(models.TextChoices):
        SELF = "self", "Attendee self-service"
        STAFF_ASSISTED = "staff_assisted", "Staff-assisted registration"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    participation = models.OneToOneField(
        "participation.Participation",
        on_delete=models.PROTECT,
        related_name="registration",
    )
    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    product = models.ForeignKey(
        AdmissionProduct,
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    reference = models.CharField(max_length=24)
    state = models.CharField(max_length=24, choices=State)
    aggregate_version = models.PositiveIntegerField(default=1, editable=False)
    product_name_snapshot = models.CharField(max_length=160)
    price_minor_snapshot = models.PositiveBigIntegerField()
    currency_snapshot = models.CharField(max_length=3)
    submitted_at = models.DateTimeField()
    waitlisted_at = models.DateTimeField(null=True, blank=True)
    offered_at = models.DateTimeField(null=True, blank=True)
    payment_due_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    confirmation_basis = models.CharField(
        max_length=20,
        choices=ConfirmationBasis,
        blank=True,
    )
    submission_source = models.CharField(
        max_length=20,
        choices=SubmissionSource,
        default=SubmissionSource.SELF,
    )
    submitted_by = models.ForeignKey(
        "identity.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registrations_submitted_on_behalf",
    )
    staff_submission_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-submitted_at", "reference", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "account"),
                name="one_registration_per_account_and_edition",
            ),
            models.UniqueConstraint(
                fields=("edition", "reference"),
                name="registration_reference_unique_within_edition",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gte=1),
                name="registration_aggregate_version_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "state", "submitted_at"),
                name="registration_staff_queue_idx",
            ),
            models.Index(
                fields=("organization", "edition", "state", "payment_due_at"),
                name="registration_payment_due_idx",
            ),
            models.Index(
                fields=("product", "state", "waitlisted_at"),
                name="registration_waitlist_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.edition_id
            and self.organization_id
            and self.edition.organization_id != self.organization_id
        ):
            raise ValidationError("Registration edition and tenant do not match.")
        if self.participation_id and (
            self.participation.organization_id != self.organization_id
            or self.participation.edition_id != self.edition_id
            or self.participation.account_id != self.account_id
        ):
            raise ValidationError(
                "Registration participation does not match its scope and account."
            )
        if self.configuration_id and (
            self.configuration.organization_id != self.organization_id
            or self.configuration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Registration configuration does not match its scope."
            )
        if self.product_id and self.product.configuration_id != self.configuration_id:
            raise ValidationError(
                "Registration product does not belong to its configuration."
            )
        if self.submission_source == self.SubmissionSource.SELF and (
            self.submitted_by_id is not None or self.staff_submission_reason
        ):
            raise ValidationError(
                "Self-service registrations cannot contain staff-assistance evidence."
            )
        if self.submission_source == self.SubmissionSource.STAFF_ASSISTED and (
            self.submitted_by_id is None or not self.staff_submission_reason.strip()
        ):
            raise ValidationError(
                "Staff-assisted registration requires actor and reason evidence."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registrations require a reasoned cancellation workflow.",
            code="protected_registration",
        )

    def __str__(self) -> str:
        return (
            f"{self.edition.name}: {self.account} — "
            f"{self.reference} ({self.get_state_display()})"
        )


REGISTRATION_STATE_CHOICES = Registration.State.choices


class MinorRegistrationPolicy(UUIDTimeStampedModel):
    """Jurisdiction-reviewed guardian policy attached to one form version."""

    configuration = models.OneToOneField(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="minor_policy",
    )
    enabled = models.BooleanField(default=False)
    minor_age_threshold = models.PositiveSmallIntegerField(default=18)
    guardian_notice_version = models.CharField(max_length=40)
    jurisdiction_code = models.CharField(max_length=40)
    review_reference = models.CharField(max_length=120)
    reviewed_by = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="reviewed_minor_registration_policies",
    )
    reviewed_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = "minor registration policies"

    def clean(self) -> None:
        super().clean()
        if self.configuration_id and (
            self.configuration.status != ConfigurationStatus.DRAFT
        ):
            raise ValidationError(
                "Minor policy is configured and reviewed before form activation.",
                code="minor_policy_configuration_immutable",
            )
        if (
            self.configuration_id
            and self.minor_age_threshold <= self.configuration.minimum_age
        ):
            raise ValidationError(
                "The guardian threshold must be above the absolute minimum age.",
                code="minor_policy_age_band_invalid",
            )
        if self.enabled and (
            not self.guardian_notice_version.strip()
            or not self.jurisdiction_code.strip()
            or not self.review_reference.strip()
        ):
            raise ValidationError(
                "Enabled minor registration needs reviewed jurisdiction evidence.",
                code="minor_policy_review_required",
            )


class GuardianConsent(UUIDTimeStampedModel):
    """Single-use guardian authorization for one minor registration."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    registration = models.OneToOneField(
        Registration,
        on_delete=models.PROTECT,
        related_name="guardian_consent",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    policy = models.ForeignKey(
        MinorRegistrationPolicy,
        on_delete=models.PROTECT,
        related_name="guardian_consents",
    )
    guardian_name = models.CharField(max_length=200)
    guardian_email = models.EmailField()
    relationship = models.CharField(max_length=80)
    notice_version = models.CharField(max_length=40)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PENDING,
    )
    requested_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    guardian_name_at_decision = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("requested_at", "id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "expires_at"),
                name="reg_guardian_consent_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
            or self.policy.configuration_id != self.registration.configuration_id
        ):
            raise ValidationError(
                "Guardian consent does not match registration scope and policy.",
                code="guardian_consent_scope_mismatch",
            )


class MediaReviewStatus(models.TextChoices):
    NONE = "none", "No image"
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class MediaSafetyReceipt(UUIDTimeStampedModel):
    """Immutable malware/decoder receipt for one stored media revision."""

    class MediaKind(models.TextChoices):
        PROFILE_PHOTO = "profile_photo", "Profile photo"
        FURSUIT_PHOTO = "fursuit_photo", "Fursuit photo"

    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    account_id = models.UUIDField()
    media_kind = models.CharField(max_length=24, choices=MediaKind)
    media_id = models.UUIDField()
    storage_name = models.CharField(max_length=255)
    original_sha256 = models.CharField(max_length=64)
    sanitized_sha256 = models.CharField(max_length=64)
    scanner_code = models.CharField(max_length=80)
    decoder_version = models.CharField(max_length=40)
    content_type = models.CharField(max_length=80)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    byte_count = models.PositiveIntegerField()
    scanned_at = models.DateTimeField()

    class Meta:
        ordering = ("-scanned_at", "-id")
        indexes = [
            models.Index(
                fields=("media_kind", "media_id", "storage_name"),
                name="reg_media_safety_lookup_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("media_kind", "media_id", "sanitized_sha256"),
                name="media_safety_revision_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Media safety receipts are immutable.",
                code="immutable_media_safety_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Media safety receipts require the media retention workflow.",
            code="protected_media_safety_receipt",
        )


def registration_profile_photo_path(
    profile: "AttendeeRegistrationProfile",
    filename: str,
) -> str:
    extension = filename.rsplit(".", maxsplit=1)[-1].lower()
    return (
        f"private/registration-profiles/{profile.edition_id}/"
        f"{profile.id}/profile.{extension}"
    )


def registration_fursuit_photo_path(
    fursuit: "AttendeeFursuit",
    filename: str,
) -> str:
    extension = filename.rsplit(".", maxsplit=1)[-1].lower()
    return (
        f"private/registration-profiles/{fursuit.edition_id}/"
        f"{fursuit.profile_id}/fursuits/{fursuit.id}.{extension}"
    )


class AttendeeRegistrationProfile(UUIDTimeStampedModel):
    """Edition-owned registration identity and contact data."""

    registration = models.OneToOneField(
        Registration,
        on_delete=models.PROTECT,
        related_name="attendee_profile",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="attendee_registration_profiles",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="attendee_registration_profiles",
    )
    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="attendee_registration_profiles",
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    real_name = models.CharField(max_length=200)
    date_of_birth = models.DateField()
    address_line_1 = models.CharField(max_length=200)
    address_line_2 = models.CharField(max_length=200, blank=True)
    locality = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=32)
    region = models.CharField(max_length=120)
    country_code = models.CharField(max_length=2)
    emergency_contact_name = models.CharField(max_length=200)
    emergency_contact_phone = models.CharField(max_length=40)
    phone_number = models.CharField(max_length=40)
    telegram_handle = models.CharField(max_length=64, blank=True)
    pronoun_code = models.CharField(max_length=24, default="they_them")
    other_pronouns = models.CharField(max_length=80, blank=True)
    pronouns = models.CharField(max_length=80)
    bio = models.TextField(max_length=MAX_BIO_LENGTH, blank=True)
    spoken_language_codes = models.JSONField(
        default=list,
        validators=[validate_spoken_language_codes],
    )
    brings_fursuits = models.BooleanField(default=False)
    profile_photo = models.FileField(
        upload_to=registration_profile_photo_path,
        blank=True,
        max_length=255,
        validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp"))],
    )
    profile_photo_status = models.CharField(
        max_length=16,
        choices=MediaReviewStatus,
        default=MediaReviewStatus.NONE,
    )
    profile_photo_reviewed_by = models.ForeignKey(
        "identity.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="profile_photo_reviews",
    )
    profile_photo_reviewed_at = models.DateTimeField(null=True, blank=True)
    profile_photo_review_note = models.CharField(max_length=500, blank=True)
    profile_photo_reused_from_id = models.UUIDField(null=True, blank=True)
    directory_visible = models.BooleanField(default=False)
    directory_country_code = models.CharField(
        max_length=2,
        blank=True,
        help_text=(
            "Optional country code entered specifically for the public attendee "
            "directory; it is not copied from the address automatically."
        ),
    )
    directory_consent_version = models.CharField(max_length=40, blank=True)
    directory_consent_at = models.DateTimeField(null=True, blank=True)
    collection_notice_version = models.CharField(max_length=40)

    class Meta:
        ordering = ("edition_id", "account_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "account"),
                name="one_attendee_profile_per_account_and_edition",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "directory_visible"),
                name="registration_prof_dir_idx",
            ),
            models.Index(
                fields=("organization", "edition", "country_code"),
                name="registration_prof_country_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
            or self.registration.account_id != self.account_id
        ):
            raise ValidationError(
                "The attendee profile does not match its registration scope."
            )
        if self.pronoun_code not in PRONOUN_CODES:
            raise ValidationError(
                {"pronoun_code": "Choose a pronoun option from the platform list."},
                code="unknown_pronoun",
            )
        if self.pronoun_code == OTHER_PRONOUN_CODE and not self.other_pronouns.strip():
            raise ValidationError(
                {"other_pronouns": "Enter the pronouns you want displayed."},
                code="other_pronouns_required",
            )
        if self.pronoun_code != OTHER_PRONOUN_CODE and self.other_pronouns:
            raise ValidationError(
                {"other_pronouns": "Only use this field with Other pronouns."},
                code="other_pronouns_not_applicable",
            )
        expected_pronouns = pronoun_display(
            self.pronoun_code,
            self.other_pronouns,
        )
        if self.pronouns != expected_pronouns:
            raise ValidationError(
                {
                    "pronouns": (
                        "The displayed pronouns do not match the selected option."
                    )
                },
                code="pronoun_display_mismatch",
            )
        has_profile_photo = bool(self.profile_photo)
        if has_profile_photo == (self.profile_photo_status == MediaReviewStatus.NONE):
            raise ValidationError(
                {
                    "profile_photo_status": (
                        "An image must be pending, approved, or rejected; "
                        "a missing image must use No image."
                    )
                },
                code="profile_photo_status_mismatch",
            )
        reviewed = self.profile_photo_status in (
            MediaReviewStatus.APPROVED,
            MediaReviewStatus.REJECTED,
        )
        if reviewed != bool(
            self.profile_photo_reviewed_by_id and self.profile_photo_reviewed_at
        ):
            raise ValidationError(
                {
                    "profile_photo_status": (
                        "Approved and rejected images require reviewer evidence."
                    )
                },
                code="profile_photo_review_evidence_mismatch",
            )
        if not self.directory_visible and (
            self.directory_country_code
            or self.directory_consent_version
            or self.directory_consent_at
        ):
            raise ValidationError(
                {
                    "directory_visible": (
                        "Withdrawn public-list consent must clear its evidence."
                    )
                },
                code="directory_consent_mismatch",
            )
        if self.directory_country_code and (
            len(self.directory_country_code) != COUNTRY_CODE_LENGTH
            or not self.directory_country_code.isalpha()
        ):
            raise ValidationError(
                {
                    "directory_country_code": (
                        "Use a two-letter country code for the public directory."
                    )
                },
                code="invalid_directory_country_code",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.country_code = self.country_code.upper()
        self.directory_country_code = self.directory_country_code.upper()
        self.telegram_handle = self.telegram_handle.strip().lstrip("@")
        self.pronoun_code = self.pronoun_code.strip().lower()
        self.other_pronouns = self.other_pronouns.strip()
        self.pronouns = pronoun_display(self.pronoun_code, self.other_pronouns)
        self.spoken_language_codes = [
            str(code).lower() for code in self.spoken_language_codes
        ]
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration profiles require the retention workflow.",
            code="protected_registration_profile",
        )

    def __str__(self) -> str:
        return f"{self.registration.reference}: registration profile"


class AttendeeFursuit(UUIDTimeStampedModel):
    """One optional edition-profile fursuit with separately moderated media."""

    profile = models.ForeignKey(
        AttendeeRegistrationProfile,
        on_delete=models.PROTECT,
        related_name="fursuits",
    )
    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="attendee_fursuits",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="attendee_fursuits",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="attendee_fursuits",
    )
    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="attendee_fursuits",
    )
    position = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    species = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    photo = models.FileField(
        upload_to=registration_fursuit_photo_path,
        blank=True,
        max_length=255,
        validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp"))],
    )
    photo_status = models.CharField(
        max_length=16,
        choices=MediaReviewStatus,
        default=MediaReviewStatus.NONE,
    )
    photo_reviewed_by = models.ForeignKey(
        "identity.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fursuit_photo_reviews",
    )
    photo_reviewed_at = models.DateTimeField(null=True, blank=True)
    photo_review_note = models.CharField(max_length=500, blank=True)
    photo_reused_from_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "profile_id", "position", "id")
        indexes = [
            models.Index(
                fields=("organization", "edition", "photo_status"),
                name="reg_fursuit_review_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "position"),
                condition=Q(is_active=True),
                name="one_fursuit_per_profile_position",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.profile_id and (
            self.profile.registration_id != self.registration_id
            or self.profile.organization_id != self.organization_id
            or self.profile.edition_id != self.edition_id
            or self.profile.account_id != self.account_id
        ):
            raise ValidationError(
                "The fursuit does not match its attendee-profile scope.",
                code="fursuit_scope_mismatch",
            )
        has_photo = bool(self.photo)
        if has_photo == (self.photo_status == MediaReviewStatus.NONE):
            raise ValidationError(
                {
                    "photo_status": (
                        "An image must be pending, approved, or rejected; "
                        "a missing image must use No image."
                    )
                },
                code="fursuit_photo_status_mismatch",
            )
        reviewed = self.photo_status in (
            MediaReviewStatus.APPROVED,
            MediaReviewStatus.REJECTED,
        )
        if reviewed != bool(self.photo_reviewed_by_id and self.photo_reviewed_at):
            raise ValidationError(
                {
                    "photo_status": (
                        "Approved and rejected images require reviewer evidence."
                    )
                },
                code="fursuit_photo_review_evidence_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.name = self.name.strip()
        self.species = self.species.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Fursuits are deactivated through the profile workflow.",
            code="protected_attendee_fursuit",
        )

    def __str__(self) -> str:
        return f"{self.profile.registration.reference}: {self.name}"


class RegistrationSubmission(UUIDTimeStampedModel):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.PROTECT,
        related_name="submission",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    configuration_version = models.PositiveIntegerField()
    schema_snapshot = models.JSONField()
    answers = models.JSONField()
    submitted_at = models.DateTimeField()

    class Meta:
        ordering = ("submitted_at", "id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration submissions are immutable.",
                code="immutable_registration_submission",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration submissions require the retention workflow.",
            code="protected_registration_submission",
        )


class RegistrationCommandReceipt(UUIDTimeStampedModel):
    """Idempotency evidence for one headless registration command."""

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    account = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="registration_command_receipts",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    result_state = models.CharField(max_length=24, choices=Registration.State)
    result_reference = models.CharField(max_length=24)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "edition_id", "idempotency_key"),
                name="registration_headless_idempotency_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration command receipts are immutable.",
                code="immutable_registration_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration command receipts require the retention workflow.",
            code="protected_registration_command_receipt",
        )


class PaymentProviderAccount(UUIDTimeStampedModel):
    """Tenant-selected hosted payment adapter configuration; secrets stay external."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_provider_accounts",
    )
    code = models.SlugField(max_length=40)
    display_name = models.CharField(max_length=120)
    adapter = models.CharField(max_length=40)
    api_base_url = models.URLField(max_length=300)
    credential_env_var = models.CharField(max_length=120)
    webhook_secret_env_var = models.CharField(max_length=120)
    enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ("organization_id", "code", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code"),
                name="payment_provider_code_unique_per_org",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.enabled:
            parsed = urlsplit(self.api_base_url)
            hostname = (parsed.hostname or "").casefold()
            allowed_hosts = {
                str(host).casefold()
                for host in getattr(settings, "MARU_PAYMENT_PROVIDER_HOSTS", ())
            }
            if (
                parsed.scheme != "https"
                or not hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValidationError(
                    "Enabled payment providers require an HTTPS API URL.",
                    code="payment_provider_https_required",
                )
            if allowed_hosts and hostname not in allowed_hosts:
                raise ValidationError(
                    "The provider API host is not permitted by deployment policy.",
                    code="payment_provider_host_not_allowed",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class PaymentIntent(UUIDTimeStampedModel):
    """Local source of truth for one hosted/tokenized checkout request."""

    class Status(models.TextChoices):
        CREATING = "creating", "Creating"
        CHECKOUT_READY = "checkout_ready", "Checkout ready"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"
        UNCERTAIN = "uncertain", "Uncertain"
        MISMATCH = "mismatch", "Mismatch"
        LATE = "late", "Late success"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="payment_intents",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="payment_intents",
    )
    idempotency_key = models.UUIDField()
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=24,
        choices=Status,
        default=Status.CREATING,
    )
    provider_reference = models.CharField(max_length=120, blank=True)
    checkout_url = models.URLField(max_length=500, blank=True)
    expires_at = models.DateTimeField()
    last_provider_event_at = models.DateTimeField(null=True, blank=True)
    safe_result_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("provider_account", "idempotency_key"),
                name="payment_intent_idempotency_unique",
            ),
            models.UniqueConstraint(
                fields=("provider_account", "provider_reference"),
                condition=~Q(provider_reference=""),
                name="payment_intent_provider_reference_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "created_at"),
                name="payment_intent_queue_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
            or self.provider_account.organization_id != self.organization_id
        ):
            raise ValidationError(
                "The payment intent does not match its registration scope.",
                code="payment_intent_scope_mismatch",
            )


class PaymentWebhookReceipt(UUIDTimeStampedModel):
    """Authenticated provider event receipt without retaining raw payload data."""

    class Outcome(models.TextChoices):
        APPLIED = "applied", "Applied"
        DUPLICATE = "duplicate", "Duplicate"
        REJECTED = "rejected", "Rejected"
        EXCEPTION = "exception", "Needs review"

    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )
    organization_id = models.UUIDField()
    remote_event_id = models.CharField(max_length=160)
    payload_digest = models.CharField(max_length=64)
    signature_timestamp = models.DateTimeField()
    received_at = models.DateTimeField()
    outcome = models.CharField(max_length=16, choices=Outcome)
    safe_result_code = models.CharField(max_length=80)
    payment_intent = models.ForeignKey(
        PaymentIntent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )

    class Meta:
        ordering = ("-received_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("provider_account", "remote_event_id"),
                name="payment_webhook_remote_event_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "outcome", "received_at"),
                name="payment_webhook_review_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Payment webhook receipts are immutable.",
                code="immutable_payment_webhook_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Payment webhook receipts require the finance retention workflow.",
            code="protected_payment_webhook_receipt",
        )


class PaymentException(UUIDTimeStampedModel):
    """Owned review queue for uncertain, mismatched, or late provider outcomes."""

    class Kind(models.TextChoices):
        PROVIDER_UNAVAILABLE = "provider_unavailable", "Provider unavailable"
        UNKNOWN_INTENT = "unknown_intent", "Unknown payment intent"
        AMOUNT_MISMATCH = "amount_mismatch", "Amount mismatch"
        CURRENCY_MISMATCH = "currency_mismatch", "Currency mismatch"
        LATE_SUCCESS = "late_success", "Late success"
        OUT_OF_ORDER = "out_of_order", "Out-of-order provider event"
        DISPUTE_REVIEW = "dispute_review", "Dispute or chargeback review"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    organization_id = models.UUIDField()
    edition_id = models.UUIDField(null=True, blank=True)
    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="payment_exceptions",
    )
    payment_intent = models.ForeignKey(
        PaymentIntent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exceptions",
    )
    kind = models.CharField(max_length=32, choices=Kind)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    safe_summary = models.CharField(max_length=320)
    opened_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_id = models.UUIDField(null=True, blank=True)
    resolution_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-opened_at", "-id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "opened_at"),
                name="payment_exception_queue_idx",
            )
        ]

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Payment exceptions require reasoned resolution.",
            code="protected_payment_exception",
        )


class PaymentAttempt(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    provider = models.CharField(max_length=40)
    provider_reference = models.CharField(max_length=120)
    idempotency_key = models.UUIDField()
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status)
    occurred_at = models.DateTimeField()
    safe_result_code = models.CharField(max_length=80)

    class Meta:
        ordering = ("occurred_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "idempotency_key"),
                name="registration_payment_idempotency_unique",
            ),
            models.UniqueConstraint(
                fields=("provider", "provider_reference"),
                name="registration_payment_provider_reference_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Payment attempts are append-only.",
                code="immutable_payment_attempt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Payment history is append-only.",
            code="protected_payment_attempt",
        )


class FinancialOperation(UUIDTimeStampedModel):
    """Dual-controlled registration financial or ownership change request."""

    class Kind(models.TextChoices):
        CANCEL = "cancel", "Cancel registration"
        REFUND = "refund", "Refund"
        TRANSFER = "transfer", "Transfer admission"
        PRODUCT_CHANGE = "product_change", "Change admission product"
        PRICE_ADJUSTMENT = "price_adjustment", "Price adjustment"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        PROVIDER_PENDING = "provider_pending", "Provider pending"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="financial_operations",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    kind = models.CharField(max_length=24, choices=Kind)
    status = models.CharField(
        max_length=24,
        choices=Status,
        default=Status.PROPOSED,
    )
    amount_minor = models.PositiveBigIntegerField(default=0)
    currency = models.CharField(max_length=3)
    target_account_id = models.UUIDField(null=True, blank=True)
    target_product_id = models.UUIDField(null=True, blank=True)
    requested_by = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="requested_financial_operations",
    )
    requested_at = models.DateTimeField()
    request_reason = models.CharField(max_length=500)
    approved_by = models.ForeignKey(
        "identity.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_financial_operations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_reason = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_result_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-requested_at", "-id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "requested_at"),
                name="reg_finance_operation_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
            or self.registration.currency_snapshot != self.currency
        ):
            raise ValidationError(
                "The financial operation does not match registration scope.",
                code="financial_operation_scope_mismatch",
            )
        if self.approved_by_id and self.approved_by_id == self.requested_by_id:
            raise ValidationError(
                "The proposer cannot approve the same financial operation.",
                code="financial_operation_dual_control",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Financial operations require a reasoned terminal state.",
            code="protected_financial_operation",
        )


class FinancialLedgerEntry(UUIDTimeStampedModel):
    """Append-only operational ledger; not a statutory general ledger."""

    class Kind(models.TextChoices):
        PAYMENT = "payment", "Provider payment"
        REFUND = "refund", "Refund"
        PROVIDER_FEE = "provider_fee", "Provider fee"
        DISPUTE = "dispute", "Dispute"
        CHARGEBACK = "chargeback", "Chargeback"
        PRICE_ADJUSTMENT = "price_adjustment", "Price adjustment"
        DONATION = "donation", "Donation"
        SETTLEMENT = "settlement", "Settlement"

    class Direction(models.TextChoices):
        INFLOW = "inflow", "Inflow"
        OUTFLOW = "outflow", "Outflow"
        NONCASH = "noncash", "Non-cash"

    registration = models.ForeignKey(
        Registration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="financial_ledger",
    )
    operation = models.ForeignKey(
        FinancialOperation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    kind = models.CharField(max_length=24, choices=Kind)
    direction = models.CharField(max_length=16, choices=Direction)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    occurred_at = models.DateTimeField()
    provider_reference = models.CharField(max_length=160, blank=True)
    settlement_reference = models.CharField(max_length=160, blank=True)
    safe_description = models.CharField(max_length=320)

    class Meta:
        verbose_name_plural = "financial ledger entries"
        ordering = ("occurred_at", "id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "currency", "occurred_at"),
                name="reg_finance_ledger_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("provider_account", "provider_reference", "kind"),
                condition=~Q(provider_reference=""),
                name="finance_provider_movement_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Financial ledger entries are append-only.",
                code="immutable_financial_ledger",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.registration_id:
            registration = self.registration
            if registration is None or (
                registration.organization_id != self.organization_id
                or registration.edition_id != self.edition_id
            ):
                raise ValidationError(
                    "The ledger registration scope does not match.",
                    code="financial_ledger_registration_scope_mismatch",
                )
        if self.operation_id:
            operation = self.operation
            if operation is None or (
                operation.organization_id != self.organization_id
                or operation.edition_id != self.edition_id
                or operation.registration_id != self.registration_id
            ):
                raise ValidationError(
                    "The ledger operation scope does not match.",
                    code="financial_ledger_operation_scope_mismatch",
                )
        if self.provider_account_id:
            provider = self.provider_account
            if provider is None or provider.organization_id != self.organization_id:
                raise ValidationError(
                    "The ledger provider scope does not match.",
                    code="financial_ledger_provider_scope_mismatch",
                )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Financial ledger entries require the finance retention workflow.",
            code="protected_financial_ledger",
        )


class SettlementBatch(UUIDTimeStampedModel):
    """Provider settlement summary reconciled to operational ledger entries."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RECONCILED = "reconciled", "Reconciled"
        EXCEPTION = "exception", "Exception"

    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="settlement_batches",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    provider_reference = models.CharField(max_length=160)
    currency = models.CharField(max_length=3)
    gross_minor = models.PositiveBigIntegerField()
    fee_minor = models.PositiveBigIntegerField()
    refund_minor = models.PositiveBigIntegerField()
    dispute_minor = models.PositiveBigIntegerField()
    net_minor = models.BigIntegerField()
    settled_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by_id = models.UUIDField(null=True, blank=True)
    safe_result_code = models.CharField(max_length=80)

    class Meta:
        verbose_name_plural = "settlement batches"
        ordering = ("-settled_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("provider_account", "provider_reference"),
                name="settlement_provider_reference_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.provider_account_id
            and self.provider_account.organization_id != self.organization_id
        ):
            raise ValidationError(
                "The settlement provider scope does not match.",
                code="settlement_provider_scope_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Reconciled settlement batches are immutable.",
                code="immutable_settlement_batch",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Settlement batches require finance retention.",
            code="protected_settlement_batch",
        )


class SettlementAllocation(UUIDTimeStampedModel):
    """Append-only link proving which provider movements a settlement covers."""

    settlement = models.ForeignKey(
        SettlementBatch,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    ledger_entry = models.OneToOneField(
        FinancialLedgerEntry,
        on_delete=models.PROTECT,
        related_name="settlement_allocation",
    )
    amount_minor = models.PositiveBigIntegerField()

    class Meta:
        ordering = ("settlement_id", "ledger_entry_id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Settlement allocations are append-only.",
                code="immutable_settlement_allocation",
            )
        if (
            self.settlement_id
            and self.ledger_entry_id
            and (
                self.settlement.organization_id != self.ledger_entry.organization_id
                or self.settlement.edition_id != self.ledger_entry.edition_id
                or self.settlement.currency != self.ledger_entry.currency
                or self.settlement.provider_account_id
                != self.ledger_entry.provider_account_id
            )
        ):
            raise ValidationError(
                "Settlement allocation scope does not match.",
                code="settlement_allocation_scope_mismatch",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Settlement allocations are append-only.",
            code="protected_settlement_allocation",
        )


class ReceiptRecord(UUIDTimeStampedModel):
    """Immutable receipt/credit-note snapshot for attendee self-service."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        CREDIT_NOTE = "credit_note", "Credit note"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="receipt_records",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    ledger_entry = models.OneToOneField(
        FinancialLedgerEntry,
        on_delete=models.PROTECT,
        related_name="receipt_record",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    document_number = models.CharField(max_length=80)
    issued_at = models.DateTimeField()
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    description_snapshot = models.CharField(max_length=320)

    class Meta:
        ordering = ("issued_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "document_number"),
                name="receipt_number_unique_per_org",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Receipt records are immutable.",
                code="immutable_receipt_record",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The receipt registration scope does not match.",
                code="receipt_registration_scope_mismatch",
            )
        if self.ledger_entry_id and (
            self.ledger_entry.registration_id != self.registration_id
            or self.ledger_entry.organization_id != self.organization_id
            or self.ledger_entry.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The receipt ledger scope does not match.",
                code="receipt_ledger_scope_mismatch",
            )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Receipts require the finance retention workflow.",
            code="protected_receipt_record",
        )


class RegistrationAdjustment(UUIDTimeStampedModel):
    """Append-only evidence for controlled registration exceptions and automation."""

    class Kind(models.TextChoices):
        PAYMENT_DEADLINE_CHANGED = (
            "payment_deadline_changed",
            "Payment deadline changed",
        )
        PAYMENT_WAIVED = "payment_waived", "Payment waived"
        WAITLIST_PROMOTED = "waitlist_promoted", "Waitlist place offered"
        PAYMENT_EXPIRED = "payment_expired", "Payment reservation expired"
        REGISTRATION_CANCELLED = "registration_cancelled", "Registration cancelled"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    kind = models.CharField(max_length=40, choices=Kind)
    from_state = models.CharField(max_length=24, blank=True)
    to_state = models.CharField(max_length=24, blank=True)
    previous_deadline = models.DateTimeField(null=True, blank=True)
    new_deadline = models.DateTimeField(null=True, blank=True)
    amount_minor = models.PositiveBigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    actor_kind = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("occurred_at", "id")
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "kind", "occurred_at"),
                name="registration_adjustment_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration adjustments are append-only.",
                code="immutable_registration_adjustment",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration adjustments are append-only.",
            code="protected_registration_adjustment",
        )


class Entitlement(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="entitlements",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    code = models.SlugField(max_length=80)
    label_snapshot = models.CharField(max_length=160)
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.ACTIVE,
    )
    granted_at = models.DateTimeField()

    class Meta:
        ordering = ("granted_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("registration", "code"),
                name="registration_entitlement_code_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.registration.reference}: {self.label_snapshot}"


class CheckInRecord(UUIDTimeStampedModel):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.PROTECT,
        related_name="check_in",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    actor_id = models.UUIDField()
    checked_in_at = models.DateTimeField()
    method = models.CharField(max_length=40, default="staff_console")
    reason = models.TextField()

    class Meta:
        verbose_name = "check-in record"
        verbose_name_plural = "check-in records"
        ordering = ("checked_in_at", "id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Check-in records are append-only.",
                code="immutable_check_in",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Check-in records require reconciliation.",
            code="protected_check_in",
        )


class RegistrationTimelineEntry(UUIDTimeStampedModel):
    class Audience(models.TextChoices):
        ATTENDEE_AND_STAFF = "attendee_and_staff", "Attendee and staff"
        STAFF_ONLY = "staff_only", "Registration staff only"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="timeline",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=60)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=320)
    audience = models.CharField(max_length=24, choices=Audience)
    occurred_at = models.DateTimeField()
    actor_kind = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField()

    class Meta:
        verbose_name_plural = "registration timeline entries"
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("registration", "sequence"),
                name="registration_timeline_sequence_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Operational timeline entries are append-only.",
                code="immutable_operational_timeline",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Operational timeline entries are append-only.",
            code="protected_operational_timeline",
        )

    def __str__(self) -> str:
        return f"{self.registration.reference}: {self.title}"


class RegistrationLifecycleRun(UUIDTimeStampedModel):
    """Append-only scheduler heartbeat and outcome evidence."""

    edition_id = models.UUIDField(null=True, blank=True)
    ran_at = models.DateTimeField()
    expired = models.PositiveIntegerField(default=0)
    inactive_cancelled = models.PositiveIntegerField(default=0)
    closed_waitlist_cancelled = models.PositiveIntegerField(default=0)
    promoted = models.PositiveIntegerField(default=0)
    restrictions_applied = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-ran_at", "-id")
        indexes = [
            models.Index(
                fields=("edition_id", "ran_at"),
                name="registration_lifecycle_run_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Lifecycle run evidence is append-only.",
                code="immutable_lifecycle_run",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Lifecycle run evidence follows its retention policy.",
            code="protected_lifecycle_run",
        )


FINANCIAL_OPERATION_KIND_CHOICES = FinancialOperation.Kind.choices
FINANCIAL_OPERATION_STATUS_CHOICES = FinancialOperation.Status.choices
PAYMENT_EXCEPTION_KIND_CHOICES = PaymentException.Kind.choices
PAYMENT_EXCEPTION_STATUS_CHOICES = PaymentException.Status.choices
