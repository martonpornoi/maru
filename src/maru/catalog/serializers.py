"""Closed API inputs for catalog configuration, orders, stock, and payments."""

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

from maru.catalog.models import CatalogPaymentIntent, CatalogProduct
from maru.core.serializers import StrictInputSerializer

MAX_ORDER_LINES = 50

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


class _CatalogClosedInputSerializer(StrictInputSerializer):
    """Marker for Catalog request objects that reject unknown properties."""


class _CatalogClosedInputSchema(OpenApiSerializerExtension):
    """Expose closed inputs and the finite-stock dependency in OpenAPI 3.1."""

    target_class = "maru.catalog.serializers._CatalogClosedInputSerializer"
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: "AutoSchema",
        direction: "Direction",
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]  # noqa: SLF001
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        if self.target.__class__.__name__ == "CatalogVariantAddSerializer":
            schema["dependentRequired"] = {
                "initial_stock": ["stock_ceiling"],
                "stock_ceiling": ["initial_stock"],
            }
        return cast("dict[str, Any]", schema)


class CatalogCreateSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog create data."""

    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField(min_length=1, max_length=500)


class CatalogProductAddSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog product add data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)
    code = serializers.SlugField(max_length=80)
    kind = serializers.ChoiceField(choices=CatalogProduct.Kind.choices)
    name = serializers.CharField(min_length=1, max_length=160)
    description = serializers.CharField(max_length=2_000, required=False, default="")
    beneficiary = serializers.ChoiceField(
        choices=CatalogProduct.Beneficiary.choices,
        required=False,
        default=CatalogProduct.Beneficiary.CONVENTION,
    )
    charity_selection_id = serializers.UUIDField(required=False, allow_null=True)
    sale_opens_at = serializers.DateTimeField(required=False, allow_null=True)
    sale_closes_at = serializers.DateTimeField(required=False, allow_null=True)
    preorder_allowed = serializers.BooleanField(required=False, default=False)
    fulfilment_mode = serializers.ChoiceField(
        choices=CatalogProduct.Fulfilment.choices,
        required=False,
        default=CatalogProduct.Fulfilment.PICKUP,
    )
    per_order_limit = serializers.IntegerField(
        min_value=1, max_value=1_000, required=False, default=10
    )


class CatalogVariantAddSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog variant add data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)
    sku = serializers.CharField(min_length=1, max_length=80)
    name = serializers.CharField(min_length=1, max_length=120)
    price_minor = serializers.IntegerField(min_value=0)
    initial_stock = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text="Supply together with stock_ceiling, or omit both fields.",
    )
    stock_ceiling = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text="Supply together with initial_stock, or omit both fields.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate the supplied data.

        Parameters
        ----------
        attrs : dict[str, Any]
            The attrs mapping to validate or transform.

        Returns
        -------
        dict[str, Any]
            A mapping containing the resolved validate data.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if ("initial_stock" in attrs) != ("stock_ceiling" in attrs):
            raise serializers.ValidationError(
                {
                    "stock": [
                        "Supply both initial_stock and stock_ceiling, or omit both."
                    ]
                }
            )
        return attrs


class CatalogActivateSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog activate data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class CatalogStockAdjustSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog stock adjust data."""

    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)
    new_stock = serializers.IntegerField(min_value=0)


class CatalogOrderLineSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog order line data."""

    variant_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class CatalogOrderCreateSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog order create data."""

    expected_version = serializers.IntegerField(min_value=1)
    lines = CatalogOrderLineSerializer(many=True)

    def validate_lines(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate lines.

        Parameters
        ----------
        value : list[dict[str, Any]]
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        list[dict[str, Any]]
            The matching validate lines records in deterministic order.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not 1 <= len(value) <= MAX_ORDER_LINES:
            raise serializers.ValidationError("Choose between 1 and 50 variants.")
        return value


class CatalogPaymentCreateSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog payment create data."""

    expected_catalog_version = serializers.IntegerField(min_value=1)
    expected_order_version = serializers.IntegerField(min_value=1)
    provider = serializers.ChoiceField(choices=CatalogPaymentIntent.Provider.choices)


class CatalogPaymentReconcileSerializer(_CatalogClosedInputSerializer):
    """Serialize and validate catalog payment reconcile data."""

    expected_catalog_version = serializers.IntegerField(min_value=1)
    expected_order_version = serializers.IntegerField(min_value=1)
    provider_event_id = serializers.CharField(min_length=1, max_length=160)
    result = serializers.ChoiceField(
        choices=(
            CatalogPaymentIntent.Status.SUCCEEDED,
            CatalogPaymentIntent.Status.FAILED,
        )
    )
    reason = serializers.CharField(min_length=1, max_length=500)


class CatalogCommandResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog command result data."""

    target_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    replayed = serializers.BooleanField()


class CatalogVariantProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog variant projection data."""

    id = serializers.UUIDField()
    sku = serializers.CharField()
    name = serializers.CharField()
    price_minor = serializers.IntegerField(min_value=0)
    currency = serializers.CharField()
    stock_limited = serializers.BooleanField()
    available_stock = serializers.IntegerField(min_value=0, allow_null=True)
    preorder_allowed = serializers.BooleanField()


class CatalogProductProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog product projection data."""

    id = serializers.UUIDField()
    code = serializers.CharField()
    kind = serializers.ChoiceField(choices=CatalogProduct.Kind.choices)
    name = serializers.CharField()
    description = serializers.CharField()
    beneficiary = serializers.ChoiceField(choices=CatalogProduct.Beneficiary.choices)
    charity_name = serializers.CharField(allow_null=True)
    sale_opens_at = serializers.DateTimeField(allow_null=True)
    sale_closes_at = serializers.DateTimeField(allow_null=True)
    preorder_allowed = serializers.BooleanField()
    fulfilment_mode = serializers.ChoiceField(choices=CatalogProduct.Fulfilment.choices)
    per_order_limit = serializers.IntegerField(min_value=1)
    variants = CatalogVariantProjectionSerializer(many=True)


class CatalogDetailSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog detail data."""

    catalog_version = serializers.IntegerField(min_value=1)
    currency = serializers.CharField()
    products = CatalogProductProjectionSerializer(many=True)


class CatalogOrderLineProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog order line projection data."""

    product_name = serializers.CharField()
    variant_name = serializers.CharField()
    sku = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)
    unit_price_minor = serializers.IntegerField(min_value=0)
    line_total_minor = serializers.IntegerField(min_value=0)
    beneficiary = serializers.ChoiceField(choices=CatalogProduct.Beneficiary.choices)
    charity_selection_id = serializers.UUIDField(allow_null=True)
    fulfilment_mode = serializers.ChoiceField(choices=CatalogProduct.Fulfilment.choices)


class CatalogPaymentProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog payment projection data."""

    id = serializers.UUIDField()
    provider = serializers.ChoiceField(choices=CatalogPaymentIntent.Provider.choices)
    status = serializers.CharField()
    checkout_url = serializers.CharField()


class CatalogOrderProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog order projection data."""

    id = serializers.UUIDField()
    reference = serializers.CharField()
    status = serializers.CharField()
    aggregate_version = serializers.IntegerField(min_value=1)
    currency = serializers.CharField()
    total_minor = serializers.IntegerField(min_value=0)
    payment_due_at = serializers.DateTimeField(allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)
    fulfilment_status = serializers.CharField()
    lines = CatalogOrderLineProjectionSerializer(many=True)
    payments = CatalogPaymentProjectionSerializer(many=True)


class CatalogOrderListSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog order list data."""

    orders = CatalogOrderProjectionSerializer(many=True)


class CatalogActivityItemSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog activity item data."""

    action = serializers.CharField()
    actor_label = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    target_count = serializers.IntegerField(min_value=0)


class CatalogActivityListSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate catalog activity list data."""

    activity = CatalogActivityItemSerializer(many=True)
