"""Registration configuration, commerce, and operational history."""
# ruff: noqa: DJ012

from typing import Any, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Lower

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_currency_codes, validate_lowercase_slug
from maru.identity.policies import validate_convention_subject
from maru.participation.models import validate_capacity_code
from maru.registration.profile_choices import (
    MAX_BIO_LENGTH,
    OTHER_PRONOUN_CODE,
    PRONOUN_CODES,
    pronoun_display,
    validate_spoken_language_codes,
)

MAX_QUESTION_OPTION_LENGTH = 120
MAX_QUESTION_OPTIONS = 64
MAX_PRODUCT_CAPACITY_CODES = 32
MAX_CAPACITY_CODE_LENGTH = 80
MAX_REGISTRATION_CAPACITY = 1_000_000
MAX_PRODUCT_PRICE_MINOR = 1_000_000_000_000
MINIMUM_CHOICE_OPTIONS = 2
MINIMUM_PAYMENT_WINDOW_MINUTES = 15
MAXIMUM_PAYMENT_WINDOW_MINUTES = 60 * 24 * 30
COUNTRY_CODE_LENGTH = 2

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 digest.",
    code="invalid_registration_setup_digest",
)

_PROFILE_VALUE_SOURCE_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_-]{0,31}$",
    message="Use one registered source channel.",
    code="invalid_profile_extension_value_source",
)


class RegistrationSetupOrigin(models.TextChoices):
    LEGACY_EXISTING = "legacy_existing", "Legacy existing"
    BLANK = "blank", "Blank"
    PLATFORM_STARTER = "platform_starter", "Platform starter"
    PUBLISHED_TEMPLATE = "published_template", "Published template"
    PRIOR_EDITION = "prior_edition", "Prior edition"
    SUCCESSOR = "successor", "Successor"


class RegistrationProvenanceStatus(models.TextChoices):
    COMPLETE = "complete", "Complete"
    LEGACY_UNKNOWN = "legacy_unknown", "Legacy unknown"


class RegistrationCommandChangeKind(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    MOVED = "moved", "Moved"
    REVIEWED = "reviewed", "Reviewed"
    ACTIVATED = "activated", "Activated"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"
    DELETED = "deleted", "Deleted"


class CatalogVersionStampedModel(models.Model):
    """Nullable command-version evidence during the additive writer cutover."""

    created_in_catalog_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_catalog_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        abstract = True


class SetupVersionStampedModel(models.Model):
    """Nullable command-version evidence during the additive writer cutover."""

    created_in_setup_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_setup_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        abstract = True


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
    if len(normalized) > MAX_QUESTION_OPTIONS:
        raise ValidationError(
            {"options": f"Choose no more than {MAX_QUESTION_OPTIONS} options."},
            code="question_option_limit_exceeded",
        )
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
    provenance_status = models.CharField(
        max_length=24,
        choices=RegistrationProvenanceStatus,
        default=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        editable=False,
    )
    content_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
        editable=False,
    )
    created_in_catalog_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_catalog_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

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
            models.CheckConstraint(
                condition=(
                    Q(created_in_catalog_version__isnull=True)
                    | Q(created_in_catalog_version__gt=0)
                )
                & (
                    Q(last_changed_in_catalog_version__isnull=True)
                    | Q(last_changed_in_catalog_version__gt=0)
                )
                & (
                    Q(created_in_catalog_version__isnull=True)
                    | Q(
                        last_changed_in_catalog_version__gte=models.F(
                            "created_in_catalog_version"
                        )
                    )
                ),
                name="reg_template_catalog_versions_valid",
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
        if self.provenance_status == RegistrationProvenanceStatus.COMPLETE and (
            not self.content_digest
            or self.created_in_catalog_version is None
            or self.last_changed_in_catalog_version is None
        ):
            raise ValidationError(
                "Complete template provenance requires digest and version stamps.",
                code="registration_template_complete_provenance_incomplete",
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


class RegistrationTemplateSection(UUIDTimeStampedModel, CatalogVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.template.name}: {self.title}"

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


class RegistrationTemplateQuestion(AbstractQuestion, CatalogVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.template.name}: {self.label}"

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


class AbstractProduct(UUIDTimeStampedModel):
    code = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    price_minor = models.PositiveBigIntegerField(default=0)
    capacity = models.PositiveIntegerField()
    capacity_ceiling = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Optional hard ceiling for governed live capacity adjustments. "
            "When omitted, the configured capacity is the ceiling."
        ),
    )
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
        if not 1 <= self.capacity <= MAX_REGISTRATION_CAPACITY:
            raise ValidationError(
                {
                    "capacity": (
                        "Product capacity must be between 1 and "
                        f"{MAX_REGISTRATION_CAPACITY}."
                    )
                },
                code="product_capacity_out_of_range",
            )
        if self.capacity_ceiling is not None and not (
            self.capacity <= self.capacity_ceiling <= MAX_REGISTRATION_CAPACITY
        ):
            raise ValidationError(
                {
                    "capacity_ceiling": (
                        "The product capacity ceiling must be at least its initial "
                        "capacity and no more than "
                        f"{MAX_REGISTRATION_CAPACITY}."
                    )
                },
                code="product_capacity_ceiling_out_of_range",
            )
        if self.price_minor > MAX_PRODUCT_PRICE_MINOR:
            raise ValidationError(
                {
                    "price_minor": (
                        "Price must not exceed "
                        f"{MAX_PRODUCT_PRICE_MINOR} minor currency units."
                    )
                },
                code="product_price_out_of_range",
            )
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
        if len(codes) > MAX_PRODUCT_CAPACITY_CODES:
            raise ValidationError(
                {
                    "required_capacity_codes": (
                        "Choose no more than "
                        f"{MAX_PRODUCT_CAPACITY_CODES} capacity codes."
                    )
                },
                code="product_capacity_code_limit_exceeded",
            )
        for code in codes:
            if len(code) > MAX_CAPACITY_CODE_LENGTH:
                raise ValidationError(
                    {
                        "required_capacity_codes": (
                            "Capacity codes must use no more than 80 characters."
                        )
                    },
                    code="product_capacity_code_too_long",
                )
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


class RegistrationTemplateProduct(AbstractProduct, CatalogVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.template.name}: {self.name}"

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


