"""Versioned API adapters for the catalog bounded context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID, uuid4

from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.services import AuthorizationDenied
from maru.catalog.models import (
    CatalogOrder,
    CatalogProduct,
    CatalogVariant,
    EditionCatalog,
)
from maru.catalog.serializers import (
    CatalogActivateSerializer,
    CatalogActivityListSerializer,
    CatalogCommandResultSerializer,
    CatalogCreateSerializer,
    CatalogDetailSerializer,
    CatalogOrderCreateSerializer,
    CatalogOrderListSerializer,
    CatalogPaymentCreateSerializer,
    CatalogPaymentReconcileSerializer,
    CatalogProductAddSerializer,
    CatalogStockAdjustSerializer,
    CatalogVariantAddSerializer,
)
from maru.catalog.services import (
    MANAGE_CATALOG,
    MANAGE_STOCK,
    OrderLineRequest,
    activate_catalog,
    add_product,
    add_variant,
    adjust_stock,
    authorize_catalog_edition_api_scope,
    authorize_catalog_order_api_scope,
    authorize_catalog_payment_api_scope,
    authorize_catalog_self_api_scope,
    available_products_for_actor,
    available_stock,
    catalog_activity,
    create_catalog,
    create_payment_intent,
    own_orders,
    place_order,
    reconcile_payment,
)
from maru.core.api_input import reject_unknown_fields
from maru.identity.models import Account

IDEMPOTENCY_HEADER = "Idempotency-Key"
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "Canonical lower-case hyphenated UUID. Exact retries return HTTP 200; "
        "new resources return HTTP 201. The key is not accepted in JSON."
    ),
)


def _actor(request: Request) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied("The catalog operation is unavailable.")
    return request.user


def _preauthorize_edition(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
) -> Account:
    actor = _actor(request)
    _execute(
        lambda: authorize_catalog_edition_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
        )
    )
    return actor


def _preauthorize_self(
    request: Request, *, organization_id: UUID, edition_id: UUID
) -> Account:
    actor = _actor(request)
    _execute(
        lambda: authorize_catalog_self_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    )
    return actor


def _preauthorize_order(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    order_id: UUID,
) -> Account:
    actor = _actor(request)
    _execute(
        lambda: authorize_catalog_order_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            order_id=order_id,
        )
    )
    return actor


def _preauthorize_payment(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    intent_id: UUID,
) -> Account:
    actor = _actor(request)
    _execute(
        lambda: authorize_catalog_payment_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            intent_id=intent_id,
        )
    )
    return actor


def _idempotency_key(request: Request) -> UUID:
    raw = request.headers.get(IDEMPOTENCY_HEADER, "")
    try:
        value = UUID(raw)
    except ValueError as error:
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]}
        ) from error
    if str(value) != raw:
        raise ApiValidationError({IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]})
    return value


def _correlation_id(request: Request) -> UUID:
    try:
        return UUID(str(getattr(request, "correlation_id", "")))
    except ValueError:
        return uuid4()


def _validated(
    request: Request, serializer_class: type[serializers.Serializer[Any]]
) -> dict[str, Any]:
    reject_unknown_fields(request.query_params, allowed_fields=frozenset())
    serializer = serializer_class(data=request.data)
    reject_unknown_fields(
        request.data,
        allowed_fields=frozenset(serializer.fields),
    )
    serializer.is_valid(raise_exception=True)
    return cast(dict[str, Any], serializer.validated_data)


def _execute[Result](command: Callable[[], Result]) -> Result:
    try:
        return command()
    except AuthorizationDenied as error:
        raise PermissionDenied("The catalog operation is unavailable.") from error
    except ObjectDoesNotExist as error:
        raise NotFound("The catalog record is unavailable.") from error
    except DjangoValidationError as error:
        if hasattr(error, "message_dict"):
            raise ApiValidationError(error.message_dict) from error
        raise ApiValidationError({"non_field_errors": list(error.messages)}) from error


def _variant_payload(variant: CatalogVariant) -> dict[str, object]:
    return {
        "id": variant.id,
        "sku": variant.sku,
        "name": variant.name,
        "price_minor": variant.price_minor,
        "currency": variant.currency,
        "stock_limited": variant.is_stock_limited,
        "available_stock": available_stock(variant),
        "preorder_allowed": variant.product.preorder_allowed,
    }


def _product_payload(product: CatalogProduct) -> dict[str, object]:
    charity = product.charity_selection
    return {
        "id": product.id,
        "code": product.code,
        "kind": product.kind,
        "name": product.name,
        "description": product.description,
        "beneficiary": product.beneficiary,
        "charity_name": charity.partner.public_name if charity is not None else None,
        "sale_opens_at": product.sale_opens_at,
        "sale_closes_at": product.sale_closes_at,
        "preorder_allowed": product.preorder_allowed,
        "fulfilment_mode": product.fulfilment_mode,
        "per_order_limit": product.per_order_limit,
        "variants": [_variant_payload(variant) for variant in product.variants.all()],
    }


def _order_payload(order: CatalogOrder) -> dict[str, object]:
    return {
        "id": order.id,
        "reference": order.reference,
        "status": order.status,
        "aggregate_version": order.aggregate_version,
        "currency": order.currency,
        "total_minor": order.total_minor,
        "payment_due_at": order.payment_due_at,
        "paid_at": order.paid_at,
        "fulfilment_status": order.fulfilment_status,
        "lines": [
            {
                "product_name": line.product_name_snapshot,
                "variant_name": line.variant_name_snapshot,
                "sku": line.sku_snapshot,
                "quantity": line.quantity,
                "unit_price_minor": line.unit_price_minor,
                "line_total_minor": line.line_total_minor,
                "beneficiary": line.beneficiary_snapshot,
                "charity_selection_id": line.charity_selection_id_snapshot,
                "fulfilment_mode": line.fulfilment_mode_snapshot,
            }
            for line in order.lines.all()
        ],
        "payments": [
            {
                "id": payment.id,
                "provider": payment.provider,
                "status": payment.status,
                "checkout_url": payment.checkout_url,
            }
            for payment in order.payment_intents.all()
        ],
    }


def _command_response(result: Any, *, created: bool = False) -> Response:
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(
        {
            "target_id": result.target_id,
            "resulting_version": result.resulting_version,
            "replayed": result.replayed,
        },
        status=response_status,
    )


@method_decorator(never_cache, name="dispatch")
class PrivateCatalogAPIView(APIView):
    """Keep authenticated catalog data and safe errors out of shared caches."""


class CatalogDetailApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_retrieve_edition_catalog",
        responses={200: CatalogDetailSerializer},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        products = _execute(
            lambda: available_products_for_actor(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
            )
        )
        catalog = _execute(
            lambda: EditionCatalog.objects.get(
                organization_id=organization_id, edition_id=edition_id
            )
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        return Response(
            {
                "catalog_version": catalog.aggregate_version,
                "currency": catalog.currency,
                "products": [_product_payload(product) for product in products],
            }
        )

    @extend_schema(
        operation_id="catalog_create_edition_catalog",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogCreateSerializer,
        responses={
            200: CatalogCommandResultSerializer,
            201: CatalogCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=MANAGE_CATALOG,
        )
        payload = _validated(request, CatalogCreateSerializer)
        result = _execute(
            lambda: create_catalog(
                organization_id=organization_id,
                edition_id=edition_id,
                currency=payload["currency"],
                actor=_actor(request),
                reason=payload["reason"],
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
            )
        )
        return _command_response(result, created=True)


class CatalogProductCollectionApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_add_product",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogProductAddSerializer,
        responses={
            200: CatalogCommandResultSerializer,
            201: CatalogCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=MANAGE_CATALOG,
        )
        payload = _validated(request, CatalogProductAddSerializer)
        result = _execute(
            lambda: add_product(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result, created=True)


class CatalogVariantCollectionApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_add_variant",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogVariantAddSerializer,
        responses={
            200: CatalogCommandResultSerializer,
            201: CatalogCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        product_id: UUID,
    ) -> Response:
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=MANAGE_CATALOG,
        )
        payload = _validated(request, CatalogVariantAddSerializer)
        result = _execute(
            lambda: add_variant(
                organization_id=organization_id,
                edition_id=edition_id,
                product_id=product_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result, created=True)


class CatalogActivateApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_activate_edition_catalog",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogActivateSerializer,
        responses={200: CatalogCommandResultSerializer},
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=MANAGE_CATALOG,
        )
        payload = _validated(request, CatalogActivateSerializer)
        result = _execute(
            lambda: activate_catalog(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result)


class CatalogStockAdjustApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_adjust_variant_stock",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogStockAdjustSerializer,
        responses={200: CatalogCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        variant_id: UUID,
    ) -> Response:
        _preauthorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=MANAGE_STOCK,
        )
        payload = _validated(request, CatalogStockAdjustSerializer)
        result = _execute(
            lambda: adjust_stock(
                organization_id=organization_id,
                edition_id=edition_id,
                variant_id=variant_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result)


class CatalogOrderCollectionApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_list_own_orders",
        responses={200: CatalogOrderListSerializer},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        orders = _execute(
            lambda: own_orders(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
            )
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        return Response({"orders": [_order_payload(order) for order in orders]})

    @extend_schema(
        operation_id="catalog_place_order",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogOrderCreateSerializer,
        responses={
            200: CatalogCommandResultSerializer,
            201: CatalogCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        _preauthorize_self(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        payload = _validated(request, CatalogOrderCreateSerializer)
        line_payloads = payload.pop("lines")
        result = _execute(
            lambda: place_order(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
                lines=tuple(
                    OrderLineRequest(
                        variant_id=line["variant_id"], quantity=line["quantity"]
                    )
                    for line in line_payloads
                ),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result, created=True)


class CatalogPaymentCreateApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_create_payment_intent",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogPaymentCreateSerializer,
        responses={
            200: CatalogCommandResultSerializer,
            201: CatalogCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        order_id: UUID,
    ) -> Response:
        _preauthorize_order(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            order_id=order_id,
        )
        payload = _validated(request, CatalogPaymentCreateSerializer)
        result = _execute(
            lambda: create_payment_intent(
                organization_id=organization_id,
                edition_id=edition_id,
                order_id=order_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result, created=True)


class CatalogPaymentReconcileApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_reconcile_payment_intent",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=CatalogPaymentReconcileSerializer,
        responses={200: CatalogCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        intent_id: UUID,
    ) -> Response:
        _preauthorize_payment(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            intent_id=intent_id,
        )
        payload = _validated(request, CatalogPaymentReconcileSerializer)
        result = _execute(
            lambda: reconcile_payment(
                organization_id=organization_id,
                edition_id=edition_id,
                intent_id=intent_id,
                actor=_actor(request),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
                **payload,
            )
        )
        return _command_response(result)


class CatalogActivityApi(PrivateCatalogAPIView):
    @extend_schema(
        operation_id="catalog_list_activity",
        responses={200: CatalogActivityListSerializer},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        activity = _execute(
            lambda: catalog_activity(
                organization_id=organization_id,
                edition_id=edition_id,
                actor=_actor(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        return Response(
            {
                "activity": [
                    {
                        "action": item.action,
                        "actor_label": item.actor_label,
                        "occurred_at": item.occurred_at,
                        "target_count": item.target_count,
                    }
                    for item in activity
                ]
            }
        )
