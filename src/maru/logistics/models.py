"""Equipment offers, storage containment, custody, and logistics evidence."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField
from django.contrib.postgres.fields.ranges import RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, RegexValidator
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Lower

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug

from .writer_boundary import require_logistics_writer

MAX_LOGISTICS_REASON_LENGTH = 1_000
MAX_LOGISTICS_TEXT_LENGTH = 5_000
MAX_OFFLINE_OPERATIONS = 500

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 digest.",
    code="invalid_logistics_digest",
)
_PHONE_VALIDATOR = RegexValidator(
    regex=r"^\+[1-9]\d{6,14}$",
    message="Enter one international telephone number.",
)


def _half_open_interval() -> Func:
    return Func(
        F("starts_at"),
        F("ends_at"),
        Value("[)"),
        function="TSTZRANGE",
        output_field=DateTimeRangeField(),
    )


class _ClosedLogisticsModel(UUIDTimeStampedModel):
    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        require_logistics_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Logistics records are retained; use a lifecycle command.",
            code="protected_logistics_record",
        )


class _AppendOnlyLogisticsModel(_ClosedLogisticsModel):
    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Logistics evidence is append-only.",
                code="immutable_logistics_evidence",
            )
        super().save(*args, **kwargs)


class LogisticsParty(_ClosedLogisticsModel):
    """Reusable external owner/provider/borrower, never a Maru tenant."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        BUSINESS = "business", "Business"
        INDIVIDUAL = "individual", "Individual"

    class Role(models.TextChoices):
        """Enumerate supported role values."""

        OWNER = "owner", "Owner"
        PROVIDER = "provider", "Provider"
        RENTAL_BUSINESS = "rental_business", "Rental business"
        BORROWER = "borrower", "Borrower"
        MIXED = "mixed", "Multiple roles"

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_parties",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    role = models.CharField(max_length=24, choices=Role)
    code = models.SlugField(max_length=96, validators=(validate_lowercase_slug,))
    legal_name = models.CharField(max_length=240)
    public_name = models.CharField(max_length=200)
    provider_reference = models.CharField(max_length=240, blank=True)
    website_url = models.URLField(max_length=2_000, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_parties_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_parties_modified",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "public_name", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("business", "individual")),
                name="log_party_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(
                    role__in=(
                        "owner",
                        "provider",
                        "rental_business",
                        "borrower",
                        "mixed",
                    )
                ),
                name="log_party_role_choice",
            ),
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "retired")),
                name="log_party_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("code"),
                name="log_party_org_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_party_version_pos",
            ),
        ]

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
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the human-readable LogisticsParty label.

        Returns
        -------
        str
            A human-readable label for the record.
        """
        return self.public_name


class RestrictedLogisticsAddress(_ClosedLogisticsModel):
    """Purpose-bound pickup/storage address, never a containment object."""

    class Purpose(models.TextChoices):
        """Enumerate supported purpose values."""

        PICKUP = "pickup", "Pickup"
        STORAGE = "storage", "Storage"
        RETURN = "return", "Return"
        DELIVERY = "delivery", "Delivery"
        PROVIDER = "provider", "Provider"

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        DISPOSED = "disposed", "Disposed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="restricted_logistics_addresses",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="restricted_logistics_addresses",
    )
    subject_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="restricted_logistics_addresses",
    )
    party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="restricted_addresses",
    )
    purpose = models.CharField(max_length=16, choices=Purpose)
    label = models.CharField(max_length=200)
    recipient_name = models.CharField(max_length=240, blank=True)
    contact_email = models.EmailField(blank=True, validators=(EmailValidator(),))
    contact_phone = models.CharField(
        max_length=16,
        blank=True,
        validators=(_PHONE_VALIDATOR,),
    )
    postal_address = models.TextField(max_length=1_000, blank=True)
    access_instructions = models.TextField(
        max_length=MAX_LOGISTICS_TEXT_LENGTH,
        blank=True,
    )
    retention_until = models.DateTimeField(null=True, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="restricted_logistics_addresses_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "purpose", "label", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    purpose__in=(
                        "pickup",
                        "storage",
                        "return",
                        "delivery",
                        "provider",
                    )
                ),
                name="log_address_purpose_choice",
            ),
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "disposed")),
                name="log_address_life_choice",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_address_version_pos",
            ),
            models.CheckConstraint(
                condition=Q(subject_account__isnull=True)
                | Q(retention_until__isnull=False),
                name="log_person_addr_retention",
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
        if self.lifecycle == self.Lifecycle.ACTIVE and not self.postal_address:
            raise ValidationError(
                "An active restricted address requires a postal address.",
                code="logistics_address_value_required",
            )
        if self.edition_id:
            edition = self.edition
            if edition is None or edition.organization_id != self.organization_id:
                raise ValidationError(
                    "The restricted address must remain in its edition organization.",
                    code="logistics_address_scope_mismatch",
                )
        if self.party_id:
            party = self.party
            if party is None or party.organization_id != self.organization_id:
                raise ValidationError(
                    "The restricted address party must remain in one organization.",
                    code="logistics_address_scope_mismatch",
                )
        if self.subject_account_id and self.party_id:
            raise ValidationError(
                "An address may belong to a person or external party, not both.",
                code="logistics_address_subject_mismatch",
            )


class EquipmentOffer(_ClosedLogisticsModel):
    """A person's self-owned offer, pending until Logistics accepts it."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="equipment_offers",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="equipment_offers",
    )
    offered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="equipment_offers",
    )
    pickup_address = models.ForeignKey(
        RestrictedLogisticsAddress,
        on_delete=models.PROTECT,
        related_name="equipment_offers",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=MAX_LOGISTICS_TEXT_LENGTH, blank=True)
    available_from = models.DateTimeField()
    available_until = models.DateTimeField()
    requested_return_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PENDING,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="equipment_offers_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(max_length=MAX_LOGISTICS_REASON_LENGTH, blank=True)
    responsible_department = models.ForeignKey(
        "workforce.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="equipment_offers",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "-created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "pending",
                        "accepted",
                        "rejected",
                        "withdrawn",
                        "expired",
                    )
                ),
                name="log_offer_status_choice",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_offer_version_pos",
            ),
            models.CheckConstraint(
                condition=Q(available_until__gt=F("available_from")),
                name="log_offer_interval_order",
            ),
            models.CheckConstraint(
                condition=Q(requested_return_at__isnull=True)
                | Q(requested_return_at__gte=F("available_from")),
                name="log_offer_return_order",
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
            raise ValidationError(
                "The equipment offer must remain in its edition organization.",
                code="logistics_offer_scope_mismatch",
            )
        if self.pickup_address_id and (
            self.pickup_address.organization_id != self.organization_id
            or self.pickup_address.edition_id not in {None, self.edition_id}
            or self.pickup_address.subject_account_id != self.offered_by_id
            or self.pickup_address.purpose != RestrictedLogisticsAddress.Purpose.PICKUP
        ):
            raise ValidationError(
                "The offer needs the submitter's purpose-bound pickup address.",
                code="logistics_offer_address_mismatch",
            )
        if self.responsible_department_id:
            department = self.responsible_department
            if department is None or (
                department.organization_id != self.organization_id
                or department.edition_id != self.edition_id
            ):
                raise ValidationError(
                    "The responsible Department must belong to this edition.",
                    code="logistics_offer_department_mismatch",
                )


class EquipmentOfferItem(_AppendOnlyLogisticsModel):
    """Store equipment offer item records."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        SERIALIZED = "serialized", "Serialized item"
        BULK = "bulk", "Bulk stock"

    offer = models.ForeignKey(
        EquipmentOffer,
        on_delete=models.PROTECT,
        related_name="items",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    name = models.CharField(max_length=200)
    description = models.TextField(max_length=2_000, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    manufacturer = models.CharField(max_length=160, blank=True)
    model_name = models.CharField(max_length=160, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    condition = models.CharField(max_length=120)
    value_class = models.CharField(max_length=32, blank=True)
    ownership_statement = models.CharField(max_length=500)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("offer_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("serialized", "bulk")),
                name="log_offer_item_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="log_offer_item_qty_pos",
            ),
            models.CheckConstraint(
                condition=(Q(kind="serialized", quantity=1) | Q(kind="bulk")),
                name="log_offer_item_kind_qty",
            ),
        ]


class EquipmentOfferHistory(_AppendOnlyLogisticsModel):
    """Store equipment offer history records."""

    offer = models.ForeignKey(
        EquipmentOffer,
        on_delete=models.PROTECT,
        related_name="history",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="equipment_offer_history",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="equipment_offer_history",
    )
    status = models.CharField(max_length=16, choices=EquipmentOffer.Status)
    offer_version = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="equipment_offer_history_actions",
    )
    reason = models.TextField(max_length=MAX_LOGISTICS_REASON_LENGTH)
    occurred_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("offer_id", "offer_version", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "pending",
                        "accepted",
                        "rejected",
                        "withdrawn",
                        "expired",
                    )
                ),
                name="log_offer_history_choice",
            ),
            models.UniqueConstraint(
                fields=("offer", "offer_version"),
                name="log_offer_history_version_uq",
            ),
        ]


class EquipmentOfferAcceptance(_AppendOnlyLogisticsModel):
    """Store equipment offer acceptance records."""

    offer_item = models.OneToOneField(
        EquipmentOfferItem,
        on_delete=models.PROTECT,
        related_name="acceptance",
    )
    asset = models.ForeignKey(
        "Asset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offer_acceptances",
    )
    stock_lot = models.ForeignKey(
        "StockLot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offer_acceptances",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="equipment_offer_items_accepted",
    )
    accepted_at = models.DateTimeField()

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(asset__isnull=False, stock_lot__isnull=True)
                    | Q(asset__isnull=True, stock_lot__isnull=False)
                ),
                name="log_acceptance_subject_one",
            ),
            models.UniqueConstraint(
                fields=("asset",),
                condition=Q(asset__isnull=False),
                name="log_acceptance_asset_uq",
            ),
            models.UniqueConstraint(
                fields=("stock_lot",),
                condition=Q(stock_lot__isnull=False),
                name="log_acceptance_lot_uq",
            ),
        ]


class LogisticsNode(_ClosedLogisticsModel):
    """Typed physical object/location; people and addresses are never nodes."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        STORAGE_SITE = "storage_site", "Storage site"
        STORAGE_AREA = "storage_area", "Storage area"
        RACK = "rack", "Rack"
        CONTAINER = "container", "Container"
        BOX = "box", "Box"
        VEHICLE = "vehicle", "Vehicle"
        LOADING_ZONE = "loading_zone", "Loading zone"
        STAGING_AREA = "staging_area", "Staging area"
        VENUE_ROOM = "venue_room", "Venue room"

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"
        RETURNED = "returned", "Returned to provider"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_nodes",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_nodes",
    )
    kind = models.CharField(max_length=24, choices=Kind)
    code = models.SlugField(max_length=96, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    description = models.TextField(max_length=2_000, blank=True)
    storage_address = models.ForeignKey(
        RestrictedLogisticsAddress,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_nodes",
    )
    external_owner = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_logistics_nodes",
    )
    provider = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="provided_logistics_nodes",
    )
    vehicle_registration = models.CharField(max_length=40, blank=True)
    venue_space_selection_id = models.UUIDField(null=True, blank=True)
    capacity_note = models.CharField(max_length=500, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_nodes_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_nodes_modified",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "kind", "name", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    kind__in=(
                        "storage_site",
                        "storage_area",
                        "rack",
                        "container",
                        "box",
                        "vehicle",
                        "loading_zone",
                        "staging_area",
                        "venue_room",
                    )
                ),
                name="log_node_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "retired", "returned")),
                name="log_node_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("code"),
                name="log_node_org_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_node_version_pos",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="venue_room",
                        edition__isnull=False,
                        venue_space_selection_id__isnull=False,
                    )
                    | (~Q(kind="venue_room") & Q(venue_space_selection_id__isnull=True))
                ),
                name="log_node_venue_shape",
            ),
            models.CheckConstraint(
                condition=(Q(kind="vehicle") | Q(vehicle_registration="")),
                name="log_node_vehicle_plate",
            ),
        ]

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
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_id:
            edition = self.edition
            if edition is None or edition.organization_id != self.organization_id:
                raise ValidationError(
                    "The logistics node must remain in its edition organization.",
                    code="logistics_node_scope_mismatch",
                )
        if self.storage_address_id:
            storage_address = self.storage_address
            if storage_address is None or (
                storage_address.organization_id != self.organization_id
                or storage_address.purpose != RestrictedLogisticsAddress.Purpose.STORAGE
                or storage_address.edition_id
                not in ({None, self.edition_id} if self.edition_id else {None})
            ):
                raise ValidationError(
                    "A node may reference only a same-organization storage address.",
                    code="logistics_node_address_mismatch",
                )
        for party in (self.external_owner, self.provider):
            if party is not None and party.organization_id != self.organization_id:
                raise ValidationError(
                    "Node owners and providers must remain in one organization.",
                    code="logistics_node_party_mismatch",
                )
        if self.venue_space_selection_id:
            from maru.venues.models import EditionSpaceSelection  # noqa: PLC0415

            if not EditionSpaceSelection.objects.filter(
                id=self.venue_space_selection_id,
                organization_id=self.organization_id,
                edition_id=self.edition_id,
                lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
            ).exists():
                raise ValidationError(
                    "A venue-room node requires an active exact-edition space.",
                    code="logistics_node_venue_scope_mismatch",
                )