class RegistrationTemplateCatalogControl(UUIDTimeStampedModel):
    """Optimistic-concurrency control for one organization's template catalog."""

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_template_catalog_control",
    )
    aggregate_version = models.PositiveBigIntegerField()
    provenance_status = models.CharField(
        max_length=24,
        choices=RegistrationProvenanceStatus,
        default=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        editable=False,
    )

    class Meta:
        ordering = ("organization_id",)
        constraints = [
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="reg_template_catalog_version_positive",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Registration template catalog v{self.aggregate_version}"


class RegistrationTemplateCatalogCommandReceipt(UUIDTimeStampedModel):
    """Immutable, minimized evidence for one successful template command."""

    class Action(models.TextChoices):
        TEMPLATE_CREATED = "template_created", "Template created"
        TEMPLATE_UPDATED = "template_updated", "Template updated"
        TEMPLATE_PUBLISHED = "template_published", "Template published"
        TEMPLATE_RETIRED = "template_retired", "Template retired"
        SECTION_CREATED = "section_created", "Section created"
        SECTION_UPDATED = "section_updated", "Section updated"
        SECTION_MOVED = "section_moved", "Section moved"
        SECTION_DELETED = "section_deleted", "Section deleted"
        QUESTION_CREATED = "question_created", "Question created"
        QUESTION_UPDATED = "question_updated", "Question updated"
        QUESTION_MOVED = "question_moved", "Question moved"
        QUESTION_DELETED = "question_deleted", "Question deleted"
        PRODUCT_CREATED = "product_created", "Product created"
        PRODUCT_UPDATED = "product_updated", "Product updated"
        PRODUCT_MOVED = "product_moved", "Product moved"
        PRODUCT_DELETED = "product_deleted", "Product deleted"

    catalog = models.ForeignKey(
        RegistrationTemplateCatalogControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_template_catalog_command_receipts",
    )
    action = models.CharField(max_length=32, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_template_catalog_commands_acted",
    )
    reason = models.CharField(max_length=500)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    retry_key = models.UUIDField(null=True, blank=True)
    request_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )

    class Meta:
        ordering = ("organization_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("catalog", "resulting_version"),
                name="reg_template_receipt_version_unique",
            ),
            models.UniqueConstraint(
                fields=("organization", "actor", "retry_key"),
                condition=Q(retry_key__isnull=False),
                name="reg_template_retry_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="reg_template_receipt_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(reason="") & ~Q(source_channel=""),
                name="reg_template_receipt_evidence_nonblank",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "action", "created_at"),
                name="reg_tpl_rcpt_action_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.catalog_id and self.catalog.organization_id != self.organization_id:
            raise ValidationError(
                "Template command receipt must match its organization scope.",
                code="registration_template_receipt_scope_mismatch",
            )
        if bool(self.retry_key) != bool(self.request_digest):
            raise ValidationError(
                "Retry key and request digest evidence must be recorded together.",
                code="registration_template_retry_evidence_incomplete",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration template command receipts are immutable.",
                code="immutable_registration_template_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration template command receipts require retention workflow.",
            code="protected_registration_template_command_receipt",
        )


