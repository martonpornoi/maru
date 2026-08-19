"""Catalog persistence, intentionally separate from admission products."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug


class ProtectedCatalogModel(UUIDTimeStampedModel):
    class Meta:
        abstract = True

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Catalog records require a governed lifecycle command.",
            code="protected_catalog_record",
        )


class AppendOnlyCatalogModel(ProtectedCatalogModel):
    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Catalog evidence is append-only.",
                code="immutable_catalog_evidence",
            )
        self.full_clean()
        super().save(*args, **kwargs)


class EditionCatalog(ProtectedCatalogModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="edition_catalogs",
    )
    edition = models.OneToOneField(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="commerce_catalog",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    currency = models.CharField(max_length=3)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="edition_catalogs_created",
    )

    class Meta:
        ordering = ("organization_id", "edition_id")
        constraints = [
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="catalog_version_positive",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.currency = self.currency.upper()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                "Catalog edition and organization must match.",
                code="catalog_scope_mismatch",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogProduct(ProtectedCatalogModel):
    class Kind(models.TextChoices):
        MERCHANDISE = "merchandise", "Convention merchandise"
        DONATION = "donation", "Donation"
        SUPPORTER = "supporter", "Limited supporter product"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    class Beneficiary(models.TextChoices):
        CONVENTION = "convention", "Convention"
        CHARITY = "charity", "Charity"

    class Fulfilment(models.TextChoices):
        NONE = "none", "No fulfilment"
        PICKUP = "pickup", "On-site pickup"
        SHIPPING = "shipping", "Shipping"

    catalog = models.ForeignKey(
        EditionCatalog,
        on_delete=models.PROTECT,
        related_name="products",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    kind = models.CharField(max_length=20, choices=Kind)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    name = models.CharField(max_length=160)
    description = models.TextField(max_length=2_000, blank=True)
    beneficiary = models.CharField(
        max_length=16,
        choices=Beneficiary,
        default=Beneficiary.CONVENTION,
    )
    charity_selection = models.ForeignKey(
        "charities.CharitySelection",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="catalog_products",
    )
    sale_opens_at = models.DateTimeField(null=True, blank=True)
    sale_closes_at = models.DateTimeField(null=True, blank=True)
    preorder_allowed = models.BooleanField(default=False)
    fulfilment_mode = models.CharField(
        max_length=16,
        choices=Fulfilment,
        default=Fulfilment.PICKUP,
    )
    per_order_limit = models.PositiveSmallIntegerField(
        default=10,
        validators=(MinValueValidator(1),),
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("catalog", "code"), name="catalog_product_code_unique"
            ),
            models.CheckConstraint(
                condition=Q(per_order_limit__gt=0),
                name="catalog_product_order_limit_pos",
            ),
            models.CheckConstraint(
                condition=(
                    Q(sale_opens_at__isnull=True)
                    | Q(sale_closes_at__isnull=True)
                    | Q(sale_closes_at__gt=models.F("sale_opens_at"))
                ),
                name="catalog_product_sale_window_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(beneficiary="charity", charity_selection__isnull=False)
                    | Q(beneficiary="convention", charity_selection__isnull=True)
                ),
                name="catalog_product_beneficiary_shape",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.code = self.code.lower()
        if self.kind == self.Kind.DONATION and (
            self.fulfilment_mode != self.Fulfilment.NONE or self.preorder_allowed
        ):
            raise ValidationError("Donations cannot require fulfilment or preorder.")
        if self.kind == self.Kind.SUPPORTER and self.preorder_allowed:
            raise ValidationError("Limited supporter products cannot oversell.")
        selection = self.charity_selection
        if selection is not None and (
            selection.organization_id != self.catalog.organization_id
            or selection.edition_id != self.catalog.edition_id
            or selection.status != selection.Status.CONFIRMED
        ):
            raise ValidationError(
                {"charity_selection": "Use a confirmed charity in this edition."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogVariant(ProtectedCatalogModel):
    product = models.ForeignKey(
        CatalogProduct, on_delete=models.PROTECT, related_name="variants"
    )
    sku = models.CharField(max_length=80)
    name = models.CharField(max_length=120)
    price_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    initial_stock = models.PositiveIntegerField(null=True, blank=True)
    stock_ceiling = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "sku"), name="catalog_variant_sku_unique"
            ),
            models.CheckConstraint(
                condition=(
                    Q(initial_stock__isnull=True, stock_ceiling__isnull=True)
                    | Q(
                        initial_stock__isnull=False,
                        stock_ceiling__isnull=False,
                        stock_ceiling__gte=models.F("initial_stock"),
                    )
                ),
                name="catalog_variant_stock_shape",
            ),
        ]

    @property
    def is_stock_limited(self) -> bool:
        return self.initial_stock is not None

    def clean(self) -> None:
        super().clean()
        self.currency = self.currency.upper()
        if self.currency != self.product.catalog.currency:
            raise ValidationError("Variant currency must match its catalog.")
        if self.product.kind == CatalogProduct.Kind.DONATION and (
            self.initial_stock is not None or self.stock_ceiling is not None
        ):
            raise ValidationError("Donation price options cannot have stock.")
        if self.product.kind == CatalogProduct.Kind.SUPPORTER and (
            self.initial_stock is None or self.stock_ceiling is None
        ):
            raise ValidationError("Limited supporter variants require finite stock.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogOrder(ProtectedCatalogModel):
    class Status(models.TextChoices):
        PAYMENT_PENDING = "payment_pending", "Payment pending"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        REFUNDED = "refunded", "Refunded"

    catalog = models.ForeignKey(
        EditionCatalog, on_delete=models.PROTECT, related_name="orders"
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="catalog_orders",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="catalog_orders",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalog_orders",
    )
    reference = models.CharField(max_length=24)
    status = models.CharField(max_length=20, choices=Status)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    currency = models.CharField(max_length=3)
    total_minor = models.PositiveBigIntegerField()
    payment_due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    fulfilment_status = models.CharField(max_length=24, default="not_started")

    class Meta:
        ordering = ("-created_at", "reference")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "reference"),
                name="catalog_order_reference_unique",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_version__gt=0),
                name="catalog_order_version_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status", "created_at"),
                name="catalog_order_scope_state_idx",
            ),
            models.Index(
                fields=("account", "edition", "created_at"),
                name="catalog_order_owner_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.catalog_id and (
            self.catalog.organization_id != self.organization_id
            or self.catalog.edition_id != self.edition_id
        ):
            raise ValidationError("Order scope must match its edition catalog.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogOrderLine(ProtectedCatalogModel):
    order = models.ForeignKey(
        CatalogOrder, on_delete=models.PROTECT, related_name="lines"
    )
    product = models.ForeignKey(
        CatalogProduct, on_delete=models.PROTECT, related_name="order_lines"
    )
    variant = models.ForeignKey(
        CatalogVariant, on_delete=models.PROTECT, related_name="order_lines"
    )
    product_kind_snapshot = models.CharField(max_length=20)
    product_name_snapshot = models.CharField(max_length=160)
    variant_name_snapshot = models.CharField(max_length=120)
    sku_snapshot = models.CharField(max_length=80)
    quantity = models.PositiveIntegerField()
    unit_price_minor = models.PositiveBigIntegerField()
    line_total_minor = models.PositiveBigIntegerField()
    beneficiary_snapshot = models.CharField(max_length=16)
    charity_selection_id_snapshot = models.UUIDField(null=True, blank=True)
    fulfilment_mode_snapshot = models.CharField(max_length=16)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="catalog_order_line_quantity_pos",
            ),
            models.UniqueConstraint(
                fields=("order", "variant"),
                name="catalog_order_variant_once",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError("Order-line variant and product must match.")
        if self.order_id and self.product.catalog_id != self.order.catalog_id:
            raise ValidationError("Order line must remain inside its catalog.")
        if self.line_total_minor != self.unit_price_minor * self.quantity:
            raise ValidationError("Order-line total does not match its snapshot.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Order lines are immutable snapshots.")
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogStockAdjustment(AppendOnlyCatalogModel):
    catalog = models.ForeignKey(
        EditionCatalog,
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )
    variant = models.ForeignKey(
        CatalogVariant,
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )
    previous_stock = models.PositiveIntegerField()
    new_stock = models.PositiveIntegerField()
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalog_stock_adjustments",
    )
    control_version = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()

    class Meta:
        ordering = ("catalog_id", "control_version")
        constraints = [
            models.UniqueConstraint(
                fields=("catalog", "control_version"),
                name="catalog_stock_control_version_uq",
            ),
            models.CheckConstraint(
                condition=~Q(reason=""), name="catalog_stock_reason_nonblank"
            ),
        ]


class CatalogPaymentIntent(ProtectedCatalogModel):
    class Provider(models.TextChoices):
        HOSTED = "hosted", "Hosted payment"
        DEMO = "demo", "Deterministic demo payment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(
        CatalogOrder, on_delete=models.PROTECT, related_name="payment_intents"
    )
    provider = models.CharField(max_length=16, choices=Provider)
    provider_reference = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    checkout_url = models.URLField(blank=True)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    succeeded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "id")

    def clean(self) -> None:
        super().clean()
        if self.order_id and (
            self.amount_minor != self.order.total_minor
            or self.currency != self.order.currency
        ):
            raise ValidationError("Payment intent must equal its order balance.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogPaymentEvent(AppendOnlyCatalogModel):
    intent = models.ForeignKey(
        CatalogPaymentIntent,
        on_delete=models.PROTECT,
        related_name="provider_events",
    )
    provider = models.CharField(max_length=16)
    provider_event_id = models.CharField(max_length=160)
    result = models.CharField(max_length=16)
    occurred_at = models.DateTimeField()
    correlation_id = models.UUIDField()

    class Meta:
        ordering = ("occurred_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "provider_event_id"),
                name="catalog_payment_provider_event_uq",
            ),
        ]


class CatalogOrderTimelineEntry(AppendOnlyCatalogModel):
    order = models.ForeignKey(
        CatalogOrder, on_delete=models.PROTECT, related_name="timeline_entries"
    )
    kind = models.CharField(max_length=32)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="catalog_order_timeline_entries",
    )
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("occurred_at", "id")


class CatalogCommandReceipt(AppendOnlyCatalogModel):
    class Operation(models.TextChoices):
        CATALOG_CREATED = "catalog_created", "Catalog created"
        PRODUCT_ADDED = "product_added", "Product added"
        VARIANT_ADDED = "variant_added", "Variant added"
        CATALOG_ACTIVATED = "catalog_activated", "Catalog activated"
        STOCK_ADJUSTED = "stock_adjusted", "Stock adjusted"
        ORDER_PLACED = "order_placed", "Order placed"
        PAYMENT_CREATED = "payment_created", "Payment created"
        PAYMENT_RECONCILED = "payment_reconciled", "Payment reconciled"

    catalog = models.ForeignKey(
        EditionCatalog,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalog_command_receipts",
    )
    operation = models.CharField(max_length=32, choices=Operation)
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    resulting_version = models.PositiveBigIntegerField()
    result_id = models.UUIDField()
    reason = models.CharField(max_length=500, blank=True)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        ordering = ("catalog_id", "resulting_version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("catalog", "actor", "idempotency_key"),
                name="catalog_command_idempotency_uq",
            ),
            models.UniqueConstraint(
                fields=("catalog", "resulting_version"),
                name="catalog_command_result_version_uq",
            ),
        ]