class _OwnedSubject(_ClosedLogisticsModel):
    class OwnerKind(models.TextChoices):
        """Enumerate supported owner kind values."""

        ORGANIZATION = "organization", "Organizer"
        ACCOUNT = "account", "Person account"
        EXTERNAL_PARTY = "external_party", "External party"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="+",
    )
    owner_kind = models.CharField(max_length=16, choices=OwnerKind)
    owner_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    owner_party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def clean(self) -> None:
        super().clean()
        valid_owner = (
            (
                self.owner_kind == self.OwnerKind.ORGANIZATION
                and self.owner_account_id is None
                and self.owner_party_id is None
            )
            or (
                self.owner_kind == self.OwnerKind.ACCOUNT
                and self.owner_account_id is not None
                and self.owner_party_id is None
            )
            or (
                self.owner_kind == self.OwnerKind.EXTERNAL_PARTY
                and self.owner_account_id is None
                and self.owner_party_id is not None
            )
        )
        if not valid_owner:
            raise ValidationError(
                "Select exactly one ownership source.",
                code="logistics_owner_shape_mismatch",
            )
        if self.owner_party_id:
            owner_party = self.owner_party
            if (
                owner_party is None
                or owner_party.organization_id != self.organization_id
            ):
                raise ValidationError(
                    "The external owner must remain in one organization.",
                    code="logistics_owner_scope_mismatch",
                )