class RegistrationTemplateCatalogCommandTarget(UUIDTimeStampedModel):
    """Stable, label-free target evidence attached to a template receipt."""

    class TargetKind(models.TextChoices):
        TEMPLATE = "template", "Template"
        SECTION = "section", "Section"
        QUESTION = "question", "Question"
        PRODUCT = "product", "Product"

    receipt = models.ForeignKey(
        RegistrationTemplateCatalogCommandReceipt,
        on_delete=models.PROTECT,
        related_name="targets",
    )
    target_kind = models.CharField(max_length=24, choices=TargetKind)
    target_id = models.UUIDField()
    change_kind = models.CharField(
        max_length=16,
        choices=RegistrationCommandChangeKind,
    )
    target_schema_version = models.PositiveIntegerField(null=True, blank=True)
    content_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )

    class Meta:
        ordering = ("receipt_id", "target_kind", "target_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("receipt", "target_kind", "target_id"),
                name="reg_template_receipt_target_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(target_schema_version__isnull=True)
                    | Q(target_schema_version__gt=0)
                ),
                name="reg_template_target_schema_ver_positive",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration template command targets are immutable.",
                code="immutable_registration_template_command_target",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration template command targets require retention workflow.",
            code="protected_registration_template_command_target",
        )


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
    source_configuration = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="successor_configurations",
        null=True,
        blank=True,
        editable=False,
    )
    origin = models.CharField(
        max_length=24,
        choices=RegistrationSetupOrigin,
        default=RegistrationSetupOrigin.LEGACY_EXISTING,
        editable=False,
    )
    provenance_status = models.CharField(
        max_length=24,
        choices=RegistrationProvenanceStatus,
        default=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        editable=False,
    )
    source_version = models.PositiveIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    source_content_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
        editable=False,
    )
    content_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
        editable=False,
    )
    source_imported_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    source_imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_configuration_imports",
        null=True,
        blank=True,
        editable=False,
    )
    created_in_setup_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    last_changed_in_setup_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    review_required = models.BooleanField(default=True)
    review_note = models.TextField(blank=True)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    capacity_ceiling = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Optional hard ceiling for reasoned live capacity adjustments. "
            "When omitted, the initial capacity is the ceiling."
        ),
    )
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
            models.CheckConstraint(
                condition=(
                    Q(created_in_setup_version__isnull=True)
                    | Q(created_in_setup_version__gt=0)
                )
                & (
                    Q(last_changed_in_setup_version__isnull=True)
                    | Q(last_changed_in_setup_version__gt=0)
                )
                & (
                    Q(created_in_setup_version__isnull=True)
                    | Q(
                        last_changed_in_setup_version__gte=models.F(
                            "created_in_setup_version"
                        )
                    )
                ),
                name="reg_configuration_setup_versions_valid",
            ),
            models.CheckConstraint(
                condition=(Q(source_version__isnull=True) | Q(source_version__gt=0)),
                name="reg_configuration_source_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(provenance_status=RegistrationProvenanceStatus.COMPLETE)
                    | (
                        Q(content_digest__regex=r"^[0-9a-f]{64}$")
                        & Q(created_in_setup_version__isnull=False)
                        & Q(last_changed_in_setup_version__isnull=False)
                        & (
                            Q(
                                origin=RegistrationSetupOrigin.BLANK,
                                source_template__isnull=True,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=True,
                                source_content_digest="",
                                source_imported_at__isnull=True,
                                source_imported_by__isnull=True,
                            )
                            | Q(
                                origin=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
                                source_template__isnull=False,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                            | Q(
                                origin=RegistrationSetupOrigin.PLATFORM_STARTER,
                                source_template__isnull=True,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                            | Q(
                                origin__in=(
                                    RegistrationSetupOrigin.PRIOR_EDITION,
                                    RegistrationSetupOrigin.SUCCESSOR,
                                ),
                                source_template__isnull=True,
                                source_edition__isnull=False,
                                source_configuration__isnull=False,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                        )
                    )
                ),
                name="reg_configuration_complete_provenance_shape",
            ),
        ]

    def clean(self) -> None:  # noqa: PLR0912
        super().clean()
        if not 1 <= self.capacity <= MAX_REGISTRATION_CAPACITY:
            raise ValidationError(
                {
                    "capacity": (
                        "Registration capacity must be between 1 and "
                        f"{MAX_REGISTRATION_CAPACITY}."
                    )
                },
                code="registration_capacity_out_of_range",
            )
        if self.capacity_ceiling is not None and not (
            self.capacity <= self.capacity_ceiling <= MAX_REGISTRATION_CAPACITY
        ):
            raise ValidationError(
                {
                    "capacity_ceiling": (
                        "The registration capacity ceiling must be at least the "
                        "initial capacity and no more than "
                        f"{MAX_REGISTRATION_CAPACITY}."
                    )
                },
                code="registration_capacity_ceiling_out_of_range",
            )
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
        if self.source_configuration_id:
            source_configuration = self.source_configuration
            if (
                source_configuration is None
                or source_configuration.id == self.id
                or source_configuration.organization_id != self.organization_id
                or (
                    self.source_edition_id is not None
                    and source_configuration.edition_id != self.source_edition_id
                )
            ):
                raise ValidationError(
                    {"source_configuration": "Choose an exact compatible source."},
                    code="registration_source_configuration_mismatch",
                )
        if bool(self.source_imported_at) != bool(self.source_imported_by_id):
            raise ValidationError(
                "Import time and actor evidence must be recorded together.",
                code="registration_import_evidence_incomplete",
            )
        if (self.source_version is not None or self.source_content_digest) and not (
            self.source_template_id
            or self.source_configuration_id
            or self.origin == RegistrationSetupOrigin.PLATFORM_STARTER
        ):
            raise ValidationError(
                "Source version and digest require an exact source record.",
                code="registration_source_evidence_without_source",
            )
        if self.provenance_status == RegistrationProvenanceStatus.COMPLETE:
            if (
                not self.content_digest
                or self.created_in_setup_version is None
                or self.last_changed_in_setup_version is None
            ):
                raise ValidationError(
                    "Complete provenance requires digest and command-version stamps.",
                    code="registration_complete_provenance_incomplete",
                )
            complete_source_evidence = (
                self.source_version is not None
                and bool(self.source_content_digest)
                and self.source_imported_at is not None
                and self.source_imported_by_id is not None
            )
            if self.origin == RegistrationSetupOrigin.BLANK:
                if self.source_template_id or self.source_configuration_id:
                    raise ValidationError(
                        "Blank setup cannot identify an imported source.",
                        code="registration_blank_source_conflict",
                    )
            elif self.origin == RegistrationSetupOrigin.PUBLISHED_TEMPLATE:
                if not self.source_template_id or not complete_source_evidence:
                    raise ValidationError(
                        "Published-template setup requires complete source evidence.",
                        code="registration_template_provenance_incomplete",
                    )
            elif self.origin == RegistrationSetupOrigin.PLATFORM_STARTER:
                if (
                    self.source_template_id
                    or self.source_edition_id
                    or self.source_configuration_id
                    or not complete_source_evidence
                ):
                    raise ValidationError(
                        "Platform-starter setup requires immutable catalog evidence.",
                        code="registration_starter_provenance_incomplete",
                    )
            elif self.origin in {
                RegistrationSetupOrigin.PRIOR_EDITION,
                RegistrationSetupOrigin.SUCCESSOR,
            }:
                if not self.source_configuration_id or not complete_source_evidence:
                    raise ValidationError(
                        "Configuration copy requires complete source evidence.",
                        code="registration_configuration_provenance_incomplete",
                    )
            else:
                raise ValidationError(
                    "Legacy-existing setup cannot claim complete provenance.",
                    code="registration_legacy_provenance_conflict",
                )
        validate_currency_codes([self.currency])

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.currency = self.currency.upper()
        if not self._state.adding:
            immutable_fields = (
                "organization_id",
                "edition_id",
                "version",
                "source_template_id",
                "source_edition_id",
                "source_configuration_id",
                "origin",
                "provenance_status",
                "source_version",
                "source_content_digest",
                "source_imported_at",
                "source_imported_by_id",
                "created_in_setup_version",
                "created_by_id",
            )
            current = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("status", *immutable_fields)
                .first()
            )
            if current is not None and any(
                getattr(self, field) != current[field] for field in immutable_fields
            ):
                raise ValidationError(
                    "Registration configuration source provenance is immutable.",
                    code="immutable_registration_configuration_provenance",
                )
            current_status = current["status"] if current is not None else None
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


