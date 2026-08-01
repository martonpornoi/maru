"""Organizer-owned structural aggregates."""

from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
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


class OrganizationRepresentation(UUIDTimeStampedModel):
    """The accountable organization-level representation root.

    Representation is deliberately separate from platform administration,
    ordinary organization membership, and edition workforce structure.  The
    first supported representation type is the Executive Board required by
    IDN-012.
    """

    EXECUTIVE_BOARD_CODE = "executive_board"
    EXECUTIVE_BOARD_NAME = "Executive Board"

    class State(models.TextChoices):
        PROVISIONING = "provisioning", "Provisioning"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="representation",
    )
    code = models.CharField(
        max_length=40,
        default=EXECUTIVE_BOARD_CODE,
        editable=False,
    )
    name = models.CharField(max_length=120, default="Executive Board")
    state = models.CharField(
        max_length=20,
        choices=State,
        default=State.PROVISIONING,
    )
    aggregate_version = models.PositiveIntegerField(default=1, editable=False)
    provisioning_reason = models.CharField(max_length=240)
    activation_reason = models.CharField(max_length=240, blank=True)
    provisioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_representations_provisioned",
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="organization_representations_activated",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("organization__name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code="executive_board"),
                name="organization_representation_exec_board_code",
            ),
            models.CheckConstraint(
                condition=models.Q(name="Executive Board"),
                name="organization_representation_exec_board_name",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gte=1),
                name="organization_representation_version_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(provisioning_reason=""),
                name="organization_representation_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="provisioning",
                        activated_at__isnull=True,
                        activated_by__isnull=True,
                        activation_reason="",
                    )
                    | (
                        models.Q(
                            state__in=("active", "suspended"),
                            activated_at__isnull=False,
                            activated_by__isnull=False,
                        )
                        & ~models.Q(activation_reason="")
                    )
                ),
                name="organization_representation_activation_state",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.provisioned_by_id and not self.provisioned_by.is_platform_administrator:
            raise ValidationError(
                {
                    "provisioned_by": ValidationError(
                        "Initial representation provisioning requires a platform "
                        "administrator.",
                        code="representation_provisioner_not_platform_administrator",
                    )
                },
            )
        activated_by = self.activated_by
        if self.activated_by_id and (
            activated_by is None or not activated_by.is_platform_administrator
        ):
            raise ValidationError(
                {
                    "activated_by": ValidationError(
                        "Initial representation activation requires a platform "
                        "administrator.",
                        code="representation_activator_not_platform_administrator",
                    )
                },
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.EXECUTIVE_BOARD_CODE
        self.name = self.EXECUTIVE_BOARD_NAME
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} — {self.organization.name}"


class RepresentationAppointment(UUIDTimeStampedModel):
    """One invitation and accepted term in an organization representation."""

    class Role(models.TextChoices):
        CONTROLLER = "controller", "Controller"

    class State(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        ACTIVE = "active", "Active"
        DECLINED = "declined", "Declined"
        ENDED = "ended", "Ended"

    representation = models.ForeignKey(
        OrganizationRepresentation,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="representation_appointments",
    )
    role = models.CharField(
        max_length=20,
        choices=Role,
        default=Role.CONTROLLER,
    )
    state = models.CharField(
        max_length=20,
        choices=State,
        default=State.INVITED,
    )
    invitation_version = models.PositiveIntegerField(default=1, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="representation_appointments_invited",
    )
    invited_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=240)
    role_assignment = models.OneToOneField(
        "authorization.RoleAssignment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="representation_appointment",
    )

    class Meta:
        ordering = ("representation_id", "invited_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("representation", "account"),
                condition=models.Q(state__in=("invited", "accepted", "active")),
                name="one_open_representation_appointment_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(role="controller"),
                name="representation_appointment_controller_role",
            ),
            models.CheckConstraint(
                condition=models.Q(invitation_version__gte=1),
                name="representation_appointment_version_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="representation_appointment_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="invited",
                        responded_at__isnull=True,
                        activated_at__isnull=True,
                        ended_at__isnull=True,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        state="accepted",
                        responded_at__isnull=False,
                        activated_at__isnull=True,
                        ended_at__isnull=True,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        state="active",
                        responded_at__isnull=False,
                        activated_at__isnull=False,
                        ended_at__isnull=True,
                        role_assignment__isnull=False,
                    )
                    | models.Q(
                        state="declined",
                        responded_at__isnull=False,
                        activated_at__isnull=True,
                        ended_at__isnull=False,
                        role_assignment__isnull=True,
                    )
                    | (
                        models.Q(
                            state="ended",
                            responded_at__isnull=False,
                            ended_at__isnull=False,
                        )
                        & (
                            models.Q(
                                activated_at__isnull=True,
                                role_assignment__isnull=True,
                            )
                            | models.Q(
                                activated_at__isnull=False,
                                role_assignment__isnull=False,
                            )
                        )
                    )
                ),
                name="representation_appointment_state_timestamps",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.account_id:
            validate_convention_subject(self.account)
        if self.role_assignment_id:
            assignment = self.role_assignment
            if assignment is None or (
                assignment.organization_id != self.representation.organization_id
                or assignment.principal_id != self.account_id
                or assignment.edition_id is not None
                or assignment.role_bundle.code != "executive-board"
            ):
                raise ValidationError(
                    {
                        "role_assignment": ValidationError(
                            "Use this controller's organization-scoped Executive "
                            "Board assignment.",
                            code="representation_assignment_scope_mismatch",
                        )
                    },
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.role = self.Role.CONTROLLER
        if self.account_id:
            validate_convention_subject(self.account)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.account} — {self.get_role_display()} at {self.representation}"