class Asset(_OwnedSubject):
    """One serialized asset; location, custody, and condition are event-derived."""

    class Acquisition(models.TextChoices):
        """Enumerate supported acquisition values."""

        OWNED = "owned", "Owned"
        LOAN = "loan", "Loan"
        RENTAL = "rental", "Rental"
        EQUIPMENT_OFFER = "equipment_offer", "Equipment offer"

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        LOST = "lost", "Lost"
        RETURNED = "returned", "Returned"
        DISPOSED = "disposed", "Disposed"

    edition_allocation = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_assets",
    )
    catalog_code = models.SlugField(
        max_length=96,
        validators=(validate_lowercase_slug,),
    )
    name = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=120)
    manufacturer = models.CharField(max_length=160, blank=True)
    model_name = models.CharField(max_length=160, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    acquisition = models.CharField(max_length=24, choices=Acquisition)
    value_class = models.CharField(max_length=32, blank=True)
    maintenance_due_at = models.DateTimeField(null=True, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_assets_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "catalog_code", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    owner_kind__in=("organization", "account", "external_party")
                ),
                name="log_asset_owner_choice",
            ),
            models.CheckConstraint(
                condition=Q(
                    acquisition__in=("owned", "loan", "rental", "equipment_offer")
                ),
                name="log_asset_acquire_choice",
            ),
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "lost", "returned", "disposed")),
                name="log_asset_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("catalog_code"),
                name="log_asset_org_code_uq",
            ),
            models.UniqueConstraint(
                fields=("organization", "serial_number"),
                condition=~Q(serial_number=""),
                name="log_asset_serial_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_asset_version_pos",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.catalog_code = self.catalog_code.lower()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_allocation_id:
            edition_allocation = self.edition_allocation
            if (
                edition_allocation is None
                or edition_allocation.organization_id != self.organization_id
            ):
                raise ValidationError(
                    "An asset allocation must remain in one organization.",
                    code="logistics_asset_scope_mismatch",
                )


class StockLot(_OwnedSubject):
    """One bulk stock lot; current quantity/location derive from events."""

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        EXHAUSTED = "exhausted", "Exhausted"
        RETURNED = "returned", "Returned"
        DISPOSED = "disposed", "Disposed"

    edition_allocation = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_stock_lots",
    )
    catalog_code = models.SlugField(
        max_length=96,
        validators=(validate_lowercase_slug,),
    )
    name = models.CharField(max_length=200)
    stock_type = models.CharField(max_length=120)
    unit = models.CharField(max_length=40)
    initial_quantity = models.PositiveIntegerField()
    value_class = models.CharField(max_length=32, blank=True)
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_stock_lots_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "catalog_code", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    owner_kind__in=("organization", "account", "external_party")
                ),
                name="log_lot_owner_choice",
            ),
            models.CheckConstraint(
                condition=Q(
                    lifecycle__in=("active", "exhausted", "returned", "disposed")
                ),
                name="log_lot_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("catalog_code"),
                name="log_lot_org_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(initial_quantity__gt=0),
                name="log_lot_initial_qty_pos",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_lot_version_pos",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.catalog_code = self.catalog_code.lower()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_allocation_id:
            edition_allocation = self.edition_allocation
            if (
                edition_allocation is None
                or edition_allocation.organization_id != self.organization_id
            ):
                raise ValidationError(
                    "A stock allocation must remain in one organization.",
                    code="logistics_lot_scope_mismatch",
                )


class PhysicalKey(_ClosedLogisticsModel):
    """A tracked physical key; keyholder responsibility grants no software access."""

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        LOST = "lost", "Lost"
        RETURNED = "returned", "Returned"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="physical_keys",
    )
    edition_allocation = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="physical_keys",
    )
    code = models.SlugField(max_length=96, validators=(validate_lowercase_slug,))
    label = models.CharField(max_length=200)
    opens_node = models.ForeignKey(
        LogisticsNode,
        on_delete=models.PROTECT,
        related_name="physical_keys",
    )
    provider = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="physical_keys",
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="physical_keys_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "code", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "lost", "returned", "retired")),
                name="log_key_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("code"),
                name="log_key_org_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_key_version_pos",
            ),
        ]

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
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.opens_node_id
            and self.opens_node.organization_id != self.organization_id
        ):
            raise ValidationError(
                "The physical key and lock must remain in one organization.",
                code="logistics_key_scope_mismatch",
            )
        if self.provider_id:
            provider = self.provider
            if provider is None or provider.organization_id != self.organization_id:
                raise ValidationError(
                    "The key provider must remain in one organization.",
                    code="logistics_key_scope_mismatch",
                )