class RegistrationSetupControl(UUIDTimeStampedModel):
    """Optimistic-concurrency aggregate for one edition's registration setup."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_setup_controls",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="registration_setup_control",
    )
    origin = models.CharField(max_length=24, choices=RegistrationSetupOrigin)
    provenance_status = models.CharField(
        max_length=24,
        choices=RegistrationProvenanceStatus,
        default=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        editable=False,
    )
    aggregate_version = models.PositiveBigIntegerField()

    class Meta:
        ordering = ("organization_id", "edition_id")
        constraints = [
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="registration_setup_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(provenance_status=RegistrationProvenanceStatus.COMPLETE)
                    | ~Q(origin=RegistrationSetupOrigin.LEGACY_EXISTING)
                ),
                name="reg_setup_complete_origin_nonlegacy",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition"),
                name="registration_setup_scope_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "Registration setup control must match its edition scope.",
                code="registration_setup_control_scope_mismatch",
            )
        if (
            self.provenance_status == RegistrationProvenanceStatus.COMPLETE
            and self.origin == RegistrationSetupOrigin.LEGACY_EXISTING
        ):
            raise ValidationError(
                "Legacy-existing setup cannot claim complete provenance.",
                code="registration_setup_legacy_provenance_conflict",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            immutable_fields = (
                "organization_id",
                "edition_id",
                "origin",
                "provenance_status",
            )
            current = (
                type(self).objects.filter(pk=self.pk).values(*immutable_fields).first()
            )
            if current is not None and any(
                getattr(self, field) != current[field] for field in immutable_fields
            ):
                raise ValidationError(
                    "Registration setup source provenance is immutable.",
                    code="immutable_registration_setup_provenance",
                )
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Registration setup v{self.aggregate_version} - {self.edition}"


class RegistrationSetupCommandReceipt(UUIDTimeStampedModel):
    """Immutable, minimized evidence for one successful setup command."""

    class Action(models.TextChoices):
        SETUP_STARTED = "setup_started", "Setup started"
        SUCCESSOR_STARTED = "successor_started", "Successor started"
        CONFIGURATION_REVIEWED = "configuration_reviewed", "Configuration reviewed"
        CONFIGURATION_ACTIVATED = (
            "configuration_activated",
            "Configuration activated",
        )
        CONFIGURATION_RETIRED = "configuration_retired", "Configuration retired"
        SECTION_CREATED = "section_created", "Section created"
        SECTION_UPDATED = "section_updated", "Section updated"
        SECTION_MOVED = "section_moved", "Section moved"
        SECTION_DELETED = "section_deleted", "Section deleted"
        QUESTION_CREATED = "question_created", "Question created"
        QUESTION_UPDATED = "question_updated", "Question updated"
        QUESTION_MOVED = "question_moved", "Question moved"
        QUESTION_DELETED = "question_deleted", "Question deleted"
        PRODUCT_CREATED = "product_created", "Product created"
        PRODUCT_UPDATED = "product_updated", "Product updated"
        PRODUCT_MOVED = "product_moved", "Product moved"
        PRODUCT_DELETED = "product_deleted", "Product deleted"
        MINOR_POLICY_CREATED = "minor_policy_created", "Minor policy created"
        MINOR_POLICY_UPDATED = "minor_policy_updated", "Minor policy updated"
        MINOR_POLICY_REMOVED = "minor_policy_removed", "Minor policy removed"
        PROFILE_FIELD_CREATED = "profile_field_created", "Profile field created"
        PROFILE_FIELD_UPDATED = "profile_field_updated", "Profile field updated"
        PROFILE_FIELD_MOVED = "profile_field_moved", "Profile field moved"
        PROFILE_FIELD_REVIEWED = "profile_field_reviewed", "Profile field reviewed"
        PROFILE_FIELD_ACTIVATED = (
            "profile_field_activated",
            "Profile field activated",
        )
        PROFILE_FIELD_SUCCESSOR_STARTED = (
            "profile_field_successor_started",
            "Profile field successor started",
        )
        PROFILE_FIELD_RETIRED = "profile_field_retired", "Profile field retired"

    setup = models.ForeignKey(
        RegistrationSetupControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_setup_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="registration_setup_command_receipts",
    )
    action = models.CharField(max_length=32, choices=Action)
    resulting_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_setup_commands_acted",
    )
    reason = models.CharField(max_length=500)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    retry_key = models.UUIDField(null=True, blank=True)
    request_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )

    class Meta:
        ordering = ("edition_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("setup", "resulting_version"),
                name="registration_setup_receipt_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                condition=Q(retry_key__isnull=False),
                name="registration_setup_retry_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="registration_setup_receipt_ver_positive",
            ),
            models.CheckConstraint(
                condition=~Q(reason="") & ~Q(source_channel=""),
                name="registration_setup_receipt_evidence_nonblank",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "resulting_version"),
                name="reg_setup_rcpt_scope_idx",
            ),
            models.Index(
                fields=("edition", "action", "created_at"),
                name="reg_setup_receipt_action_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.setup_id and (
            self.setup.organization_id != self.organization_id
            or self.setup.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Registration setup receipt must match its exact edition scope.",
                code="registration_setup_receipt_scope_mismatch",
            )
        if bool(self.retry_key) != bool(self.request_digest):
            raise ValidationError(
                "Retry key and request digest evidence must be recorded together.",
                code="registration_setup_retry_evidence_incomplete",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration setup command receipts are immutable.",
                code="immutable_registration_setup_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration setup command receipts require retention workflow.",
            code="protected_registration_setup_command_receipt",
        )


class RegistrationSetupCommandTarget(UUIDTimeStampedModel):
    """Stable, label-free target evidence attached to a setup receipt."""

    class TargetKind(models.TextChoices):
        CONFIGURATION = "configuration", "Configuration"
        SECTION = "section", "Section"
        QUESTION = "question", "Question"
        PRODUCT = "product", "Product"
        MINOR_POLICY = "minor_policy", "Minor policy"
        PROFILE_FIELD = "profile_field", "Profile field"

    receipt = models.ForeignKey(
        RegistrationSetupCommandReceipt,
        on_delete=models.PROTECT,
        related_name="targets",
    )
    target_kind = models.CharField(max_length=24, choices=TargetKind)
    target_id = models.UUIDField()
    change_kind = models.CharField(
        max_length=16,
        choices=RegistrationCommandChangeKind,
    )
    target_schema_version = models.PositiveIntegerField(null=True, blank=True)
    content_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(_SHA256_VALIDATOR,),
    )

    class Meta:
        ordering = ("receipt_id", "target_kind", "target_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("receipt", "target_kind", "target_id"),
                name="registration_setup_receipt_target_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(target_schema_version__isnull=True)
                    | Q(target_schema_version__gt=0)
                ),
                name="reg_setup_target_schema_ver_positive",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration setup command targets are immutable.",
                code="immutable_registration_setup_command_target",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration setup command targets require retention workflow.",
            code="protected_registration_setup_command_target",
        )


class RegistrationSection(UUIDTimeStampedModel, SetupVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.title}"

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


class RegistrationQuestion(AbstractQuestion, SetupVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.label}"

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


class AdmissionProduct(AbstractProduct, SetupVersionStampedModel):
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

    def __str__(self) -> str:
        return f"{self.configuration.edition.name}: {self.name}"

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
        if self.account_id:
            validate_convention_subject(self.account)
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


class MinorRegistrationPolicy(UUIDTimeStampedModel, SetupVersionStampedModel):
    """Jurisdiction-reviewed guardian policy attached to one form version."""

    configuration = models.OneToOneField(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="minor_policy",
    )
    enabled = models.BooleanField(default=False)
    minor_age_threshold = models.PositiveSmallIntegerField(default=18)
    guardian_notice_version = models.CharField(max_length=40, blank=True)
    jurisdiction_code = models.CharField(max_length=40, blank=True)
    review_reference = models.CharField(max_length=120, blank=True)
    reviewed_by = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="reviewed_minor_registration_policies",
    )
    reviewed_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = "minor registration policies"

    def __str__(self) -> str:
        return f"Minor policy - {self.configuration}"

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


class ProfileExtensionWriter(models.TextChoices):
    ATTENDEE = "attendee", "Attendee"
    REGISTRATION_STAFF = "registration_staff", "Registration staff"
    ATTENDEE_AND_STAFF = "attendee_and_staff", "Attendee and registration staff"


class ProfileExtensionAudience(models.TextChoices):
    """One explicit reader policy, independent from the writer policy."""

    SELF = "self", "Registration owner"
    REGISTRATION_STAFF = "registration_staff", "Exact registration staff"
    DEPARTMENT = "department", "Exact department or team"
    CONFIRMED_ATTENDEES = "confirmed_attendees", "All confirmed attendees"
    PUBLIC = "public", "Public attendee directory"


class ProfileExtensionReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ProfileExtensionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class ProfileExtensionValueWriterKind(models.TextChoices):
    OWNER = "owner", "Registration owner"
    STAFF = "staff", "Authorized registration staff"


class RegistrationProfileExtensionField(UUIDTimeStampedModel, SetupVersionStampedModel):
    """Versioned current-profile field separate from immutable submissions."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_fields",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_fields",
    )
    key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    label = models.CharField(max_length=200)
    help_text = models.TextField(blank=True)
    field_type = models.CharField(max_length=24, choices=QuestionFieldType)
    options = models.JSONField(default=list, blank=True)
    purpose = models.CharField(max_length=240)
    classification = models.CharField(
        max_length=2,
        choices=QuestionClassification,
        default=QuestionClassification.PERSONAL,
    )
    attendee_visible = models.BooleanField(default=True)
    audience_policy = models.CharField(
        max_length=24,
        choices=ProfileExtensionAudience,
        default=ProfileExtensionAudience.SELF,
    )
    audience_department = models.ForeignKey(
        "workforce.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_audiences",
    )
    writer_policy = models.CharField(
        max_length=30,
        choices=ProfileExtensionWriter,
        default=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    )
    required = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    source_template = models.ForeignKey(
        RegistrationTemplate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="profile_extension_field_copies",
    )
    source_prior_edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="profile_extension_field_copies",
    )
    review_status = models.CharField(
        max_length=16,
        choices=ProfileExtensionReviewStatus,
        default=ProfileExtensionReviewStatus.PENDING,
    )
    status = models.CharField(
        max_length=16,
        choices=ProfileExtensionStatus,
        default=ProfileExtensionStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_fields_created",
    )
    approved_by = models.ForeignKey(
        "identity.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_fields_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "position", "key", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "key", "version"),
                name="registration_profile_extension_field_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "key"),
                condition=Q(status="active"),
                name="registration_one_active_profile_extension_field",
            ),
            models.UniqueConstraint(
                fields=("supersedes",),
                condition=Q(supersedes__isnull=False) & ~Q(status="retired"),
                name="registration_one_open_profile_extension_successor",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        audience_policy=ProfileExtensionAudience.DEPARTMENT,
                        audience_department__isnull=False,
                    )
                    | (
                        ~Q(audience_policy=ProfileExtensionAudience.DEPARTMENT)
                        & Q(audience_department__isnull=True)
                    )
                ),
                name="reg_profile_audience_department_shape",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        audience_policy__in=(
                            ProfileExtensionAudience.SELF,
                            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
                            ProfileExtensionAudience.PUBLIC,
                        ),
                        attendee_visible=True,
                    )
                    | Q(
                        audience_policy__in=(
                            ProfileExtensionAudience.REGISTRATION_STAFF,
                            ProfileExtensionAudience.DEPARTMENT,
                        ),
                        attendee_visible=False,
                    )
                ),
                name="reg_profile_audience_legacy_visibility",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "audience_policy", "position"),
                name="reg_profile_audience_idx",
            )
        ]

    def clean(self) -> None:  # noqa: PLR0912
        super().clean()
        _validate_question_options(field_type=self.field_type, options=self.options)
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The profile field must match its edition scope.")
        if self.audience_policy == ProfileExtensionAudience.DEPARTMENT:
            department = self.audience_department
            if (
                department is None
                or department.organization_id != self.organization_id
                or department.edition_id != self.edition_id
                or department.retired_at is not None
            ):
                raise ValidationError(
                    {
                        "audience_department": (
                            "Choose one active department in this exact edition."
                        )
                    },
                    code="profile_extension_audience_department_mismatch",
                )
        elif self.audience_department_id is not None:
            raise ValidationError(
                {
                    "audience_department": (
                        "Only the department audience accepts a department."
                    )
                },
                code="profile_extension_audience_department_unexpected",
            )
        source_binding_changed = self._state.adding
        if not self._state.adding and self.pk is not None:
            persisted_source = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("source_template_id", "source_prior_edition_id")
                .first()
            )
            if persisted_source is not None and (
                persisted_source["source_template_id"] != self.source_template_id
                or persisted_source["source_prior_edition_id"]
                != self.source_prior_edition_id
            ):
                raise ValidationError(
                    "Profile-extension source provenance is immutable.",
                    code="immutable_profile_extension_source",
                )
        if self.source_template_id and self.source_prior_edition_id:
            raise ValidationError(
                "Choose either template or prior-edition provenance, not both."
            )
        if self.source_template_id:
            source_template = self.source_template
            if (
                source_template is None
                or source_template.organization_id != self.organization_id
                or (
                    source_template.series_id is not None
                    and source_template.series_id != self.edition.series_id
                )
                or (
                    self._state.adding
                    and source_template.status != TemplateStatus.PUBLISHED
                )
                or (
                    not self._state.adding
                    and source_template.status
                    not in {TemplateStatus.PUBLISHED, TemplateStatus.RETIRED}
                )
            ):
                raise ValidationError(
                    {"source_template": "Choose an applicable published template."}
                )
        if self.source_prior_edition_id:
            source_edition = self.source_prior_edition
            if (
                source_edition is None
                or source_edition.organization_id != self.organization_id
                or source_edition.id == self.edition_id
                or (
                    source_binding_changed
                    and source_edition.starts_on >= self.edition.starts_on
                )
            ):
                raise ValidationError(
                    {
                        "source_prior_edition": (
                            "Choose an earlier edition in the same organization."
                        )
                    }
                )
        if self.writer_policy in {
            ProfileExtensionWriter.ATTENDEE,
            ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        } and self.audience_policy not in {
            ProfileExtensionAudience.SELF,
            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
            ProfileExtensionAudience.PUBLIC,
        }:
            raise ValidationError(
                {
                    "audience_policy": (
                        "An attendee-writable profile field must include its owner."
                    )
                }
            )
        approval_is_complete = (
            self.review_status == ProfileExtensionReviewStatus.APPROVED
            and self.approved_by_id is not None
            and self.approved_at is not None
        )
        if self.review_status == ProfileExtensionReviewStatus.APPROVED:
            if not approval_is_complete:
                raise ValidationError(
                    "Approved profile fields require complete approval evidence.",
                    code="profile_extension_approval_evidence_incomplete",
                )
        elif self.approved_by_id is not None or self.approved_at is not None:
            raise ValidationError(
                "Unapproved profile fields cannot carry approval evidence.",
                code="profile_extension_approval_evidence_unexpected",
            )
        if self.status == ProfileExtensionStatus.ACTIVE and not approval_is_complete:
            raise ValidationError(
                "An active profile field requires recorded approval.",
                code="profile_extension_approval_required",
            )
        if self.supersedes_id:
            previous = self.supersedes
            if (
                previous is None
                or previous.edition_id != self.edition_id
                or previous.key != self.key
                or previous.version >= self.version
            ):
                raise ValidationError(
                    {
                        "supersedes": (
                            "A successor must be a later version of the same "
                            "edition key."
                        )
                    }
                )
            if self._state.adding:
                if previous.status != ProfileExtensionStatus.ACTIVE:
                    raise ValidationError(
                        {
                            "supersedes": (
                                "A successor starts from the active definition."
                            )
                        },
                        code="profile_extension_successor_source_not_active",
                    )
                if (
                    type(self)
                    .objects.filter(supersedes_id=self.supersedes_id)
                    .exclude(status=ProfileExtensionStatus.RETIRED)
                    .exists()
                ):
                    raise ValidationError(
                        {
                            "supersedes": (
                                "An active definition can have only one open "
                                "successor. Retire its existing draft first."
                            )
                        },
                        code="profile_extension_open_successor_exists",
                    )
                highest_version = (
                    type(self)
                    .objects.filter(edition_id=self.edition_id, key=self.key)
                    .order_by("-version")
                    .values_list("version", flat=True)
                    .first()
                    or 0
                )
                if self.version != highest_version + 1:
                    raise ValidationError(
                        {
                            "version": (
                                "A successor must use the next version number not "
                                "yet used for this edition key."
                            )
                        },
                        code="profile_extension_successor_version_invalid",
                    )
        reserved_prefixes = (
            "infinity",
            "admission",
            "entitlement",
            "payment",
            "role",
            "capacity",
            "restriction",
        )
        if self.key.startswith(reserved_prefixes):
            raise ValidationError(
                {"key": "Use the authoritative Maru domain record for this fact."},
                code="authoritative_profile_extension_key",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.lower()
        # Preserve the pre-audience model-construction contract while callers
        # migrate to the explicit policy vocabulary. A newly constructed
        # legacy ``attendee_visible=False`` field meant staff-only.
        if (
            self._state.adding
            and self.audience_policy == ProfileExtensionAudience.SELF
            and self.attendee_visible is False
        ):
            self.audience_policy = ProfileExtensionAudience.REGISTRATION_STAFF
        self.attendee_visible = self.audience_policy in {
            ProfileExtensionAudience.SELF,
            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
            ProfileExtensionAudience.PUBLIC,
        }
        if not self._state.adding:
            current = type(self).objects.filter(pk=self.pk).values("status").first()
            if current and current["status"] == ProfileExtensionStatus.RETIRED:
                raise ValidationError(
                    "Retired profile field versions are immutable.",
                    code="immutable_retired_profile_extension_field",
                )
            if current and current["status"] == ProfileExtensionStatus.ACTIVE:
                update_fields = set(kwargs.get("update_fields") or ())
                if self.status != ProfileExtensionStatus.RETIRED or (
                    update_fields
                    and not update_fields
                    <= {
                        "status",
                        "last_changed_in_setup_version",
                        "updated_at",
                    }
                ):
                    raise ValidationError(
                        "Active profile field versions are immutable.",
                        code="immutable_profile_extension_field",
                    )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Profile extension fields use versioning and retirement.",
            code="protected_profile_extension_field",
        )

    def __str__(self) -> str:
        return f"{self.label} v{self.version} — {self.edition.name}"


