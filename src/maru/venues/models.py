"""Reusable venue facts, edition space selection, and conflict-safe bookings."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField
from django.contrib.postgres.fields.ranges import RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from maru.core.localization import validate_country_code
from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug

from .writer_boundary import require_venue_writer

MAX_VENUE_REASON_LENGTH = 1_000
MAX_VENUE_TEXT_LENGTH = 5_000

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 digest.",
    code="invalid_venue_digest",
)
_PHONE_VALIDATOR = RegexValidator(
    regex=r"^\+[1-9]\d{6,14}$",
    message="Enter one international telephone number.",
)


class _ClosedVenueModel(UUIDTimeStampedModel):
    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        require_venue_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Venue records are retained; use a lifecycle command.",
            code="protected_venue_record",
        )


class _AppendOnlyVenueModel(_ClosedVenueModel):
    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Venue evidence is append-only.",
                code="immutable_venue_evidence",
            )
        super().save(*args, **kwargs)


class VenueProperty(_ClosedVenueModel):
    """Organizer-owned reusable hotel or venue, never a Maru tenant."""

    class Kind(models.TextChoices):
        HOTEL = "hotel", "Hotel"
        VENUE = "venue", "Venue"
        MIXED = "mixed", "Hotel and venue"

    class Lifecycle(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_properties",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    slug = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    legal_name = models.CharField(max_length=240)
    provider_name = models.CharField(max_length=240, blank=True)
    public_name = models.CharField(max_length=200)
    public_description = models.TextField(max_length=MAX_VENUE_TEXT_LENGTH, blank=True)
    internal_notes = models.TextField(max_length=MAX_VENUE_TEXT_LENGTH, blank=True)
    location_name = models.CharField(max_length=240)
    postal_address = models.TextField(max_length=1_000)
    country_code = models.CharField(max_length=2, validators=(validate_country_code,))
    website_url = models.URLField(blank=True)
    public_contact = models.CharField(max_length=240, blank=True)
    contact_name = models.CharField(max_length=240, blank=True)
    contact_email = models.EmailField(blank=True, validators=(EmailValidator(),))
    contact_phone = models.CharField(
        max_length=16,
        blank=True,
        validators=(_PHONE_VALIDATOR,),
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.DRAFT,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_properties_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_properties_modified",
    )

    class Meta:
        ordering = ("organization_id", "public_name", "id")
        constraints = [
            models.UniqueConstraint(
                F("organization"),
                Lower("slug"),
                name="venue_property_org_slug_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="venue_property_version_pos",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.lower()
        self.country_code = self.country_code.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.public_name


class VenuePropertyMedia(_ClosedVenueModel):
    class Kind(models.TextChoices):
        PHOTO = "photo", "Photo"
        LOGO = "logo", "Logo"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        WITHDRAWN = "withdrawn", "Withdrawn"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_property_media",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="media_references",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    source_reference = models.CharField(max_length=1_000)
    public_reference = models.CharField(max_length=1_000, blank=True)
    owner_name = models.CharField(max_length=240)
    license_basis = models.CharField(max_length=500)
    usage_scope = models.CharField(max_length=500)
    attribution = models.CharField(max_length=500, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus,
        default=ReviewStatus.PENDING,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_media_submitted",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="venue_media_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("property_id", "kind", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="venue_media_version_pos",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.property_id and self.property.organization_id != self.organization_id:
            raise ValidationError(
                "Venue media must remain in its property organization.",
                code="venue_media_scope_mismatch",
            )


class VenueSite(_ClosedVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_sites",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="sites",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    public_description = models.TextField(max_length=2_000, blank=True)
    postal_address = models.TextField(max_length=1_000, blank=True)
    access_facts = models.TextField(max_length=2_000, blank=True)
    is_active = models.BooleanField(default=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("property_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                F("property"), Lower("code"), name="venue_site_property_code_uq"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.property_id and self.property.organization_id != self.organization_id:
            raise ValidationError(
                "Venue site must remain in its property organization.",
                code="venue_site_scope_mismatch",
            )


class VenueBuilding(_ClosedVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_buildings",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="buildings",
    )
    site = models.ForeignKey(
        VenueSite,
        on_delete=models.PROTECT,
        related_name="buildings",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    public_description = models.TextField(max_length=2_000, blank=True)
    access_facts = models.TextField(max_length=2_000, blank=True)
    is_active = models.BooleanField(default=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("site_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                F("site"), Lower("code"), name="venue_building_site_code_uq"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.site_id and (
            self.site.organization_id != self.organization_id
            or self.site.property_id != self.property_id
        ):
            raise ValidationError(
                "Venue building must remain in its exact site and property.",
                code="venue_building_scope_mismatch",
            )


class VenueSpace(_ClosedVenueModel):
    class Kind(models.TextChoices):
        FUNCTION_ROOM = "function_room", "Function room"
        ZONE = "zone", "Zone"
        ENTRANCE = "entrance", "Entrance"
        ROUTE = "route", "Route"
        LOADING = "loading", "Loading area"
        STORAGE = "storage", "Storage"
        GREEN_ROOM = "green_room", "Green room"
        CATERING = "catering", "Catering space"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_spaces",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="spaces",
    )
    site = models.ForeignKey(
        VenueSite,
        on_delete=models.PROTECT,
        related_name="spaces",
    )
    building = models.ForeignKey(
        VenueBuilding,
        on_delete=models.PROTECT,
        related_name="spaces",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=24, choices=Kind)
    public_description = models.TextField(max_length=2_000, blank=True)
    internal_description = models.TextField(
        max_length=MAX_VENUE_TEXT_LENGTH, blank=True
    )
    accessibility_features = models.TextField(max_length=2_000, blank=True)
    known_barriers = models.TextField(max_length=2_000, blank=True)
    equipment_facts = models.TextField(max_length=2_000, blank=True)
    is_active = models.BooleanField(default=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("building_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                F("building"), Lower("code"), name="venue_space_building_code_uq"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.building_id and (
            self.building.organization_id != self.organization_id
            or self.building.property_id != self.property_id
            or self.building.site_id != self.site_id
        ):
            raise ValidationError(
                "Venue space must remain in its exact building chain.",
                code="venue_space_scope_mismatch",
            )


class VenueSpaceConfiguration(_ClosedVenueModel):
    class Lifecycle(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_space_configurations",
    )
    space = models.ForeignKey(
        VenueSpace,
        on_delete=models.PROTECT,
        related_name="configurations",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=200)
    seated_capacity = models.PositiveIntegerField(default=0)
    standing_capacity = models.PositiveIntegerField(default=0)
    table_capacity = models.PositiveIntegerField(default=0)
    fire_capacity = models.PositiveIntegerField()
    accessibility_features = models.TextField(max_length=2_000, blank=True)
    equipment_facts = models.TextField(max_length=2_000, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.DRAFT,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("space_id", "code", "version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("space", "code", "version"),
                name="venue_space_config_version_uq",
            ),
            models.CheckConstraint(
                condition=Q(fire_capacity__gt=0),
                name="venue_config_fire_capacity_pos",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.space_id and self.space.organization_id != self.organization_id:
            raise ValidationError(
                "Venue configuration must remain in its space organization.",
                code="venue_configuration_scope_mismatch",
            )


class VenueSpaceCombination(_ClosedVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_space_combinations",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="space_combinations",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("property_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                F("property"), Lower("code"), name="venue_combo_property_code_uq"
            ),
        ]


class VenueSpaceCombinationMember(_AppendOnlyVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_space_combination_members",
    )
    combination = models.ForeignKey(
        VenueSpaceCombination,
        on_delete=models.PROTECT,
        related_name="members",
    )
    space = models.ForeignKey(
        VenueSpace,
        on_delete=models.PROTECT,
        related_name="combination_memberships",
    )

    class Meta:
        ordering = ("combination_id", "space_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("combination", "space"),
                name="venue_combo_member_uq",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.combination_id
            and self.space_id
            and (
                self.combination.organization_id != self.organization_id
                or self.space.organization_id != self.organization_id
                or self.space.property_id != self.combination.property_id
            )
        ):
            raise ValidationError(
                "Combined spaces must share one organizer-owned property.",
                code="venue_combination_scope_mismatch",
            )


class VenueLayoutVersion(_ClosedVenueModel):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        INTERNAL = "internal", "Internal"
        SECURITY = "security", "Security"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        WITHDRAWN = "withdrawn", "Withdrawn"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_layout_versions",
    )
    space = models.ForeignKey(
        VenueSpace,
        on_delete=models.PROTECT,
        related_name="layout_versions",
    )
    layout_code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    visibility = models.CharField(max_length=16, choices=Visibility)
    source_reference = models.CharField(max_length=1_000)
    approved_reference = models.CharField(max_length=1_000, blank=True)
    checksum_sha256 = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    notes = models.TextField(max_length=2_000, blank=True)
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus,
        default=ReviewStatus.PENDING,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_layouts_submitted",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="venue_layouts_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("space_id", "layout_code", "version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("space", "layout_code", "version"),
                name="venue_layout_space_version_uq",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.space_id and self.space.organization_id != self.organization_id:
            raise ValidationError(
                "Venue layout must remain in its space organization.",
                code="venue_layout_scope_mismatch",
            )


class AccommodationRoomType(_ClosedVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="accommodation_room_types",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="accommodation_room_types",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    public_name = models.CharField(max_length=200)
    description = models.TextField(max_length=2_000, blank=True)
    accessible_features = models.TextField(max_length=2_000, blank=True)
    minimum_occupants = models.PositiveSmallIntegerField(default=1)
    maximum_occupants = models.PositiveSmallIntegerField()
    provider_reference = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("property_id", "public_name", "id")
        constraints = [
            models.UniqueConstraint(
                F("property"), Lower("code"), name="venue_room_type_property_code_uq"
            ),
            models.CheckConstraint(
                condition=Q(maximum_occupants__gte=F("minimum_occupants")),
                name="venue_room_type_occupancy_order",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.property_id and (
            self.property.organization_id != self.organization_id
            or self.property.kind == VenueProperty.Kind.VENUE
        ):
            raise ValidationError(
                "Accommodation types require a hotel or mixed property in scope.",
                code="venue_room_type_property_mismatch",
            )


class AccommodationNightInventory(_ClosedVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="accommodation_night_inventory",
    )
    room_type = models.ForeignKey(
        AccommodationRoomType,
        on_delete=models.PROTECT,
        related_name="night_inventory",
    )
    night = models.DateField()
    room_capacity = models.PositiveIntegerField()
    release_at = models.DateTimeField()
    provider_reference = models.CharField(max_length=240, blank=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("room_type_id", "night", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("room_type", "night"),
                name="venue_room_night_inventory_uq",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.room_type_id and self.room_type.organization_id != self.organization_id:
            raise ValidationError(
                "Accommodation inventory must remain in its organizer scope.",
                code="venue_room_inventory_scope_mismatch",
            )


class EditionVenueSelection(_ClosedVenueModel):
    class Lifecycle(models.TextChoices):
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="edition_venue_selections",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="venue_selections",
    )
    property = models.ForeignKey(
        VenueProperty,
        on_delete=models.PROTECT,
        related_name="edition_selections",
    )
    responsible_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="edition_venue_selections",
    )
    local_name = models.CharField(max_length=200)
    public_description_override = models.TextField(max_length=2_000, blank=True)
    public_contact_override = models.CharField(max_length=240, blank=True)
    opening_restrictions = models.TextField(max_length=2_000, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="edition_venues_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="edition_venues_modified",
    )

    class Meta:
        ordering = ("edition_id", "local_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "property"),
                name="venue_edition_property_uq",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "Edition venue selection must match its organization.",
                code="venue_selection_edition_scope",
            )
        if self.property_id and self.property.organization_id != self.organization_id:
            raise ValidationError(
                "Edition venue selection requires an organizer-owned property.",
                code="venue_selection_property_scope",
            )
        if self.responsible_department_id and (
            self.responsible_department.organization_id != self.organization_id
            or self.responsible_department.edition_id != self.edition_id
            or self.responsible_department.retired_at is not None
        ):
            raise ValidationError(
                "Edition venue selection requires a current exact-edition Department.",
                code="venue_selection_department_scope",
            )


class EditionSpaceSelection(_ClosedVenueModel):
    class Lifecycle(models.TextChoices):
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="edition_space_selections",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="space_selections",
    )
    venue_selection = models.ForeignKey(
        EditionVenueSelection,
        on_delete=models.PROTECT,
        related_name="space_selections",
    )
    responsible_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="edition_space_selections",
    )
    source_space = models.ForeignKey(
        VenueSpace,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="edition_selections",
    )
    source_combination = models.ForeignKey(
        VenueSpaceCombination,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="edition_selections",
    )
    selected_configuration = models.ForeignKey(
        VenueSpaceConfiguration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="edition_selections",
    )
    local_name = models.CharField(max_length=200)
    configuration_name = models.CharField(max_length=200)
    seated_capacity = models.PositiveIntegerField(default=0)
    standing_capacity = models.PositiveIntegerField(default=0)
    table_capacity = models.PositiveIntegerField(default=0)
    fire_capacity = models.PositiveIntegerField()
    public_access_info = models.TextField(max_length=2_000, blank=True)
    opening_restrictions = models.TextField(max_length=2_000, blank=True)
    current_availability_version = models.PositiveBigIntegerField(default=0)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        ordering = ("edition_id", "local_name", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(source_space__isnull=False, source_combination__isnull=True)
                    | Q(source_space__isnull=True, source_combination__isnull=False)
                ),
                name="venue_edition_space_one_source",
            ),
            models.CheckConstraint(
                condition=Q(fire_capacity__gt=0),
                name="venue_edition_space_fire_pos",
            ),
            models.UniqueConstraint(
                fields=("edition", "source_space"),
                condition=Q(source_space__isnull=False),
                name="venue_edition_source_space_uq",
            ),
            models.UniqueConstraint(
                fields=("edition", "source_combination"),
                condition=Q(source_combination__isnull=False),
                name="venue_edition_source_combo_uq",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.venue_selection_id and (
            self.venue_selection.organization_id != self.organization_id
            or self.venue_selection.edition_id != self.edition_id
            or self.venue_selection.responsible_department_id
            != self.responsible_department_id
        ):
            raise ValidationError(
                "Edition space must remain in its selected venue scope.",
                code="venue_edition_space_scope_mismatch",
            )
        source_space = self.source_space if self.source_space_id else None
        if source_space is not None and (
            source_space.organization_id != self.organization_id
            or source_space.property_id != self.venue_selection.property_id
        ):
            raise ValidationError(
                "Edition space source must belong to the selected property.",
                code="venue_edition_space_source_mismatch",
            )
        source_combination = (
            self.source_combination if self.source_combination_id else None
        )
        if source_combination is not None and (
            source_combination.organization_id != self.organization_id
            or source_combination.property_id != self.venue_selection.property_id
        ):
            raise ValidationError(
                "Edition combination must belong to the selected property.",
                code="venue_edition_space_source_mismatch",
            )
        selected_configuration = (
            self.selected_configuration if self.selected_configuration_id else None
        )
        if selected_configuration is not None and (
            self.source_space_id is None
            or selected_configuration.space_id != self.source_space_id
            or selected_configuration.lifecycle
            != VenueSpaceConfiguration.Lifecycle.ACTIVE
        ):
            raise ValidationError(
                "Edition space configuration must be active for its source space.",
                code="venue_edition_space_configuration_mismatch",
            )


class EditionSpaceMember(_AppendOnlyVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="edition_space_members",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="space_members",
    )
    space_selection = models.ForeignKey(
        EditionSpaceSelection,
        on_delete=models.PROTECT,
        related_name="physical_members",
    )
    source_space = models.ForeignKey(
        VenueSpace,
        on_delete=models.PROTECT,
        related_name="edition_physical_memberships",
    )

    class Meta:
        ordering = ("space_selection_id", "source_space_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("space_selection", "source_space"),
                name="venue_edition_space_member_uq",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.space_selection_id
            and self.source_space_id
            and (
                self.space_selection.organization_id != self.organization_id
                or self.space_selection.edition_id != self.edition_id
                or self.source_space.organization_id != self.organization_id
                or self.source_space.property_id
                != self.space_selection.venue_selection.property_id
            )
        ):
            raise ValidationError(
                "Edition physical member must remain in its exact space scope.",
                code="venue_edition_member_scope_mismatch",
            )


class EditionSpaceAvailabilityWindow(_AppendOnlyVenueModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="edition_space_availability",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="space_availability",
    )
    space_selection = models.ForeignKey(
        EditionSpaceSelection,
        on_delete=models.PROTECT,
        related_name="availability_windows",
    )
    availability_version = models.PositiveBigIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    opening_restriction = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("space_selection_id", "availability_version", "starts_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "space_selection",
                    "availability_version",
                    "starts_at",
                    "ends_at",
                ),
                name="venue_space_availability_uq",
            ),
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at")),
                name="venue_space_availability_order",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.space_selection_id and (
            self.space_selection.organization_id != self.organization_id
            or self.space_selection.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Availability must remain in its exact edition space.",
                code="venue_availability_scope_mismatch",
            )


class VenueBooking(_ClosedVenueModel):
    class Kind(models.TextChoices):
        PROGRAMME = "programme", "Programme"
        PANEL = "panel", "Panel"
        EVENT = "event", "Event"
        DEPARTMENT = "department", "Department"
        STORAGE = "storage", "Storage"
        CATERING = "catering", "Catering"
        REHEARSAL = "rehearsal", "Rehearsal"
        PRIVATE = "private", "Private"

    class CapacityMode(models.TextChoices):
        SEATED = "seated", "Seated"
        STANDING = "standing", "Standing"
        TABLE = "table", "Table"

    class Lifecycle(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Cancelled"

    class ReviewState(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"

    class PublicationState(models.TextChoices):
        UNPUBLISHED = "unpublished", "Unpublished"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_bookings",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="venue_bookings",
    )
    space_selection = models.ForeignKey(
        EditionSpaceSelection,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    responsible_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="venue_bookings",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    external_reference = models.CharField(max_length=240, blank=True)
    internal_title = models.CharField(max_length=240)
    public_title = models.CharField(max_length=240, blank=True)
    public_description = models.TextField(max_length=2_000, blank=True)
    capacity_mode = models.CharField(max_length=16, choices=CapacityMode)
    expected_attendance = models.PositiveIntegerField()
    setup_starts_at = models.DateTimeField()
    effective_starts_at = models.DateTimeField()
    effective_ends_at = models.DateTimeField()
    teardown_ends_at = models.DateTimeField()
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    review_state = models.CharField(
        max_length=16,
        choices=ReviewState,
        default=ReviewState.DRAFT,
    )
    publication_state = models.CharField(
        max_length=16,
        choices=PublicationState,
        default=PublicationState.UNPUBLISHED,
    )
    public_layout = models.ForeignKey(
        VenueLayoutVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="public_bookings",
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_bookings_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_bookings_modified",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="venue_bookings_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="venue_bookings_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "effective_starts_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(setup_starts_at__lte=F("effective_starts_at"))
                    & Q(effective_starts_at__lt=F("effective_ends_at"))
                    & Q(effective_ends_at__lte=F("teardown_ends_at"))
                ),
                name="venue_booking_envelope_order",
            ),
            models.CheckConstraint(
                condition=Q(expected_attendance__gt=0),
                name="venue_booking_attendance_pos",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(publication_state="published") | Q(review_state="approved")
                ),
                name="venue_booking_publish_approved",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.space_selection_id and (
            self.space_selection.organization_id != self.organization_id
            or self.space_selection.edition_id != self.edition_id
            or self.space_selection.responsible_department_id
            != self.responsible_department_id
        ):
            raise ValidationError(
                "Booking must remain in its exact edition space scope.",
                code="venue_booking_scope_mismatch",
            )
        public_layout = self.public_layout if self.public_layout_id else None
        if public_layout is not None and (
            public_layout.organization_id != self.organization_id
            or public_layout.visibility != VenueLayoutVersion.Visibility.PUBLIC
            or public_layout.review_status != VenueLayoutVersion.ReviewStatus.APPROVED
        ):
            raise ValidationError(
                "Public bookings may use only an approved public layout rendition.",
                code="venue_booking_public_layout_invalid",
            )


class VenueBookingHistory(_AppendOnlyVenueModel):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        RESCHEDULED = "rescheduled", "Rescheduled"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Publication withdrawn"
        CANCELLED = "cancelled", "Cancelled"

    booking = models.ForeignKey(
        VenueBooking,
        on_delete=models.PROTECT,
        related_name="history_entries",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_booking_history",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="venue_booking_history",
    )
    sequence = models.PositiveBigIntegerField()
    booking_version = models.PositiveBigIntegerField()
    action = models.CharField(max_length=16, choices=Action)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_booking_history_acted",
    )
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=MAX_VENUE_REASON_LENGTH)
    old_setup_starts_at = models.DateTimeField(null=True, blank=True)
    old_effective_starts_at = models.DateTimeField(null=True, blank=True)
    old_effective_ends_at = models.DateTimeField(null=True, blank=True)
    old_teardown_ends_at = models.DateTimeField(null=True, blank=True)
    new_setup_starts_at = models.DateTimeField(null=True, blank=True)
    new_effective_starts_at = models.DateTimeField(null=True, blank=True)
    new_effective_ends_at = models.DateTimeField(null=True, blank=True)
    new_teardown_ends_at = models.DateTimeField(null=True, blank=True)
    from_review_state = models.CharField(max_length=16, blank=True)
    to_review_state = models.CharField(max_length=16, blank=True)
    from_publication_state = models.CharField(max_length=16, blank=True)
    to_publication_state = models.CharField(max_length=16, blank=True)
    from_lifecycle = models.CharField(max_length=16, blank=True)
    to_lifecycle = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ("booking_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("booking", "sequence"),
                name="venue_booking_history_sequence_uq",
            )
        ]


class VenueBookingOccupancy(_ClosedVenueModel):
    """Derived physical-space reservations enforcing SCH-009 in PostgreSQL."""

    class ConflictGroup(models.TextChoices):
        SETUP_EFFECTIVE = "setup_effective", "Setup and effective"
        EFFECTIVE_TEARDOWN = "effective_teardown", "Effective and teardown"

    booking = models.ForeignKey(
        VenueBooking,
        on_delete=models.PROTECT,
        related_name="occupancy_rows",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_booking_occupancy",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="venue_booking_occupancy",
    )
    source_space = models.ForeignKey(
        VenueSpace,
        on_delete=models.PROTECT,
        related_name="booking_occupancy",
    )
    conflict_group = models.CharField(max_length=24, choices=ConflictGroup)
    occupied_range = DateTimeRangeField()
    booking_version = models.PositiveBigIntegerField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("source_space_id", "conflict_group", "occupied_range", "id")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "booking",
                    "booking_version",
                    "source_space",
                    "conflict_group",
                ),
                name="venue_booking_occupancy_uq",
            ),
            ExclusionConstraint(
                name="venue_booking_no_overlap",
                expressions=(
                    ("source_space", RangeOperators.EQUAL),
                    ("conflict_group", RangeOperators.EQUAL),
                    ("occupied_range", RangeOperators.OVERLAPS),
                ),
                condition=Q(active=True),
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.booking_id and (
            self.booking.organization_id != self.organization_id
            or self.booking.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Booking occupancy must remain in its booking scope.",
                code="venue_booking_occupancy_scope_mismatch",
            )


class VenueCommandReceipt(_AppendOnlyVenueModel):
    class Operation(models.TextChoices):
        PROPERTY_CREATE = "property.create", "Create property"
        CATALOG_ADD = "catalog.add", "Add catalog record"
        MEDIA_ADD = "media.add", "Add media"
        MEDIA_REVIEW = "media.review", "Review media"
        LAYOUT_ADD = "layout.add", "Add layout"
        LAYOUT_REVIEW = "layout.review", "Review layout"
        ROOM_INVENTORY_SET = "room_inventory.set", "Set room inventory"
        EDITION_SELECT = "edition.select", "Select venue"
        SPACE_SELECT = "space.select", "Select space"
        AVAILABILITY_SET = "availability.set", "Set availability"
        BOOKING_CREATE = "booking.create", "Create booking"
        BOOKING_RESCHEDULE = "booking.reschedule", "Reschedule booking"
        BOOKING_APPROVE = "booking.approve", "Approve booking"
        BOOKING_PUBLISH = "booking.publish", "Publish booking"
        BOOKING_WITHDRAW = "booking.withdraw", "Withdraw booking"
        BOOKING_CANCEL = "booking.cancel", "Cancel booking"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="venue_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="venue_command_receipts",
    )
    operation = models.CharField(max_length=32, choices=Operation)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="venue_commands_acted",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    result_object_id = models.UUIDField()
    resulting_version = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        ordering = ("organization_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "operation", "idempotency_key"),
                name="venue_command_retry_uq",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="venue_receipt_version_pos",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        edition = self.edition if self.edition_id else None
        if edition is not None and edition.organization_id != self.organization_id:
            raise ValidationError(
                "Venue receipt edition is outside its organization.",
                code="venue_receipt_scope_mismatch",
            )