class KeyholderResponsibility(_AppendOnlyLogisticsModel):
    """Store keyholder responsibility records."""

    key = models.ForeignKey(
        PhysicalKey,
        on_delete=models.PROTECT,
        related_name="responsibilities",
    )
    responsible_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="physical_key_responsibilities",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="physical_key_responsibilities_assigned",
    )
    reason = models.TextField(max_length=MAX_LOGISTICS_REASON_LENGTH)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("key_id", "starts_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="log_keyholder_interval",
            ),
            ExclusionConstraint(
                name="log_keyholder_no_overlap",
                expressions=(
                    ("key", RangeOperators.EQUAL),
                    (_half_open_interval(), RangeOperators.OVERLAPS),
                ),
            ),
        ]


class AssetAgreement(_ClosedLogisticsModel):
    """Store asset agreement records."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        LOAN = "loan", "Loan"
        RENTAL = "rental", "Rental"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_agreements",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_agreements",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    stock_lot = models.ForeignKey(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    physical_key = models.ForeignKey(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    offer_acceptance = models.OneToOneField(
        EquipmentOfferAcceptance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="agreement",
    )
    provider = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="provided_agreements",
    )
    provider_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="provided_logistics_agreements",
    )
    borrower_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="borrowed_logistics_agreements",
    )
    borrower_party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="borrowed_agreements",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    return_due_at = models.DateTimeField()
    return_address = models.ForeignKey(
        RestrictedLogisticsAddress,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="return_agreements",
    )
    provider_reference = models.CharField(max_length=240, blank=True)
    terms_reference = models.CharField(max_length=1_000, blank=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_agreements_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "return_due_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("loan", "rental")),
                name="log_agreement_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="log_agreement_interval",
            ),
            models.CheckConstraint(
                condition=Q(return_due_at__gte=F("starts_at")),
                name="log_agreement_return_due",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_agreement_version_pos",
            ),
            *(
                ExclusionConstraint(
                    name=constraint_name,
                    expressions=(
                        (field_name, RangeOperators.EQUAL),
                        (_half_open_interval(), RangeOperators.OVERLAPS),
                    ),
                    condition=Q(**{f"{field_name}__isnull": False}),
                )
                for field_name, constraint_name in (
                    ("asset", "log_agree_asset_no_overlap"),
                    ("stock_lot", "log_agree_lot_no_overlap"),
                    ("physical_key", "log_agree_key_no_overlap"),
                    ("node", "log_agree_node_no_overlap"),
                )
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
        subjects = [
            self.asset_id,
            self.stock_lot_id,
            self.physical_key_id,
            self.node_id,
        ]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "An agreement must name exactly one tracked subject.",
                code="logistics_agreement_subject_mismatch",
            )
        if self.provider_account_id and self.provider_id:
            raise ValidationError(
                "An agreement has one provider.",
                code="logistics_agreement_provider_mismatch",
            )
        if self.provider_account_id is None and self.provider_id is None:
            raise ValidationError(
                "An agreement must name its provider.",
                code="logistics_agreement_provider_mismatch",
            )
        if self.borrower_account_id and self.borrower_party_id:
            raise ValidationError(
                (
                    "An agreement has at most one external borrower; blank means "
                    "organizer."
                ),
                code="logistics_agreement_borrower_mismatch",
            )
        if self.provider_id:
            provider = self.provider
            if provider is None or provider.organization_id != self.organization_id:
                raise ValidationError(
                    "The agreement provider must remain in one organization.",
                    code="logistics_agreement_scope_mismatch",
                )
        if self.borrower_party_id:
            borrower_party = self.borrower_party
            if (
                borrower_party is None
                or borrower_party.organization_id != self.organization_id
            ):
                raise ValidationError(
                    "The agreement borrower must remain in one organization.",
                    code="logistics_agreement_scope_mismatch",
                )
        if self.return_address_id:
            return_address = self.return_address
            if return_address is None or (
                return_address.organization_id != self.organization_id
                or return_address.purpose != RestrictedLogisticsAddress.Purpose.RETURN
            ):
                raise ValidationError(
                    "The agreement requires a purpose-bound return address.",
                    code="logistics_agreement_address_mismatch",
                )


class ReusableKit(_ClosedLogisticsModel):
    """Store reusable kit records."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_kits",
    )
    code = models.SlugField(max_length=96, validators=(validate_lowercase_slug,))
    name = models.CharField(max_length=200)
    description = models.TextField(max_length=2_000, blank=True)
    declared_line_count = models.PositiveIntegerField()
    lifecycle = models.CharField(
        max_length=16,
        choices=LogisticsParty.Lifecycle,
        default=LogisticsParty.Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_kits_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "code", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "retired")),
                name="log_kit_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("code"),
                name="log_kit_org_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_kit_version_pos",
            ),
            models.CheckConstraint(
                condition=Q(declared_line_count__gt=0)
                & Q(declared_line_count__lte=200),
                name="log_kit_line_count_bound",
            ),
        ]

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
        super().save(*args, **kwargs)