class RegistrationProfileExtensionValueRevision(UUIDTimeStampedModel):
    """One append-only value revision for a registration profile extension."""

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="profile_extension_value_revisions",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    field = models.ForeignKey(
        RegistrationProfileExtensionField,
        on_delete=models.PROTECT,
        related_name="value_revisions",
    )
    field_key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    sequence = models.PositiveIntegerField()
    value = models.JSONField()
    actor = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_value_revisions",
    )
    source_channel = models.CharField(
        max_length=32,
        validators=(_PROFILE_VALUE_SOURCE_VALIDATOR,),
    )
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("registration_id", "field_key", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("registration", "field_key", "sequence"),
                name="registration_profile_extension_value_revision_unique",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
        ):
            raise ValidationError("The value revision must match its registration.")
        if self.field_id and (
            self.field.organization_id != self.organization_id
            or self.field.edition_id != self.edition_id
            or self.field.key != self.field_key
        ):
            raise ValidationError("The value revision must match its field scope.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Profile extension value revisions are append-only.",
                code="immutable_profile_extension_value_revision",
            )
        self.field_key = self.field_key.lower()
        stores_json_null = (
            isinstance(self.value, Value)
            and self.value.value is None
            and isinstance(self.value.output_field, models.JSONField)
        )
        if stores_json_null:
            self.full_clean(exclude={"value"})
        else:
            self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Profile extension value revisions require the retention workflow.",
            code="protected_profile_extension_value_revision",
        )

    def __str__(self) -> str:
        return f"{self.registration.reference}: {self.field_key} r{self.sequence}"


