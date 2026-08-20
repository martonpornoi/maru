"""Transactional commands for edition catalog configuration and orders."""
# ruff: noqa: FBT003 -- immutable command-result tuples intentionally use positional fields.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Prefetch, Sum
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_owned_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.catalog.models import (
    CatalogCommandReceipt,
    CatalogOrder,
    CatalogOrderLine,
    CatalogOrderTimelineEntry,
    CatalogPaymentEvent,
    CatalogPaymentIntent,
    CatalogProduct,
    CatalogStockAdjustment,
    CatalogVariant,
    EditionCatalog,
)
from maru.effects.models import DomainEvent
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.queries import account_display_labels

if TYPE_CHECKING:
    from maru.identity.models import Account

MANAGE_CATALOG = "catalog.manage"
MANAGE_STOCK = "catalog.manage_stock"
MANAGE_PAYMENTS = "catalog.manage_payments"
ORDER_SELF = "catalog.order_self"
VIEW_SELF = "catalog.view_self"
VIEW_ACTIVITY = "catalog.view_activity"
MAX_REASON_LENGTH = 500
MAX_ORDER_LINES = 50
MAX_PROVIDER_EVENT_ID_LENGTH = 160
CURRENCY_CODE_LENGTH = 3
PAYMENT_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class CatalogCommandResult:
    """Describe catalog command result.

    Attributes
    ----------
    target_id
        The target identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    target_id: UUID
    resulting_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class OrderLineRequest:
    """Describe order line request.

    Attributes
    ----------
    variant_id
        The variant identifier within the requested scope.
    quantity
        The positive number of inventory or entitlement units requested.
    """

    variant_id: UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class CatalogActivity:
    """Describe catalog activity.

    Attributes
    ----------
    action
        The stable action code describing the requested transition.
    actor_label
        The human-readable actor label shown to authorized readers.
    occurred_at
        The timezone-aware timestamp for occurred.
    target_count
        The bounded number of target records.
    """

    action: str
    actor_label: str
    occurred_at: datetime
    target_count: int


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reason(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_REASON_LENGTH:
        raise ValidationError(
            {"reason": "Use a reason between 1 and 500 characters."},
            code="catalog_reason_invalid",
        )
    return normalized


def _authorize(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
) -> frozenset[str]:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
    )
    if decision.allowed:
        return decision.obligations
    raise AuthorizationDenied(
        "The catalog operation is unavailable.",
        reason_code=decision.reason_code,
    )


def authorize_catalog_edition_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> None:
    """Authorize an exact edition route before an API adapter parses input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    capability_code : str
        The stable capability code required by the operation.
    """
    _authorize(
        actor=actor,
        capability_code=capability_code,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )


def authorize_catalog_self_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> None:
    """Authorize an exact attendee catalog route before parsing input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    """
    _authorize(
        actor=actor,
        capability_code=ORDER_SELF,
        target=resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )


def authorize_catalog_order_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID, order_id: UUID
) -> None:
    """Authorize exact order ownership without loading order line projections.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    order_id : UUID
        The order identifier within the requested scope.
    """
    order = CatalogOrder.objects.filter(
        id=order_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=actor.id,
    ).first()
    _authorize(
        actor=actor,
        capability_code=ORDER_SELF,
        target=resolve_owned_target(resource=order) if order is not None else None,
    )


def _audit(
    *,
    actor: Account,
    capability_code: str,
    operation: str,
    catalog: EditionCatalog,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    reason_code: str,
    obligations: frozenset[str],
    changed_fields: tuple[str, ...] = (),
    target_count: int = 1,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=catalog.organization_id,
            event_edition_id=catalog.edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(obligations)),
            changed_fields=changed_fields,
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "target_count": target_count,
            },
            retention_class="commerce-operational",
        )
    )


def _publish(
    *,
    catalog: EditionCatalog,
    event_name: str,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    payload: dict[str, object],
    actor: Account,
    correlation_id: UUID,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=catalog.organization_id,
            event_edition_id=catalog.edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=correlation_id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="commerce-operational",
        ),
        workload_pool="core",
    )


def _existing_receipt(
    *,
    catalog: EditionCatalog,
    actor: Account,
    idempotency_key: UUID,
    operation: str,
    request_digest: str,
) -> CatalogCommandReceipt | None:
    receipt = CatalogCommandReceipt.objects.filter(
        catalog=catalog,
        actor=actor,
        idempotency_key=idempotency_key,
    ).first()
    if receipt is None:
        return None
    if receipt.operation != operation or receipt.request_digest != request_digest:
        raise ValidationError(
            "The idempotency key belongs to a different catalog command.",
            code="catalog_idempotency_conflict",
        )
    return receipt


def _advance(catalog: EditionCatalog, *, expected_version: int) -> int:
    if expected_version != catalog.aggregate_version:
        raise ValidationError(
            "The catalog changed; reload before retrying.",
            code="catalog_version_conflict",
        )
    catalog.aggregate_version += 1
    catalog.save(update_fields=("aggregate_version", "updated_at"))
    return int(catalog.aggregate_version)


def _receipt(
    *,
    catalog: EditionCatalog,
    actor: Account,
    operation: str,
    idempotency_key: UUID,
    request_digest: str,
    resulting_version: int,
    result_id: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
) -> None:
    CatalogCommandReceipt.objects.create(
        catalog=catalog,
        actor=actor,
        operation=operation,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        resulting_version=resulting_version,
        result_id=result_id,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def create_catalog(
    *,
    organization_id: UUID,
    edition_id: UUID,
    currency: str,
    actor: Account,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Create catalog.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    currency : str
        The ISO currency code.
    actor : Account
        The authenticated person performing the operation.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _authorize(
        actor=actor,
        capability_code=MANAGE_CATALOG,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    normalized_reason = _reason(reason)
    normalized_currency = currency.strip().upper()
    if len(normalized_currency) != CURRENCY_CODE_LENGTH:
        raise ValidationError({"currency": "Use a three-letter currency code."})
    request_digest = _digest(
        {
            "operation": "catalog_created",
            "organization_id": organization_id,
            "edition_id": edition_id,
            "currency": normalized_currency,
        }
    )
    with transaction.atomic():
        edition = EventEdition.objects.select_for_update().get(
            id=edition_id,
            organization_id=organization_id,
        )
        existing = EditionCatalog.objects.filter(edition=edition).first()
        if existing is not None:
            replay = _existing_receipt(
                catalog=existing,
                actor=actor,
                idempotency_key=idempotency_key,
                operation=CatalogCommandReceipt.Operation.CATALOG_CREATED,
                request_digest=request_digest,
            )
            if replay is not None:
                return CatalogCommandResult(
                    target_id=replay.result_id,
                    resulting_version=int(replay.resulting_version),
                    replayed=True,
                )
            raise ValidationError(
                "This edition already has a catalog.",
                code="catalog_already_exists",
            )
        catalog = EditionCatalog.objects.create(
            organization_id=organization_id,
            edition=edition,
            currency=normalized_currency,
            created_by=actor,
        )
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.CATALOG_CREATED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=1,
            result_id=catalog.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.definition.changed.v1",
            aggregate_type="edition_catalog",
            aggregate_id=catalog.id,
            aggregate_version=1,
            payload={"action": "created", "target_kind": "catalog", "state": "draft"},
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=MANAGE_CATALOG,
            operation="catalog.create",
            catalog=catalog,
            target_type="edition_catalog",
            target_id=catalog.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="catalog_created",
            obligations=obligations,
            changed_fields=("catalog",),
        )
    return CatalogCommandResult(catalog.id, 1, False)


def add_product(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    expected_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    reason: str,
    code: str,
    kind: str,
    name: str,
    description: str = "",
    beneficiary: str = CatalogProduct.Beneficiary.CONVENTION,
    charity_selection_id: UUID | None = None,
    sale_opens_at: datetime | None = None,
    sale_closes_at: datetime | None = None,
    preorder_allowed: bool = False,
    fulfilment_mode: str = CatalogProduct.Fulfilment.PICKUP,
    per_order_limit: int = 10,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Add product.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    reason : str
        The operator-supplied reason for the operation.
    code : str
        The stable machine-readable code.
    kind : str
        The closed kind code.
    name : str
        The human-readable name.
    description : str, default=''
        The human-readable description.
    beneficiary : str, default=CatalogProduct.Beneficiary.CONVENTION
        The beneficiary applied within the audited domain transition.
    charity_selection_id : UUID | None, default=None
        The identifier of the charity selection.
    sale_opens_at : datetime | None, default=None
        The timezone-aware timestamp for sale opens.
    sale_closes_at : datetime | None, default=None
        The timezone-aware timestamp for sale closes.
    preorder_allowed : bool, default=False
        The preorder allowed applied within the audited domain transition.
    fulfilment_mode : str, default=CatalogProduct.Fulfilment.PICKUP
        The closed fulfilment mode discriminator defined by the domain catalog.
    per_order_limit : int, default=10
        The per order limit applied within the audited domain transition.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    obligations = _authorize(actor=actor, capability_code=MANAGE_CATALOG, target=target)
    normalized_reason = _reason(reason)
    request_digest = _digest(
        {
            "operation": "product_added",
            "code": code,
            "kind": kind,
            "name": name,
            "description": description,
            "beneficiary": beneficiary,
            "charity_selection_id": charity_selection_id,
            "sale_opens_at": sale_opens_at,
            "sale_closes_at": sale_closes_at,
            "preorder_allowed": preorder_allowed,
            "fulfilment_mode": fulfilment_mode,
            "per_order_limit": per_order_limit,
        }
    )
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.PRODUCT_ADDED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        if catalog.status != EditionCatalog.Status.DRAFT:
            raise ValidationError("Only a draft catalog may add products.")
        product = CatalogProduct.objects.create(
            catalog=catalog,
            code=code,
            kind=kind,
            name=name.strip(),
            description=description.strip(),
            beneficiary=beneficiary,
            charity_selection_id=charity_selection_id,
            sale_opens_at=sale_opens_at,
            sale_closes_at=sale_closes_at,
            preorder_allowed=preorder_allowed,
            fulfilment_mode=fulfilment_mode,
            per_order_limit=per_order_limit,
        )
        version = _advance(catalog, expected_version=expected_version)
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.PRODUCT_ADDED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=product.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.definition.changed.v1",
            aggregate_type="edition_catalog",
            aggregate_id=catalog.id,
            aggregate_version=version,
            payload={
                "action": "product_added",
                "target_kind": "product",
                "state": "draft",
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=MANAGE_CATALOG,
            operation="catalog.product.add",
            catalog=catalog,
            target_type="catalog_product",
            target_id=product.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="product_added",
            obligations=obligations,
            changed_fields=("products",),
        )
    return CatalogCommandResult(product.id, version, False)


def add_variant(
    *,
    organization_id: UUID,
    edition_id: UUID,
    product_id: UUID,
    actor: Account,
    expected_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    reason: str,
    sku: str,
    name: str,
    price_minor: int,
    initial_stock: int | None = None,
    stock_ceiling: int | None = None,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Add variant.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    product_id : UUID
        The identifier of the product.
    actor : Account
        The authenticated person performing the operation.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    reason : str
        The operator-supplied reason for the operation.
    sku : str
        The sku applied within the audited domain transition.
    name : str
        The human-readable name.
    price_minor : int
        The price in minor currency units.
    initial_stock : int | None, default=None
        The initial stock applied within the audited domain transition.
    stock_ceiling : int | None, default=None
        The non-negative hard limit or requested amount for stock ceiling.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _authorize(
        actor=actor,
        capability_code=MANAGE_CATALOG,
        target=resolve_edition_target(
            organization_id=organization_id, edition_id=edition_id
        ),
    )
    normalized_reason = _reason(reason)
    request_digest = _digest(
        {
            "operation": "variant_added",
            "product_id": product_id,
            "sku": sku,
            "name": name,
            "price_minor": price_minor,
            "initial_stock": initial_stock,
            "stock_ceiling": stock_ceiling,
        }
    )
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.VARIANT_ADDED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        if catalog.status != EditionCatalog.Status.DRAFT:
            raise ValidationError("Only a draft catalog may add variants.")
        product = CatalogProduct.objects.get(id=product_id, catalog=catalog)
        variant = CatalogVariant.objects.create(
            product=product,
            sku=sku.strip(),
            name=name.strip(),
            price_minor=price_minor,
            currency=catalog.currency,
            initial_stock=initial_stock,
            stock_ceiling=stock_ceiling,
        )
        version = _advance(catalog, expected_version=expected_version)
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.VARIANT_ADDED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=variant.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.definition.changed.v1",
            aggregate_type="edition_catalog",
            aggregate_id=catalog.id,
            aggregate_version=version,
            payload={
                "action": "variant_added",
                "target_kind": "variant",
                "state": "draft",
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=MANAGE_CATALOG,
            operation="catalog.variant.add",
            catalog=catalog,
            target_type="catalog_variant",
            target_id=variant.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="variant_added",
            obligations=obligations,
            changed_fields=("variants",),
        )
    return CatalogCommandResult(variant.id, version, False)


def activate_catalog(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    expected_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    reason: str,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Activate catalog.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    reason : str
        The operator-supplied reason for the operation.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _authorize(
        actor=actor,
        capability_code=MANAGE_CATALOG,
        target=resolve_edition_target(
            organization_id=organization_id, edition_id=edition_id
        ),
    )
    normalized_reason = _reason(reason)
    request_digest = _digest({"operation": "catalog_activated"})
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.CATALOG_ACTIVATED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        if catalog.status != EditionCatalog.Status.DRAFT:
            raise ValidationError("Only a draft catalog may be activated.")
        products = CatalogProduct.objects.filter(catalog=catalog)
        if (
            not products.exists()
            or not CatalogVariant.objects.filter(
                product__catalog=catalog, active=True
            ).exists()
        ):
            raise ValidationError("Activate only after adding a product and variant.")
        products.update(status=CatalogProduct.Status.ACTIVE)
        version = _advance(catalog, expected_version=expected_version)
        catalog.status = EditionCatalog.Status.ACTIVE
        catalog.save(update_fields=("status", "updated_at"))
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.CATALOG_ACTIVATED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=catalog.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.definition.changed.v1",
            aggregate_type="edition_catalog",
            aggregate_id=catalog.id,
            aggregate_version=version,
            payload={
                "action": "activated",
                "target_kind": "catalog",
                "state": "active",
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=MANAGE_CATALOG,
            operation="catalog.activate",
            catalog=catalog,
            target_type="edition_catalog",
            target_id=catalog.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="catalog_activated",
            obligations=obligations,
            changed_fields=("status",),
        )
    return CatalogCommandResult(catalog.id, version, False)


def effective_stock(variant: CatalogVariant) -> int | None:
    """Return governed physical stock, or ``None`` for unlimited variants.

    Parameters
    ----------
    variant : CatalogVariant
        The variant applied within the audited domain transition.

    Returns
    -------
    int | None
        The resolved int | None for effective stock.
    """
    if variant.initial_stock is None:
        return None
    latest = (
        CatalogStockAdjustment.objects.filter(variant=variant)
        .order_by("-control_version", "-id")
        .values_list("new_stock", flat=True)
        .first()
    )
    return int(latest if latest is not None else variant.initial_stock)


def committed_quantity(variant: CatalogVariant) -> int:
    """Return committed quantity.

    Parameters
    ----------
    variant : CatalogVariant
        The variant applied within the audited domain transition.

    Returns
    -------
    int
        The effective numeric value for committed quantity.
    """
    value = CatalogOrderLine.objects.filter(
        variant=variant,
        order__status__in=(
            CatalogOrder.Status.PAYMENT_PENDING,
            CatalogOrder.Status.PAID,
        ),
    ).aggregate(total=Sum("quantity"))["total"]
    return int(value or 0)


def available_stock(variant: CatalogVariant) -> int | None:
    """Return available stock.

    Parameters
    ----------
    variant : CatalogVariant
        The variant applied within the audited domain transition.

    Returns
    -------
    int | None
        The available stock.
    """
    stock = effective_stock(variant)
    return None if stock is None else max(0, stock - committed_quantity(variant))


def adjust_stock(
    *,
    organization_id: UUID,
    edition_id: UUID,
    variant_id: UUID,
    new_stock: int,
    actor: Account,
    expected_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    reason: str,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Adjust stock.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    variant_id : UUID
        The identifier of the variant.
    new_stock : int
        The new stock applied within the audited domain transition.
    actor : Account
        The authenticated person performing the operation.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    reason : str
        The operator-supplied reason for the operation.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _authorize(
        actor=actor,
        capability_code=MANAGE_STOCK,
        target=resolve_edition_target(
            organization_id=organization_id, edition_id=edition_id
        ),
    )
    normalized_reason = _reason(reason)
    if type(new_stock) is not int or new_stock < 0:
        raise ValidationError({"new_stock": "Use a non-negative stock value."})
    request_digest = _digest(
        {
            "operation": "stock_adjusted",
            "variant_id": variant_id,
            "new_stock": new_stock,
        }
    )
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.STOCK_ADJUSTED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        if catalog.status == EditionCatalog.Status.CLOSED:
            raise ValidationError("Closed catalog stock cannot change.")
        variant = CatalogVariant.objects.select_for_update().get(
            id=variant_id,
            product__catalog=catalog,
        )
        previous = effective_stock(variant)
        if previous is None or variant.stock_ceiling is None:
            raise ValidationError("Unlimited variants do not accept stock changes.")
        if new_stock > variant.stock_ceiling:
            raise ValidationError(
                "Stock cannot exceed its configured hard ceiling.",
                code="catalog_stock_ceiling_exceeded",
            )
        if new_stock < committed_quantity(variant):
            raise ValidationError(
                "Stock cannot drop below paid and payment-pending commitments.",
                code="catalog_stock_below_committed",
            )
        version = _advance(catalog, expected_version=expected_version)
        adjustment = CatalogStockAdjustment.objects.create(
            catalog=catalog,
            variant=variant,
            previous_stock=previous,
            new_stock=new_stock,
            reason=normalized_reason,
            actor=actor,
            control_version=version,
            correlation_id=correlation_id,
        )
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.STOCK_ADJUSTED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=adjustment.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.stock.adjusted.v1",
            aggregate_type="edition_catalog",
            aggregate_id=catalog.id,
            aggregate_version=version,
            payload={
                "variant_id": str(variant.id),
                "previous_stock": str(previous),
                "new_stock": str(new_stock),
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=MANAGE_STOCK,
            operation="catalog.stock.adjust",
            catalog=catalog,
            target_type="catalog_variant",
            target_id=variant.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="stock_adjusted",
            obligations=obligations,
            changed_fields=("effective_stock",),
        )
    return CatalogCommandResult(adjustment.id, version, False)


def _validate_line_requests(
    lines: tuple[OrderLineRequest, ...],
) -> dict[UUID, int]:
    if not lines or len(lines) > MAX_ORDER_LINES:
        raise ValidationError(
            {"lines": f"Choose between 1 and {MAX_ORDER_LINES} variants."}
        )
    quantities: dict[UUID, int] = {}
    for line in lines:
        if line.variant_id in quantities:
            raise ValidationError({"lines": "Each variant may appear only once."})
        if type(line.quantity) is not int or line.quantity < 1:
            raise ValidationError({"lines": "Quantities must be positive integers."})
        quantities[line.variant_id] = line.quantity
    return quantities


def place_order(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    lines: tuple[OrderLineRequest, ...],
    expected_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> CatalogCommandResult:
    """Place order.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.
    lines : tuple[OrderLineRequest, ...]
        The ordered line items to process.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _authorize(
        actor=actor,
        capability_code=ORDER_SELF,
        target=resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    quantities = _validate_line_requests(lines)
    request_digest = _digest(
        {
            "operation": "order_placed",
            "lines": [
                {"variant_id": str(variant_id), "quantity": quantity}
                for variant_id, quantity in sorted(
                    quantities.items(), key=lambda item: str(item[0])
                )
            ],
        }
    )
    ordered_at = now or timezone.now()
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.ORDER_PLACED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        if catalog.status != EditionCatalog.Status.ACTIVE:
            raise ValidationError("This edition catalog is not accepting orders.")
        variants = list(
            CatalogVariant.objects.select_for_update(of=("self",))
            .select_related("product", "product__catalog", "product__charity_selection")
            .filter(
                id__in=quantities,
                active=True,
                product__catalog=catalog,
                product__status=CatalogProduct.Status.ACTIVE,
            )
            .order_by("id")
        )
        if len(variants) != len(quantities):
            raise ValidationError("One or more selected variants are unavailable.")
        total_minor = 0
        for variant in variants:
            product = variant.product
            quantity = quantities[variant.id]
            if product.sale_opens_at and ordered_at < product.sale_opens_at:
                raise ValidationError(f"{product.name} is not on sale yet.")
            if product.sale_closes_at and ordered_at >= product.sale_closes_at:
                raise ValidationError(f"{product.name} is no longer on sale.")
            if quantity > product.per_order_limit:
                raise ValidationError(
                    f"{product.name} allows at most "
                    f"{product.per_order_limit} per order."
                )
            charity_selection = product.charity_selection
            if charity_selection is not None and (
                charity_selection.status != charity_selection.Status.CONFIRMED
            ):
                raise ValidationError(
                    "The selected charity beneficiary is unavailable."
                )
            stock = available_stock(variant)
            if stock is not None and quantity > stock and not product.preorder_allowed:
                raise ValidationError(
                    f"Only {stock} unit(s) of {product.name} are available.",
                    code="catalog_stock_unavailable",
                )
            total_minor += int(variant.price_minor) * quantity
        order = CatalogOrder(
            catalog=catalog,
            organization_id=organization_id,
            edition_id=edition_id,
            account=actor,
            reference="",
            status=(
                CatalogOrder.Status.PAID
                if total_minor == 0
                else CatalogOrder.Status.PAYMENT_PENDING
            ),
            currency=catalog.currency,
            total_minor=total_minor,
            payment_due_at=(ordered_at + PAYMENT_WINDOW if total_minor else None),
            paid_at=(ordered_at if total_minor == 0 else None),
        )
        order.reference = f"SHOP-{order.id.hex[:12].upper()}"
        order.save()
        for variant in variants:
            product = variant.product
            quantity = quantities[variant.id]
            CatalogOrderLine.objects.create(
                order=order,
                product=product,
                variant=variant,
                product_kind_snapshot=product.kind,
                product_name_snapshot=product.name,
                variant_name_snapshot=variant.name,
                sku_snapshot=variant.sku,
                quantity=quantity,
                unit_price_minor=variant.price_minor,
                line_total_minor=int(variant.price_minor) * quantity,
                beneficiary_snapshot=product.beneficiary,
                charity_selection_id_snapshot=product.charity_selection_id,
                fulfilment_mode_snapshot=product.fulfilment_mode,
            )
        CatalogOrderTimelineEntry.objects.create(
            order=order,
            kind="placed",
            title="Order placed",
            summary=(
                "No payment was required."
                if total_minor == 0
                else "Stock was reserved while payment is pending."
            ),
            actor=actor,
            occurred_at=ordered_at,
        )
        version = _advance(catalog, expected_version=expected_version)
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.ORDER_PLACED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=order.id,
            reason="",
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.order.changed.v1",
            aggregate_type="catalog_order",
            aggregate_id=order.id,
            aggregate_version=1,
            payload={
                "action": "placed",
                "status": order.status,
                "reference": order.reference,
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=ORDER_SELF,
            operation="catalog.order.place",
            catalog=catalog,
            target_type="catalog_order",
            target_id=order.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="order_placed",
            obligations=obligations,
            changed_fields=("order", "stock_commitment"),
            target_count=len(variants),
        )
    return CatalogCommandResult(order.id, version, False)


def create_payment_intent(
    *,
    organization_id: UUID,
    edition_id: UUID,
    order_id: UUID,
    provider: str,
    actor: Account,
    expected_catalog_version: int,
    expected_order_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
) -> CatalogCommandResult:
    """Create payment intent.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    order_id : UUID
        The identifier of the order.
    provider : str
        The external-service adapter used without making it authoritative.
    actor : Account
        The authenticated person performing the operation.
    expected_catalog_version : int
        The catalog version required for optimistic concurrency.
    expected_order_version : int
        The order version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    owned = CatalogOrder.objects.filter(
        id=order_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account=actor,
    ).first()
    obligations = _authorize(
        actor=actor,
        capability_code=ORDER_SELF,
        target=resolve_owned_target(resource=owned) if owned is not None else None,
    )
    if provider not in CatalogPaymentIntent.Provider.values:
        raise ValidationError({"provider": "Use a registered payment provider."})
    request_digest = _digest(
        {"operation": "payment_created", "order_id": order_id, "provider": provider}
    )
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.PAYMENT_CREATED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        order = CatalogOrder.objects.select_for_update().get(
            id=order_id,
            catalog=catalog,
            account=actor,
        )
        if order.status != CatalogOrder.Status.PAYMENT_PENDING:
            raise ValidationError("This order does not require payment.")
        if expected_order_version != order.aggregate_version:
            raise ValidationError(
                "The order changed; reload before retrying.",
                code="catalog_order_version_conflict",
            )
        if order.payment_intents.filter(status="pending").exists():
            raise ValidationError("This order already has a pending payment.")
        intent = CatalogPaymentIntent(
            order=order,
            provider=provider,
            provider_reference="",
            amount_minor=order.total_minor,
            currency=order.currency,
        )
        intent.provider_reference = f"{provider}-{intent.id.hex}"
        if provider == CatalogPaymentIntent.Provider.HOSTED:
            intent.checkout_url = (
                f"https://payments.invalid/catalog/{intent.provider_reference}"
            )
        intent.save()
        order.aggregate_version += 1
        order.save(update_fields=("aggregate_version", "updated_at"))
        CatalogOrderTimelineEntry.objects.create(
            order=order,
            kind="payment_created",
            title="Payment started",
            summary=f"A {provider} payment was created for the exact order total.",
            actor=actor,
            occurred_at=timezone.now(),
        )
        version = _advance(catalog, expected_version=expected_catalog_version)
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.PAYMENT_CREATED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=intent.id,
            reason="",
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.order.changed.v1",
            aggregate_type="catalog_order",
            aggregate_id=order.id,
            aggregate_version=int(order.aggregate_version),
            payload={
                "action": "payment_created",
                "status": order.status,
                "reference": order.reference,
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=ORDER_SELF,
            operation="catalog.payment.create",
            catalog=catalog,
            target_type="catalog_payment_intent",
            target_id=intent.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code="payment_created",
            obligations=obligations,
            changed_fields=("payment",),
        )
    return CatalogCommandResult(intent.id, version, False)


def _payment_authorization(
    *, actor: Account, intent: CatalogPaymentIntent
) -> tuple[str, frozenset[str]]:
    owned_target = resolve_owned_target(resource=intent.order)
    self_decision = decide(
        principal=actor,
        capability_code=ORDER_SELF,
        resource=owned_target,
    )
    if intent.provider == CatalogPaymentIntent.Provider.DEMO and self_decision.allowed:
        return ORDER_SELF, self_decision.obligations
    target = resolve_edition_target(
        organization_id=intent.order.organization_id,
        edition_id=intent.order.edition_id,
    )
    return MANAGE_PAYMENTS, _authorize(
        actor=actor,
        capability_code=MANAGE_PAYMENTS,
        target=target,
    )


def authorize_catalog_payment_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID, intent_id: UUID
) -> None:
    """Authorize an exact payment intent without exposing order or payment data.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    intent_id : UUID
        The intent identifier within the requested scope.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    intent = (
        CatalogPaymentIntent.objects.select_related("order")
        .filter(
            id=intent_id,
            order__organization_id=organization_id,
            order__edition_id=edition_id,
        )
        .first()
    )
    if intent is None:
        raise AuthorizationDenied(
            "The catalog operation is unavailable.",
            reason_code="catalog_resource_unavailable",
        )
    _payment_authorization(actor=actor, intent=intent)


def reconcile_payment(
    *,
    organization_id: UUID,
    edition_id: UUID,
    intent_id: UUID,
    provider_event_id: str,
    result: str,
    actor: Account,
    expected_catalog_version: int,
    expected_order_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    reason: str = "provider reconciliation",
    source_channel: str = "api",
    now: datetime | None = None,
) -> CatalogCommandResult:
    """Reconcile payment.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    intent_id : UUID
        The identifier of the intent.
    provider_event_id : str
        The identifier of the provider event.
    result : str
        The result applied within the audited domain transition.
    actor : Account
        The authenticated person performing the operation.
    expected_catalog_version : int
        The catalog version required for optimistic concurrency.
    expected_order_version : int
        The order version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    reason : str, default='provider reconciliation'
        The operator-supplied reason for the operation.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.

    Raises
    ------
    ObjectDoesNotExist
        If a required scoped record does not exist.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    unresolved = (
        CatalogPaymentIntent.objects.select_related("order")
        .filter(
            id=intent_id,
            order__organization_id=organization_id,
            order__edition_id=edition_id,
        )
        .first()
    )
    if unresolved is None:
        raise ObjectDoesNotExist
    capability_code, obligations = _payment_authorization(
        actor=actor, intent=unresolved
    )
    normalized_reason = _reason(reason)
    if result not in {
        CatalogPaymentIntent.Status.SUCCEEDED,
        CatalogPaymentIntent.Status.FAILED,
    }:
        raise ValidationError({"result": "Use succeeded or failed."})
    provider_event_id = provider_event_id.strip()
    if not provider_event_id or len(provider_event_id) > MAX_PROVIDER_EVENT_ID_LENGTH:
        raise ValidationError({"provider_event_id": "Use a bounded event reference."})
    request_digest = _digest(
        {
            "operation": "payment_reconciled",
            "intent_id": intent_id,
            "provider_event_id": provider_event_id,
            "result": result,
        }
    )
    reconciled_at = now or timezone.now()
    with transaction.atomic():
        catalog = EditionCatalog.objects.select_for_update().get(
            organization_id=organization_id, edition_id=edition_id
        )
        replay = _existing_receipt(
            catalog=catalog,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=CatalogCommandReceipt.Operation.PAYMENT_RECONCILED,
            request_digest=request_digest,
        )
        if replay is not None:
            return CatalogCommandResult(
                replay.result_id, int(replay.resulting_version), True
            )
        intent = (
            CatalogPaymentIntent.objects.select_for_update()
            .select_related("order")
            .get(id=intent_id, order__catalog=catalog)
        )
        order = CatalogOrder.objects.select_for_update().get(id=intent.order_id)
        if intent.status != CatalogPaymentIntent.Status.PENDING:
            raise ValidationError("This payment intent has already reached a result.")
        if expected_order_version != order.aggregate_version:
            raise ValidationError(
                "The order changed; reload before reconciliation.",
                code="catalog_order_version_conflict",
            )
        if CatalogPaymentEvent.objects.filter(
            provider=intent.provider, provider_event_id=provider_event_id
        ).exists():
            raise ValidationError("This provider event was already consumed.")
        intent.status = result
        intent.aggregate_version += 1
        intent.succeeded_at = (
            reconciled_at if result == CatalogPaymentIntent.Status.SUCCEEDED else None
        )
        intent.save(
            update_fields=("status", "aggregate_version", "succeeded_at", "updated_at")
        )
        if result == CatalogPaymentIntent.Status.SUCCEEDED:
            if order.status != CatalogOrder.Status.PAYMENT_PENDING:
                raise ValidationError("The payment no longer matches an open order.")
            order.status = CatalogOrder.Status.PAID
            order.paid_at = reconciled_at
        order.aggregate_version += 1
        order.save(
            update_fields=("status", "paid_at", "aggregate_version", "updated_at")
        )
        event = CatalogPaymentEvent.objects.create(
            intent=intent,
            provider=intent.provider,
            provider_event_id=provider_event_id,
            result=result,
            occurred_at=reconciled_at,
            correlation_id=correlation_id,
        )
        CatalogOrderTimelineEntry.objects.create(
            order=order,
            kind="payment_succeeded" if result == "succeeded" else "payment_failed",
            title="Payment confirmed" if result == "succeeded" else "Payment failed",
            summary=(
                "The provider confirmed the exact order total."
                if result == "succeeded"
                else "The provider did not confirm payment; the order remains unpaid."
            ),
            actor=actor,
            occurred_at=reconciled_at,
        )
        version = _advance(catalog, expected_version=expected_catalog_version)
        _receipt(
            catalog=catalog,
            actor=actor,
            operation=CatalogCommandReceipt.Operation.PAYMENT_RECONCILED,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=version,
            result_id=event.id,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        _publish(
            catalog=catalog,
            event_name="catalog.order.changed.v1",
            aggregate_type="catalog_order",
            aggregate_id=order.id,
            aggregate_version=int(order.aggregate_version),
            payload={
                "action": "payment_succeeded"
                if result == "succeeded"
                else "payment_failed",
                "status": order.status,
                "reference": order.reference,
            },
            actor=actor,
            correlation_id=correlation_id,
        )
        _audit(
            actor=actor,
            capability_code=capability_code,
            operation="catalog.payment.reconcile",
            catalog=catalog,
            target_type="catalog_payment_intent",
            target_id=intent.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            reason_code=f"payment_{result}",
            obligations=obligations,
            changed_fields=("payment", "order_status"),
        )
    return CatalogCommandResult(event.id, version, False)


def complete_demo_payment(
    *,
    organization_id: UUID,
    edition_id: UUID,
    order_id: UUID,
    actor: Account,
    expected_catalog_version: int,
    expected_order_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "web",
) -> CatalogCommandResult:
    """Complete demo payment.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    order_id : UUID
        The identifier of the order.
    actor : Account
        The authenticated person performing the operation.
    expected_catalog_version : int
        The catalog version required for optimistic concurrency.
    expected_order_version : int
        The order version required for optimistic concurrency.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.

    Returns
    -------
    CatalogCommandResult
        The catalog command result.
    """
    create_key = uuid5(NAMESPACE_URL, f"maru:catalog:demo:create:{idempotency_key}")
    reconcile_key = uuid5(
        NAMESPACE_URL, f"maru:catalog:demo:reconcile:{idempotency_key}"
    )
    created = create_payment_intent(
        organization_id=organization_id,
        edition_id=edition_id,
        order_id=order_id,
        provider=CatalogPaymentIntent.Provider.DEMO,
        actor=actor,
        expected_catalog_version=expected_catalog_version,
        expected_order_version=expected_order_version,
        idempotency_key=create_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    intent = CatalogPaymentIntent.objects.select_related("order").get(
        id=created.target_id
    )
    if intent.status == CatalogPaymentIntent.Status.SUCCEEDED:
        receipt = CatalogCommandReceipt.objects.get(
            catalog=intent.order.catalog,
            actor=actor,
            idempotency_key=reconcile_key,
        )
        return CatalogCommandResult(
            receipt.result_id, int(receipt.resulting_version), True
        )
    return reconcile_payment(
        organization_id=organization_id,
        edition_id=edition_id,
        intent_id=intent.id,
        provider_event_id=f"demo-{idempotency_key.hex}",
        result=CatalogPaymentIntent.Status.SUCCEEDED,
        actor=actor,
        expected_catalog_version=created.resulting_version,
        expected_order_version=int(intent.order.aggregate_version),
        idempotency_key=reconcile_key,
        correlation_id=correlation_id,
        reason="deterministic demo payment",
        source_channel=source_channel,
    )


_ACTIVITY_LABELS = {
    "catalog.definition.changed.v1": "Changed the edition catalog",
    "catalog.stock.adjusted.v1": "Adjusted governed catalog stock",
    "catalog.order.changed.v1": "Advanced a catalog order or payment",
}


def catalog_activity(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    correlation_id: UUID,
    source_channel: str = "api",
    limit: int = 50,
) -> tuple[CatalogActivity, ...]:
    """Return catalog activity.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str, default='api'
        The trusted channel that initiated the operation.
    limit : int, default=50
        The maximum number of records to process.

    Returns
    -------
    tuple[CatalogActivity, ...]
        The authorized catalog activity records in deterministic order.
    """
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    obligations = _authorize(actor=actor, capability_code=VIEW_ACTIVITY, target=target)
    bounded_limit = min(max(int(limit), 1), 100)
    events = tuple(
        DomainEvent.objects.filter(
            organization_id=organization_id,
            event_edition_id=edition_id,
            event_name__in=_ACTIVITY_LABELS,
        ).order_by("-occurred_at", "-id")[:bounded_limit]
    )
    catalog = EditionCatalog.objects.get(
        organization_id=organization_id, edition_id=edition_id
    )
    _audit(
        actor=actor,
        capability_code=VIEW_ACTIVITY,
        operation="catalog.activity.list",
        catalog=catalog,
        target_type="catalog_activity",
        target_id=edition_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason_code="purpose_scoped_catalog_activity",
        obligations=obligations,
        target_count=len(events),
    )
    labels = account_display_labels(
        {event.actor_id for event in events if event.actor_id is not None}
    )
    return tuple(
        CatalogActivity(
            action=_ACTIVITY_LABELS[event.event_name],
            actor_label=(
                labels.get(event.actor_id, "Maru account")
                if event.actor_id is not None
                else "Maru automation"
            ),
            occurred_at=event.occurred_at,
            target_count=1,
        )
        for event in events
    )


def available_products_for_actor(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    now: datetime | None = None,
) -> tuple[CatalogProduct, ...]:
    """Return available products for actor.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    tuple[CatalogProduct, ...]
        The available products for actor.
    """
    _authorize(
        actor=actor,
        capability_code=ORDER_SELF,
        target=resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    evaluated_at = now or timezone.now()
    return tuple(
        CatalogProduct.objects.prefetch_related(
            Prefetch(
                "variants",
                queryset=CatalogVariant.objects.filter(active=True),
            )
        )
        .select_related("charity_selection__partner")
        .filter(
            catalog__organization_id=organization_id,
            catalog__edition_id=edition_id,
            catalog__status=EditionCatalog.Status.ACTIVE,
            status=CatalogProduct.Status.ACTIVE,
        )
        .exclude(sale_opens_at__gt=evaluated_at)
        .exclude(sale_closes_at__lte=evaluated_at)
        .order_by("position", "name", "id")
    )


def available_catalogs_for_actor(
    *, actor: Account, limit: int = 50
) -> tuple[EditionCatalog, ...]:
    """Return a bounded attendee-facing index of active edition catalogs.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    limit : int, default=50
        The maximum number of records to return.

    Returns
    -------
    tuple[EditionCatalog, ...]
        The matching available catalogs for actor records in deterministic
        order.
    """
    bounded_limit = min(max(int(limit), 1), 100)
    scope_rows = (
        EditionCatalog.objects.filter(status=EditionCatalog.Status.ACTIVE)
        .order_by("-edition__starts_on", "edition__name", "id")
        .values_list("id", "organization_id", "edition_id")
        .iterator(chunk_size=min(max(bounded_limit, 10), 100))
    )
    authorized_ids: list[UUID] = []
    for catalog_id, organization_id, edition_id in scope_rows:
        target = resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        try:
            _authorize(actor=actor, capability_code=ORDER_SELF, target=target)
        except AuthorizationDenied:
            continue
        authorized_ids.append(catalog_id)
        if len(authorized_ids) == bounded_limit:
            break
    # Fetch tenant labels only after the exact self-service decision succeeds.
    return tuple(
        EditionCatalog.objects.select_related("edition", "edition__series")
        .filter(id__in=authorized_ids)
        .order_by("-edition__starts_on", "edition__name", "id")
    )


def own_orders(
    *, organization_id: UUID, edition_id: UUID, actor: Account
) -> tuple[CatalogOrder, ...]:
    """Return own orders.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    actor : Account
        The authenticated person performing the operation.

    Returns
    -------
    tuple[CatalogOrder, ...]
        The authorized own orders records in deterministic order.
    """
    _authorize(
        actor=actor,
        capability_code=VIEW_SELF,
        target=resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    return tuple(
        CatalogOrder.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account=actor,
        )
        .prefetch_related("lines", "payment_intents", "timeline_entries")
        .order_by("-created_at", "id")
    )