class ReusableKitLine(_AppendOnlyLogisticsModel):
    """Store reusable kit line records."""

    kit = models.ForeignKey(
        ReusableKit,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="kit_lines",
    )
    stock_lot = models.ForeignKey(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="kit_lines",
    )
    physical_key = models.ForeignKey(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="kit_lines",
    )
    quantity = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("kit_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("kit", "asset"),
                condition=Q(asset__isnull=False),
                name="log_kit_asset_line_uq",
            ),
            models.UniqueConstraint(
                fields=("kit", "stock_lot"),
                condition=Q(stock_lot__isnull=False),
                name="log_kit_lot_line_uq",
            ),
            models.UniqueConstraint(
                fields=("kit", "physical_key"),
                condition=Q(physical_key__isnull=False),
                name="log_kit_key_line_uq",
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
        subjects = [self.asset_id, self.stock_lot_id, self.physical_key_id]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "A kit line must name exactly one tracked item.",
                code="logistics_kit_line_subject_mismatch",
            )
        if (self.asset_id or self.physical_key_id) and self.quantity != 1:
            raise ValidationError(
                "Serialized kit items always have quantity one.",
                code="logistics_kit_line_quantity_mismatch",
            )


class LogisticsManifest(_ClosedLogisticsModel):
    """Store logistics manifest records."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"
        TRANSFER = "transfer", "Transfer"
        RETURN = "return", "Return"
        STAGE_RECEIVING = "stage_receiving", "Stage Tech receiving"

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        DRAFT = "draft", "Draft"
        SEALED = "sealed", "Sealed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_manifests",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="logistics_manifests",
    )
    responsible_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="logistics_manifests",
    )
    manifest_number = models.CharField(max_length=96)
    kind = models.CharField(max_length=24, choices=Kind)
    title = models.CharField(max_length=200)
    line_count = models.PositiveIntegerField()
    source_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outbound_manifests",
    )
    destination_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inbound_manifests",
    )
    vehicle = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vehicle_manifests",
    )
    provider = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manifests",
    )
    loading_starts_at = models.DateTimeField(null=True, blank=True)
    loading_ends_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.DRAFT,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_manifests_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_manifests_modified",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "manifest_number", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    kind__in=(
                        "inbound",
                        "outbound",
                        "transfer",
                        "return",
                        "stage_receiving",
                    )
                ),
                name="log_manifest_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("draft", "sealed", "completed", "cancelled")),
                name="log_manifest_status_choice",
            ),
            models.UniqueConstraint(
                fields=("edition", "manifest_number"),
                name="log_manifest_number_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_manifest_version_pos",
            ),
            models.CheckConstraint(
                condition=Q(line_count__gt=0) & Q(line_count__lte=500),
                name="log_manifest_line_count_bound",
            ),
            models.CheckConstraint(
                condition=Q(
                    loading_starts_at__isnull=True, loading_ends_at__isnull=True
                )
                | Q(
                    loading_starts_at__isnull=False,
                    loading_ends_at__gt=F("loading_starts_at"),
                ),
                name="log_manifest_loading_window",
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
            raise ValidationError(
                "The manifest must remain in its edition organization.",
                code="logistics_manifest_scope_mismatch",
            )
        if self.responsible_department_id and (
            self.responsible_department.organization_id != self.organization_id
            or self.responsible_department.edition_id != self.edition_id
        ):
            raise ValidationError(
                "The manifest Department must belong to its edition.",
                code="logistics_manifest_scope_mismatch",
            )
        for node in (self.source_node, self.destination_node, self.vehicle):
            if node is not None and node.organization_id != self.organization_id:
                raise ValidationError(
                    "Manifest nodes must remain in one organization.",
                    code="logistics_manifest_scope_mismatch",
                )
        if self.vehicle_id:
            vehicle = self.vehicle
            if vehicle is None or vehicle.kind != LogisticsNode.Kind.VEHICLE:
                raise ValidationError(
                    "The manifest vehicle must be a tracked vehicle node.",
                    code="logistics_manifest_vehicle_mismatch",
                )
        if self.provider_id:
            provider = self.provider
            if provider is None or provider.organization_id != self.organization_id:
                raise ValidationError(
                    "The manifest provider must remain in one organization.",
                    code="logistics_manifest_scope_mismatch",
                )


class LogisticsManifestLine(_AppendOnlyLogisticsModel):
    """Store logistics manifest line records."""

    class SubjectKind(models.TextChoices):
        """Enumerate supported subject kind values."""

        NODE = "node", "Node"
        ASSET = "asset", "Asset"
        STOCK_LOT = "stock_lot", "Stock lot"
        KEY = "key", "Physical key"

    manifest = models.ForeignKey(
        LogisticsManifest,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    subject_kind = models.CharField(max_length=16, choices=SubjectKind)
    node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manifest_lines",
    )
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manifest_lines",
    )
    stock_lot = models.ForeignKey(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manifest_lines",
    )
    physical_key = models.ForeignKey(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manifest_lines",
    )
    packed_in_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="packed_manifest_lines",
    )
    quantity = models.PositiveIntegerField(default=1)
    label_snapshot = models.CharField(max_length=200)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("manifest_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(subject_kind__in=("node", "asset", "stock_lot", "key")),
                name="log_manifest_subject_choice",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="log_manifest_line_qty_pos",
            ),
            models.UniqueConstraint(
                fields=("manifest", "node"),
                condition=Q(node__isnull=False),
                name="log_manifest_node_line_uq",
            ),
            models.UniqueConstraint(
                fields=("manifest", "asset"),
                condition=Q(asset__isnull=False),
                name="log_manifest_asset_line_uq",
            ),
            models.UniqueConstraint(
                fields=("manifest", "stock_lot"),
                condition=Q(stock_lot__isnull=False),
                name="log_manifest_lot_line_uq",
            ),
            models.UniqueConstraint(
                fields=("manifest", "physical_key"),
                condition=Q(physical_key__isnull=False),
                name="log_manifest_key_line_uq",
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
        subjects = [
            self.node_id,
            self.asset_id,
            self.stock_lot_id,
            self.physical_key_id,
        ]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "A manifest line must name exactly one tracked subject.",
                code="logistics_manifest_line_subject_mismatch",
            )
        expected = {
            self.SubjectKind.NODE.value: self.node_id,
            self.SubjectKind.ASSET.value: self.asset_id,
            self.SubjectKind.STOCK_LOT.value: self.stock_lot_id,
            self.SubjectKind.KEY.value: self.physical_key_id,
        }.get(self.subject_kind)
        if expected is None:
            raise ValidationError(
                "The manifest subject kind must match its item.",
                code="logistics_manifest_line_subject_mismatch",
            )
        if self.subject_kind != self.SubjectKind.STOCK_LOT and self.quantity != 1:
            raise ValidationError(
                "Serialized manifest items always have quantity one.",
                code="logistics_manifest_line_quantity_mismatch",
            )
        if self.packed_in_node_id:
            packed_in_node = self.packed_in_node
            if packed_in_node is None or packed_in_node.kind not in {
                LogisticsNode.Kind.BOX.value,
                LogisticsNode.Kind.CONTAINER.value,
                LogisticsNode.Kind.VEHICLE.value,
            }:
                raise ValidationError(
                    (
                        "Manifest contents may be packed only into a box, container, "
                        "or vehicle."
                    ),
                    code="logistics_manifest_pack_target_mismatch",
                )


class LogisticsLabel(_ClosedLogisticsModel):
    """Store logistics label records."""

    class Lifecycle(models.TextChoices):
        """Enumerate supported lifecycle values."""

        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_labels",
    )
    label_code = models.CharField(max_length=96)
    qr_identifier_digest = models.CharField(
        max_length=64,
        validators=(_SHA256_VALIDATOR,),
    )
    node = models.OneToOneField(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="label",
    )
    asset = models.OneToOneField(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="label",
    )
    stock_lot = models.OneToOneField(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="label",
    )
    physical_key = models.OneToOneField(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_label",
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.ACTIVE,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_labels_created",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "label_code", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(lifecycle__in=("active", "revoked")),
                name="log_label_lifecycle_choice",
            ),
            models.UniqueConstraint(
                F("organization"),
                Lower("label_code"),
                name="log_label_org_code_uq",
            ),
            models.UniqueConstraint(
                fields=("organization", "qr_identifier_digest"),
                name="log_label_qr_digest_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_label_version_pos",
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
        subjects = [
            self.node_id,
            self.asset_id,
            self.stock_lot_id,
            self.physical_key_id,
        ]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "A label must identify exactly one tracked subject.",
                code="logistics_label_subject_mismatch",
            )


class LogisticsEvent(_AppendOnlyLogisticsModel):
    """Canonical append-only source for current location, custody, and condition."""

    class EventType(models.TextChoices):
        """Enumerate supported event type values."""

        RECEIVE = "receive", "Receive"
        PACK = "pack", "Pack"
        UNPACK = "unpack", "Unpack"
        MOVE = "move", "Move"
        LOAD = "load", "Load"
        UNLOAD = "unload", "Unload"
        HANDOVER = "handover", "Handover"
        COUNT = "count", "Count"
        CONDITION = "condition", "Condition"
        DAMAGE = "damage", "Damage"
        RETURN = "return", "Return"

    class SubjectKind(models.TextChoices):
        """Enumerate supported subject kind values."""

        NODE = "node", "Node"
        ASSET = "asset", "Asset"
        STOCK_LOT = "stock_lot", "Stock lot"
        KEY = "key", "Physical key"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    subject_kind = models.CharField(max_length=16, choices=SubjectKind)
    node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    stock_lot = models.ForeignKey(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    physical_key = models.ForeignKey(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_events",
    )
    event_type = models.CharField(max_length=16, choices=EventType)
    event_sequence = models.PositiveBigIntegerField()
    source_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_departures",
    )
    destination_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_arrivals",
    )
    from_custodian_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_custody_released",
    )
    to_custodian_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_custody_received",
    )
    from_custodian_party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_custody_released",
    )
    to_custodian_party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_custody_received",
    )
    quantity = models.PositiveIntegerField(null=True, blank=True)
    condition_before = models.CharField(max_length=120, blank=True)
    condition_after = models.CharField(max_length=120, blank=True)
    manifest = models.ForeignKey(
        LogisticsManifest,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_events_recorded",
    )
    occurred_at = models.DateTimeField()
    reason = models.TextField(max_length=MAX_LOGISTICS_REASON_LENGTH)
    evidence_reference = models.CharField(max_length=1_000, blank=True)
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "occurred_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    event_type__in=(
                        "receive",
                        "pack",
                        "unpack",
                        "move",
                        "load",
                        "unload",
                        "handover",
                        "count",
                        "condition",
                        "damage",
                        "return",
                    )
                ),
                name="log_event_type_choice",
            ),
            models.CheckConstraint(
                condition=Q(subject_kind__in=("node", "asset", "stock_lot", "key")),
                name="log_event_subject_choice",
            ),
            models.CheckConstraint(
                condition=Q(event_sequence__gt=0),
                name="log_event_sequence_pos",
            ),
            models.UniqueConstraint(
                fields=("asset", "event_sequence"),
                condition=Q(asset__isnull=False),
                name="log_asset_event_seq_uq",
            ),
            models.UniqueConstraint(
                fields=("stock_lot", "event_sequence"),
                condition=Q(stock_lot__isnull=False),
                name="log_lot_event_seq_uq",
            ),
            models.UniqueConstraint(
                fields=("physical_key", "event_sequence"),
                condition=Q(physical_key__isnull=False),
                name="log_key_event_seq_uq",
            ),
            models.UniqueConstraint(
                fields=("node", "event_sequence"),
                condition=Q(node__isnull=False),
                name="log_node_event_seq_uq",
            ),
            models.UniqueConstraint(
                fields=("manifest", "evidence_reference", "event_type"),
                condition=Q(manifest__isnull=False),
                name="log_manifest_event_line_type_uq",
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
        subjects = [
            self.node_id,
            self.asset_id,
            self.stock_lot_id,
            self.physical_key_id,
        ]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "A logistics event must name exactly one tracked subject.",
                code="logistics_event_subject_mismatch",
            )
        expected = {
            self.SubjectKind.NODE.value: self.node_id,
            self.SubjectKind.ASSET.value: self.asset_id,
            self.SubjectKind.STOCK_LOT.value: self.stock_lot_id,
            self.SubjectKind.KEY.value: self.physical_key_id,
        }.get(self.subject_kind)
        if expected is None:
            raise ValidationError(
                "The event subject kind must match its tracked subject.",
                code="logistics_event_subject_mismatch",
            )
        if self.from_custodian_account_id and self.from_custodian_party_id:
            raise ValidationError(
                "An event has at most one source custodian.",
                code="logistics_event_custody_mismatch",
            )
        if self.to_custodian_account_id and self.to_custodian_party_id:
            raise ValidationError(
                "An event has at most one destination custodian.",
                code="logistics_event_custody_mismatch",
            )
        if self.subject_kind == self.SubjectKind.STOCK_LOT:
            if self.quantity is None:
                raise ValidationError(
                    "Stock events require an observed quantity.",
                    code="logistics_event_quantity_required",
                )
        elif self.quantity not in {None, 1}:
            raise ValidationError(
                "Serialized events may only use quantity one.",
                code="logistics_event_quantity_mismatch",
            )


class LogisticsCurrentState(_ClosedLogisticsModel):
    """Materialized projection changed only while appending its source event."""

    class State(models.TextChoices):
        """Enumerate supported state values."""

        RECEIVED = "received", "Received"
        STORED = "stored", "Stored"
        IN_TRANSIT = "in_transit", "In transit"
        ISSUED = "issued", "Issued"
        RETURNED = "returned", "Returned"
        LOST = "lost", "Lost"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_current_states",
    )
    node = models.OneToOneField(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_state",
    )
    asset = models.OneToOneField(
        Asset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_state",
    )
    stock_lot = models.OneToOneField(
        StockLot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_state",
    )
    physical_key = models.OneToOneField(
        PhysicalKey,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_state",
    )
    current_node = models.ForeignKey(
        LogisticsNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contained_current_states",
    )
    custodian_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_current_custody",
    )
    custodian_party = models.ForeignKey(
        LogisticsParty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_current_custody",
    )
    quantity_on_hand = models.PositiveIntegerField(null=True, blank=True)
    condition = models.CharField(max_length=120)
    state = models.CharField(max_length=16, choices=State)
    event_sequence = models.PositiveBigIntegerField()
    last_event = models.OneToOneField(
        LogisticsEvent,
        on_delete=models.PROTECT,
        related_name="resulting_state",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    state__in=(
                        "received",
                        "stored",
                        "in_transit",
                        "issued",
                        "returned",
                        "lost",
                    )
                ),
                name="log_state_choice",
            ),
            models.CheckConstraint(
                condition=Q(event_sequence__gt=0),
                name="log_state_event_seq_pos",
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
        subjects = [
            self.node_id,
            self.asset_id,
            self.stock_lot_id,
            self.physical_key_id,
        ]
        if sum(value is not None for value in subjects) != 1:
            raise ValidationError(
                "A current-state row must name exactly one tracked subject.",
                code="logistics_state_subject_mismatch",
            )
        if self.custodian_account_id and self.custodian_party_id:
            raise ValidationError(
                "A tracked subject has at most one current custodian.",
                code="logistics_state_custody_mismatch",
            )
        if self.stock_lot_id and self.quantity_on_hand is None:
            raise ValidationError(
                "A stock-lot projection requires its current quantity.",
                code="logistics_state_quantity_required",
            )
        if not self.stock_lot_id and self.quantity_on_hand is not None:
            raise ValidationError(
                "Only stock lots carry a projected quantity.",
                code="logistics_state_quantity_mismatch",
            )
        if self.current_node_id:
            current_node = self.current_node
            if (
                current_node is None
                or current_node.organization_id != self.organization_id
            ):
                raise ValidationError(
                    "Containment must remain in one organization.",
                    code="logistics_containment_scope_mismatch",
                )


class LogisticsDiscrepancy(_ClosedLogisticsModel):
    """Store logistics discrepancy records."""

    class Kind(models.TextChoices):
        """Enumerate supported kind values."""

        MISSING = "missing", "Missing"
        UNEXPECTED = "unexpected", "Unexpected"
        COUNT = "count", "Count mismatch"
        CONDITION = "condition", "Condition mismatch"
        DAMAGE = "damage", "Damage"
        OFFLINE_CONFLICT = "offline_conflict", "Offline conflict"
        RETURN_OVERDUE = "return_overdue", "Return overdue"

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_discrepancies",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_discrepancies",
    )
    kind = models.CharField(max_length=24, choices=Kind)
    subject_kind = models.CharField(max_length=16, choices=LogisticsEvent.SubjectKind)
    subject_id = models.UUIDField()
    expected_quantity = models.PositiveIntegerField(null=True, blank=True)
    observed_quantity = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(max_length=2_000)
    detected_event = models.ForeignKey(
        LogisticsEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="detected_discrepancies",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.OPEN,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_discrepancies_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.TextField(
        max_length=MAX_LOGISTICS_REASON_LENGTH,
        blank=True,
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("organization_id", "status", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    kind__in=(
                        "missing",
                        "unexpected",
                        "count",
                        "condition",
                        "damage",
                        "offline_conflict",
                        "return_overdue",
                    )
                ),
                name="log_discrepancy_kind_choice",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("open", "resolved")),
                name="log_discrepancy_status_choice",
            ),
            models.CheckConstraint(
                condition=Q(subject_kind__in=("node", "asset", "stock_lot", "key")),
                name="log_discrepancy_subject_choice",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_discrepancy_version_pos",
            ),
            models.UniqueConstraint(
                fields=("detected_event",),
                condition=Q(detected_event__isnull=False),
                name="log_discrepancy_event_uq",
            ),
        ]


class LogisticsEditionControl(_ClosedLogisticsModel):
    """Store logistics edition control records."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_edition_controls",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="logistics_control",
    )
    aggregate_version = models.PositiveBigIntegerField(default=0, editable=False)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id",)

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "The logistics control must remain in its edition organization.",
                code="logistics_control_scope_mismatch",
            )