class RegistrationProfileExtensionValueControl(UUIDTimeStampedModel):
    """Locked current-sequence pointer for one registration and stable field key."""

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="profile_extension_value_controls",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    field_key = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    current_sequence = models.PositiveIntegerField(default=0)
    latest_revision = models.OneToOneField(
        RegistrationProfileExtensionValueRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_control",
    )

    class Meta:
        ordering = ("registration_id", "field_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("registration", "field_key"),
                name="reg_profile_value_control_key_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(current_sequence=0, latest_revision__isnull=True)
                    | Q(current_sequence__gt=0, latest_revision__isnull=False)
                ),
                name="reg_profile_value_control_pointer_complete",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "registration"),
                name="reg_prof_val_ctrl_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The profile-value control must match its registration scope.",
                code="profile_value_control_scope_mismatch",
            )
        latest_revision = (
            self.latest_revision if self.latest_revision_id is not None else None
        )
        if latest_revision is not None and (
            latest_revision.registration_id != self.registration_id
            or latest_revision.organization_id != self.organization_id
            or latest_revision.edition_id != self.edition_id
            or latest_revision.field_key != self.field_key
            or latest_revision.sequence != self.current_sequence
        ):
            raise ValidationError(
                "The profile-value control must point to its exact latest revision.",
                code="profile_value_control_revision_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.field_key = self.field_key.lower()
        if not self._state.adding:
            current = (
                type(self).objects.filter(pk=self.pk).values("current_sequence").first()
            )
            if current and self.current_sequence != current["current_sequence"] + 1:
                raise ValidationError(
                    "Profile-value control sequence must advance exactly once.",
                    code="profile_value_control_sequence_invalid",
                )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Profile-value controls require the retention workflow.",
            code="protected_profile_value_control",
        )


