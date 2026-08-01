"""Organizer-owned structural aggregates."""

from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import EmailValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower

from maru.core.localization import (
    validate_country_code,
    validate_language_code_list,
)
from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug, validate_time_zone
from maru.identity.policies import validate_convention_subject


def default_organization_languages() -> list[str]:
    return ["en"]


class Organization(UUIDTimeStampedModel):
    class Lifecycle(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CLOSED = "closed", "Closed"

    slug = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    lifecycle = models.CharField(
        max_length=20,
        choices=Lifecycle,
        default=Lifecycle.DRAFT,
    )
    legal_name = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "Optional registered legal name when it differs from the public name."
        ),
    )
    description = models.TextField(
        blank=True,
        help_text=(
            "Short organizer description for staff context and future public use."
        ),
    )
    website_url = models.URLField(blank=True)
    contact_email = models.EmailField(
        blank=True,
        validators=(EmailValidator(),),
        help_text="General organizer contact; not an account login.",
    )
    contact_phone = models.CharField(
        max_length=16,
        blank=True,
        validators=(
            RegexValidator(
                regex=r"^\+[1-9]\d{6,14}$",
                message="Enter an international telephone number such as +431234567.",
            ),
        ),
        help_text="Optional public contact number stored in E.164 format.",
    )
    legal_address = models.TextField(
        max_length=1000,
        blank=True,
        help_text="Formatted registered postal address for legal notices.",
    )
    legal_representative = models.CharField(
        max_length=200,
        blank=True,
        help_text="Printable representative or responsible office for the imprint.",
    )
    registration_authority = models.CharField(
        max_length=200,
        blank=True,
        help_text="Public register or authority maintaining the organization record.",
    )
    registration_identifier = models.CharField(
        max_length=120,
        blank=True,
        help_text="Public association, company, charity, or registry identifier.",
    )
    tax_identifier = models.CharField(
        max_length=120,
        blank=True,
        help_text="Tax identifier only where it belongs in the public legal profile.",
    )
    imprint_text = models.TextField(
        max_length=5000,
        blank=True,
        help_text="Additional jurisdiction-specific public imprint wording.",
    )
    country_code = models.CharField(
        max_length=2,
        blank=True,
        validators=(validate_country_code,),
        help_text="Primary operating country used only for sensible setup defaults.",
    )
    default_language_codes = ArrayField(
        models.CharField(max_length=2),
        default=default_organization_languages,
        validators=(validate_language_code_list,),
        help_text="Ordered ISO 639-1 languages suggested for new convention editions.",
    )
    default_time_zone = models.CharField(
        max_length=63,
        default="UTC",
        validators=[validate_time_zone],
    )

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                Lower("slug"),
                name="organization_slug_case_insensitive_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.lower()
        self.country_code = self.country_code.upper()
        self.default_language_codes = [
            str(code).lower() for code in self.default_language_codes
        ]
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ConventionSeries(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="convention_series",
    )
    slug = models.SlugField(max_length=80, validators=[validate_lowercase_slug])
    name = models.CharField(max_length=160)
    description = models.TextField(
        blank=True,
        help_text="Public-facing description of this recurring convention brand.",
    )
    website_url = models.URLField(blank=True)
    contact_email = models.EmailField(
        blank=True,
        validators=(EmailValidator(),),
        help_text="Public contact for this convention brand.",
    )
    is_active = models.BooleanField(default=True)
    profile_version = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name_plural = "convention series"
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("organization"),
                Lower("slug"),
                name="series_slug_unique_within_organization",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} — {self.organization.name}"


class OrganizationMembership(UUIDTimeStampedModel):
    class State(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ENDED = "ended", "Ended"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_memberships",
    )
    state = models.CharField(max_length=20, choices=State, default=State.INVITED)
    relationship_label = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("organization_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "account"),
                name="one_membership_per_account_and_organization",
            ),
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
        relationship = self.relationship_label or self.get_state_display()
        return f"{self.account} — {relationship} at {self.organization}"