class OfflineScanBatch(_ClosedLogisticsModel):
    """Store offline scan batch records."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        PENDING = "pending", "Pending"
        APPLIED = "applied", "Applied"
        REVIEW = "review", "Needs review"
        REJECTED = "rejected", "Rejected"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_offline_batches",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="logistics_offline_batches",
    )
    device_code = models.CharField(max_length=96)
    snapshot_version = models.PositiveBigIntegerField()
    policy_version = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    operation_count = models.PositiveIntegerField()
    payload_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PENDING,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_offline_batches_submitted",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=("pending", "applied", "review", "rejected")),
                name="log_offline_status_choice",
            ),
            models.CheckConstraint(
                condition=Q(operation_count__gt=0)
                & Q(operation_count__lte=MAX_OFFLINE_OPERATIONS),
                name="log_offline_operation_bound",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="log_offline_version_pos",
            ),
        ]


class OfflineScanOperation(_AppendOnlyLogisticsModel):
    """Store offline scan operation records."""

    class Result(models.TextChoices):
        """Enumerate supported result values."""

        APPLIED = "applied", "Applied"
        DUPLICATE = "duplicate", "Duplicate"
        SUPERSEDED = "superseded", "Superseded"
        REJECTED = "rejected", "Rejected"
        REVIEW = "review", "Needs review"

    batch = models.ForeignKey(
        OfflineScanBatch,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    sequence = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    expected_subject_sequence = models.PositiveBigIntegerField()
    action = models.CharField(max_length=16, choices=LogisticsEvent.EventType)
    label_code = models.CharField(max_length=96)
    source_label_code = models.CharField(max_length=96, blank=True)
    destination_label_code = models.CharField(max_length=96, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    observed_condition = models.CharField(max_length=120, blank=True)
    occurred_at = models.DateTimeField()
    operation_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    result = models.CharField(max_length=16, choices=Result)
    reason_code = models.CharField(max_length=80)
    applied_event = models.ForeignKey(
        LogisticsEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offline_operations",
    )
    discrepancy = models.ForeignKey(
        LogisticsDiscrepancy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offline_operations",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("batch_id", "sequence", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=LogisticsEvent.EventType.values),
                name="log_offline_action_choice",
            ),
            models.CheckConstraint(
                condition=Q(
                    result__in=(
                        "applied",
                        "duplicate",
                        "superseded",
                        "rejected",
                        "review",
                    )
                ),
                name="log_offline_result_choice",
            ),
            models.UniqueConstraint(
                fields=("batch", "sequence"),
                name="log_offline_batch_seq_uq",
            ),
            models.UniqueConstraint(
                fields=("batch", "idempotency_key"),
                name="log_offline_batch_key_uq",
            ),
            models.UniqueConstraint(
                fields=("applied_event",),
                condition=Q(
                    applied_event__isnull=False,
                    result__in=("applied", "review"),
                ),
                name="log_offline_event_nondup_uq",
            ),
            models.UniqueConstraint(
                fields=("discrepancy",),
                condition=Q(
                    discrepancy__isnull=False,
                    result__in=("applied", "review"),
                ),
                name="log_offline_discrepancy_nondup_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="log_offline_sequence_pos",
            ),
        ]


class OfflineOperationReceipt(_AppendOnlyLogisticsModel):
    """Store offline operation receipt records."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_offline_operation_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="logistics_offline_operation_receipts",
    )
    idempotency_key = models.UUIDField(unique=True)
    operation_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    result = models.CharField(max_length=16, choices=OfflineScanOperation.Result)
    reason_code = models.CharField(max_length=80)
    applied_event = models.ForeignKey(
        LogisticsEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offline_receipts",
    )
    discrepancy = models.ForeignKey(
        LogisticsDiscrepancy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offline_receipts",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    result__in=(
                        "applied",
                        "duplicate",
                        "superseded",
                        "rejected",
                        "review",
                    )
                ),
                name="log_offline_receipt_choice",
            )
        ]


class LogisticsCommandReceipt(_AppendOnlyLogisticsModel):
    """Store logistics command receipt records."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="logistics_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_command_receipts",
    )
    operation = models.CharField(max_length=80)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logistics_command_receipts",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    resulting_version = models.PositiveBigIntegerField()
    result_object_id = models.UUIDField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "operation", "idempotency_key"),
                name="log_command_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0),
                name="log_receipt_version_pos",
            ),
        ]