class RegistrationProfileExtensionValueCommandReceipt(UUIDTimeStampedModel):
    """Immutable idempotency and result evidence for one profile-value append."""

    control = models.ForeignKey(
        RegistrationProfileExtensionValueControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="profile_extension_value_command_receipts",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    field = models.ForeignKey(
        RegistrationProfileExtensionField,
        on_delete=models.PROTECT,
        related_name="value_command_receipts",
    )
    revision = models.OneToOneField(
        RegistrationProfileExtensionValueRevision,
        on_delete=models.PROTECT,
        related_name="command_receipt",
    )
    actor = models.ForeignKey(
        "identity.Account",
        on_delete=models.PROTECT,
        related_name="registration_profile_extension_value_command_receipts",
    )
    writer_kind = models.CharField(
        max_length=8,
        choices=ProfileExtensionValueWriterKind,
    )
    retry_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(_SHA256_VALIDATOR,),
    )
    expected_sequence = models.PositiveIntegerField()
    result_sequence = models.PositiveIntegerField()
    correlation_id = models.UUIDField()
    request_id = models.UUIDField(null=True, blank=True)
    source_channel = models.CharField(
        max_length=32,
        validators=(_PROFILE_VALUE_SOURCE_VALIDATOR,),
    )

    class Meta:
        ordering = ("registration_id", "result_sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "registration", "retry_key"),
                name="reg_profile_value_retry_key_unique",
            ),
            models.UniqueConstraint(
                fields=("control", "result_sequence"),
                name="reg_profile_value_receipt_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(result_sequence=models.F("expected_sequence") + 1),
                name="reg_profile_value_receipt_sequence_exact",
            ),
            models.CheckConstraint(
                condition=Q(source_channel__regex=r"^[a-z][a-z0-9_-]{0,31}$"),
                name="reg_profile_value_receipt_source_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "registration"),
                name="reg_prof_val_rcpt_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The profile-value receipt must match its registration scope.",
                code="profile_value_receipt_scope_mismatch",
            )
        if self.control_id and (
            self.control.registration_id != self.registration_id
            or self.control.organization_id != self.organization_id
            or self.control.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The profile-value receipt must match its sequence control.",
                code="profile_value_receipt_control_mismatch",
            )
        if self.field_id and (
            self.field.organization_id != self.organization_id
            or self.field.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The profile-value receipt must match its field scope.",
                code="profile_value_receipt_field_mismatch",
            )
        if self.revision_id and (
            self.revision.registration_id != self.registration_id
            or self.revision.field_id != self.field_id
            or self.revision.actor_id != self.actor_id
            or self.revision.sequence != self.result_sequence
            or self.revision.source_channel != self.source_channel
        ):
            raise ValidationError(
                "The profile-value receipt must match its exact result revision.",
                code="profile_value_receipt_revision_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Profile-value command receipts are immutable.",
                code="immutable_profile_value_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Profile-value command receipts require the retention workflow.",
            code="protected_profile_value_command_receipt",
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


class RegistrationCommerceControl(UUIDTimeStampedModel):
    """Version fence for governed live registration-commerce operations."""

    configuration = models.OneToOneField(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="commerce_control",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    aggregate_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("organization_id", "edition_id", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="reg_commerce_control_version_positive",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.configuration_id and (
            self.configuration.organization_id != self.organization_id
            or self.configuration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The commerce control must match its configuration scope.",
                code="registration_commerce_control_scope_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration commerce controls require the recovery workflow.",
            code="protected_registration_commerce_control",
        )


class RegistrationCommerceCommandReceipt(UUIDTimeStampedModel):
    """Immutable replay evidence for one governed commerce command."""

    class Operation(models.TextChoices):
        TIER_REPLACEMENT_RESERVED = (
            "tier_replacement_reserved",
            "Admission tier replacement reserved",
        )
        OVERALL_CAPACITY_ADJUSTED = (
            "overall_capacity_adjusted",
            "Overall capacity adjusted",
        )
        PRODUCT_CAPACITY_ADJUSTED = (
            "product_capacity_adjusted",
            "Product capacity adjusted",
        )
        WAITLIST_BATCH_OFFERED = (
            "waitlist_batch_offered",
            "Waitlist batch offered",
        )

    control = models.ForeignKey(
        RegistrationCommerceControl,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    registration = models.ForeignKey(
        Registration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="commerce_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_commerce_command_receipts",
    )
    operation = models.CharField(max_length=48, choices=Operation)
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    expected_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()
    result_id = models.UUIDField()
    result_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("control", "actor", "idempotency_key"),
                name="reg_commerce_command_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(expected_version__gt=0),
                name="reg_commerce_receipt_expected_positive",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=models.F("expected_version")),
                name="reg_commerce_receipt_version_advanced",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration commerce command receipts are immutable.",
                code="immutable_registration_commerce_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration commerce command receipts require retention workflow.",
            code="protected_registration_commerce_receipt",
        )


class RegistrationCapacityAdjustment(UUIDTimeStampedModel):
    """Append-only effective-capacity change below an immutable hard ceiling."""

    class Scope(models.TextChoices):
        OVERALL = "overall", "Overall registration"
        PRODUCT = "product", "Admission product"

    control = models.ForeignKey(
        RegistrationCommerceControl,
        on_delete=models.PROTECT,
        related_name="capacity_adjustments",
    )
    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="capacity_adjustments",
    )
    product = models.ForeignKey(
        AdmissionProduct,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capacity_adjustments",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    scope = models.CharField(max_length=16, choices=Scope)
    previous_capacity = models.PositiveIntegerField()
    new_capacity = models.PositiveIntegerField()
    hard_ceiling = models.PositiveIntegerField()
    control_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_capacity_adjustments",
    )
    reason = models.CharField(max_length=500)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("control_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("control", "control_version"),
                name="reg_capacity_adjustment_version_unique",
            ),
            models.CheckConstraint(
                condition=Q(previous_capacity__gt=0, new_capacity__gt=0),
                name="reg_capacity_adjustment_values_positive",
            ),
            models.CheckConstraint(
                condition=Q(new_capacity__lte=models.F("hard_ceiling")),
                name="reg_capacity_adjustment_below_ceiling",
            ),
            models.CheckConstraint(
                condition=(
                    Q(scope="overall", product__isnull=True)
                    | Q(scope="product", product__isnull=False)
                ),
                name="reg_capacity_adjustment_scope_shape",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "scope", "occurred_at"),
                name="reg_capacity_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.configuration_id and (
            self.configuration.organization_id != self.organization_id
            or self.configuration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The capacity adjustment scope does not match.",
                code="registration_capacity_adjustment_scope_mismatch",
            )
        if self.control_id and self.control.configuration_id != self.configuration_id:
            raise ValidationError(
                "The capacity adjustment control does not match.",
                code="registration_capacity_adjustment_control_mismatch",
            )
        if self.product_id:
            product = cast(AdmissionProduct, self.product)
            if product.configuration_id != self.configuration_id:
                raise ValidationError(
                    "The capacity adjustment product does not match.",
                    code="registration_capacity_adjustment_product_mismatch",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Registration capacity adjustments are append-only.",
                code="immutable_registration_capacity_adjustment",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Registration capacity adjustments are append-only.",
            code="protected_registration_capacity_adjustment",
        )


class AdmissionTierReplacement(UUIDTimeStampedModel):
    """A target-capacity hold for replacing one already-paid admission tier."""

    class Status(models.TextChoices):
        PAYMENT_PENDING = "payment_pending", "Payment pending"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    registration = models.ForeignKey(
        Registration,
        on_delete=models.PROTECT,
        related_name="tier_replacements",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    source_product = models.ForeignKey(
        AdmissionProduct,
        on_delete=models.PROTECT,
        related_name="tier_replacements_from",
    )
    target_product = models.ForeignKey(
        AdmissionProduct,
        on_delete=models.PROTECT,
        related_name="tier_replacements_to",
    )
    source_product_name_snapshot = models.CharField(max_length=160)
    target_product_name_snapshot = models.CharField(max_length=160)
    source_price_minor_snapshot = models.PositiveBigIntegerField()
    target_price_minor_snapshot = models.PositiveBigIntegerField()
    amount_due_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    source_entitlement_code = models.SlugField(max_length=80)
    target_entitlement_code = models.SlugField(max_length=80)
    target_entitlement_name_snapshot = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24,
        choices=Status,
        default=Status.PAYMENT_PENDING,
    )
    aggregate_version = models.PositiveIntegerField(default=1)
    expected_registration_version = models.PositiveIntegerField()
    resulting_registration_version = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    reserved_at = models.DateTimeField()
    payment_due_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admission_tier_replacements",
    )

    class Meta:
        ordering = ("-reserved_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("registration",),
                condition=Q(status="payment_pending"),
                name="one_pending_tier_replacement_per_registration",
            ),
            models.CheckConstraint(
                condition=Q(amount_due_minor__gt=0),
                name="tier_replacement_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    target_price_minor_snapshot__gt=models.F(
                        "source_price_minor_snapshot"
                    )
                ),
                name="tier_replacement_price_increases",
            ),
            models.CheckConstraint(
                condition=Q(payment_due_at__gt=models.F("reserved_at")),
                name="tier_replacement_deadline_after_reservation",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "status", "payment_due_at"),
                name="tier_replacement_expiry_idx",
            ),
            models.Index(
                fields=("target_product", "status", "reserved_at"),
                name="tier_replacement_capacity_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.registration_id and (
            self.registration.organization_id != self.organization_id
            or self.registration.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The tier replacement scope does not match its registration.",
                code="tier_replacement_scope_mismatch",
            )
        if (
            self.source_product_id
            and self.target_product_id
            and (
                self.source_product_id == self.target_product_id
                or self.source_product.configuration_id
                != self.target_product.configuration_id
                or self.registration.configuration_id
                != self.source_product.configuration_id
            )
        ):
            raise ValidationError(
                "The admission products do not form a valid replacement.",
                code="tier_replacement_product_mismatch",
            )
        if (
            self.target_price_minor_snapshot - self.source_price_minor_snapshot
            != self.amount_due_minor
        ):
            raise ValidationError(
                "The tier replacement amount must equal the configured "
                "price difference.",
                code="tier_replacement_amount_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Admission tier replacements require the retention workflow.",
            code="protected_admission_tier_replacement",
        )


class WaitlistBatchOffer(UUIDTimeStampedModel):
    """Immutable evidence for offering only the next strict FIFO batch."""

    control = models.ForeignKey(
        RegistrationCommerceControl,
        on_delete=models.PROTECT,
        related_name="waitlist_batches",
    )
    configuration = models.ForeignKey(
        RegistrationConfiguration,
        on_delete=models.PROTECT,
        related_name="waitlist_batches",
    )
    product = models.ForeignKey(
        AdmissionProduct,
        on_delete=models.PROTECT,
        related_name="waitlist_batches",
    )
    organization_id = models.UUIDField()
    edition_id = models.UUIDField()
    requested_size = models.PositiveIntegerField()
    offered_count = models.PositiveIntegerField()
    control_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_waitlist_batches",
    )
    reason = models.CharField(max_length=500)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("-occurred_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("control", "control_version"),
                name="reg_waitlist_batch_version_unique",
            ),
            models.CheckConstraint(
                condition=Q(offered_count__lte=models.F("requested_size")),
                name="reg_waitlist_batch_within_requested",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization_id", "edition_id", "occurred_at"),
                name="reg_waitlist_batch_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.configuration_id and (
            self.configuration.organization_id != self.organization_id
            or self.configuration.edition_id != self.edition_id
            or self.product.configuration_id != self.configuration_id
            or self.control.configuration_id != self.configuration_id
        ):
            raise ValidationError(
                "The waitlist batch scope does not match.",
                code="registration_waitlist_batch_scope_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Waitlist batch evidence is immutable.",
                code="immutable_waitlist_batch_offer",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Waitlist batch evidence is immutable.",
            code="protected_waitlist_batch_offer",
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
    tier_replacement = models.ForeignKey(
        AdmissionTierReplacement,
        null=True,
        blank=True,
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
        if self.tier_replacement_id:
            tier_replacement = cast(
                AdmissionTierReplacement,
                self.tier_replacement,
            )
            if (
                tier_replacement.registration_id != self.registration_id
                or tier_replacement.organization_id != self.organization_id
                or tier_replacement.edition_id != self.edition_id
                or self.amount_minor != tier_replacement.amount_due_minor
                or self.currency != tier_replacement.currency
            ):
                raise ValidationError(
                    "The payment intent does not match its tier replacement.",
                    code="payment_intent_tier_replacement_mismatch",
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
    tier_replacements_expired = models.PositiveIntegerField(default=0)
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
