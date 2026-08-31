"""Same-shell attendee and staff pages for catalog commerce."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.catalog.forms import (
    CatalogActivateForm,
    CatalogCreateForm,
    CatalogOrderForm,
    CatalogPaymentForm,
    CatalogProductAddForm,
    CatalogStockForm,
    CatalogVariantAddForm,
)
from maru.catalog.models import (
    CatalogOrder,
    CatalogPaymentIntent,
    CatalogProduct,
    CatalogVariant,
    EditionCatalog,
)
from maru.catalog.services import (
    MANAGE_CATALOG,
    MANAGE_STOCK,
    ORDER_SELF,
    VIEW_ACTIVITY,
    VIEW_SELF,
    OrderLineRequest,
    activate_catalog,
    add_product,
    add_variant,
    adjust_stock,
    available_catalogs_for_actor,
    available_products_for_actor,
    available_stock,
    catalog_activity,
    complete_demo_payment,
    create_catalog,
    create_payment_intent,
    effective_stock,
    own_orders,
    place_order,
)
from maru.charities.models import CharitySelection
from maru.events.models import EventEdition
from maru.events.queries import adoption_profile_filter_for_module
from maru.identity.models import Account

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import QuerySet


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise Http404
    return request.user


def _correlation_id(request: HttpRequest) -> UUID:
    return UUID(str(request.correlation_id))  # type: ignore[attr-defined]


def _page_context(
    request: HttpRequest,
    *,
    personal: bool,
    **values: object,
) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(values)
    context["maru_personal_surface"] = personal
    if personal:
        context["has_permission"] = True
    return context


def _authorize_self_catalog_scope(
    *, edition_id: UUID, actor: Account, capability_code: str
) -> None:
    """Authorize one exact-profile Catalog self-service scope before labels.

    Parameters
    ----------
    edition_id : UUID
        The event edition whose exact profile governs the request.
    actor : Account
        The authenticated person requesting the self-service operation.
    capability_code : str
        The exact self-service capability required by the route.

    Raises
    ------
    Http404
        If the exact profile, scope, or self-service capability is unavailable.
    """
    organization_id = (
        EventEdition.objects.filter(
            adoption_profile_filter_for_module("catalog"),
            id=edition_id,
        )
        .values_list("organization_id", flat=True)
        .first()
    )
    if organization_id is None:
        raise Http404
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise Http404


def _owned_order(
    *,
    order_id: UUID,
    edition_id: UUID,
    actor: Account,
    capability_code: str,
) -> CatalogOrder:
    _authorize_self_catalog_scope(
        edition_id=edition_id,
        actor=actor,
        capability_code=capability_code,
    )
    return get_object_or_404(
        CatalogOrder.objects.prefetch_related(
            "lines", "payment_intents", "timeline_entries"
        ),
        id=order_id,
        edition_id=edition_id,
        account=actor,
    )


@login_required(login_url="staff-login")
@never_cache
@require_GET
def my_catalog_index_page(request: HttpRequest) -> HttpResponse:
    """Render my catalog index page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    catalogs = available_catalogs_for_actor(actor=actor)
    return TemplateResponse(
        request,
        "catalog/my_catalog_index.html",
        _page_context(
            request,
            personal=True,
            title="Shop & orders",
            catalogs=catalogs,
            maru_personal_editions=tuple(catalog.edition for catalog in catalogs),
        ),
    )


@login_required(login_url="staff-login")
@never_cache
@require_GET
def my_catalog_page(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    """Render my catalog page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _actor(request)
    _authorize_self_catalog_scope(
        edition_id=edition_id,
        actor=actor,
        capability_code=VIEW_SELF,
    )
    catalog = get_object_or_404(
        EditionCatalog.objects.select_related("edition"),
        edition_id=edition_id,
        status=EditionCatalog.Status.ACTIVE,
    )
    try:
        products = available_products_for_actor(
            organization_id=catalog.organization_id,
            edition_id=edition_id,
            actor=actor,
        )
    except AuthorizationDenied as error:
        raise Http404 from error
    product_cards: list[dict[str, object]] = []
    for product in products:
        variants: list[dict[str, object]] = []
        for variant in product.variants.all():
            variants.append(  # noqa: PERF401 - each card owns a bound command form.
                {
                    "variant": variant,
                    "available_stock": available_stock(variant),
                    "form": CatalogOrderForm(
                        initial={
                            "variant_id": variant.id,
                            "quantity": 1,
                            "expected_version": catalog.aggregate_version,
                        },
                        auto_id=f"catalog_order_{variant.id}_%s",
                    ),
                }
            )
        product_cards.append({"product": product, "variants": tuple(variants)})
    return TemplateResponse(
        request,
        "catalog/my_catalog.html",
        _page_context(
            request,
            personal=True,
            title=f"{catalog.edition.name} catalog",
            edition=catalog.edition,
            catalog=catalog,
            product_cards=tuple(product_cards),
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def place_catalog_order_page(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    """Place catalog order page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    _authorize_self_catalog_scope(
        edition_id=edition_id,
        actor=actor,
        capability_code=ORDER_SELF,
    )
    form = CatalogOrderForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The order input was invalid; nothing was reserved.")
        return redirect("my-catalog", edition_id=edition_id)
    catalog = get_object_or_404(EditionCatalog, edition_id=edition_id)
    try:
        result = place_order(
            organization_id=catalog.organization_id,
            edition_id=edition_id,
            actor=actor,
            lines=(
                OrderLineRequest(
                    variant_id=cast("UUID", form.cleaned_data["variant_id"]),
                    quantity=cast("int", form.cleaned_data["quantity"]),
                ),
            ),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="web",
        )
    except (AuthorizationDenied, ObjectDoesNotExist, ValidationError):
        messages.error(request, "Availability changed; reload before ordering.")
        return redirect("my-catalog", edition_id=edition_id)
    messages.success(request, "Your catalog order was created.")
    return redirect(
        "my-catalog-checkout", edition_id=edition_id, order_id=result.target_id
    )


@login_required(login_url="staff-login")
@never_cache
@require_GET
def my_catalog_orders_page(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    """Render my catalog orders page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _actor(request)
    _authorize_self_catalog_scope(
        edition_id=edition_id,
        actor=actor,
        capability_code=VIEW_SELF,
    )
    catalog = get_object_or_404(
        EditionCatalog.objects.select_related("edition"), edition_id=edition_id
    )
    try:
        orders = own_orders(
            organization_id=catalog.organization_id,
            edition_id=edition_id,
            actor=actor,
        )
    except AuthorizationDenied as error:
        raise Http404 from error
    return TemplateResponse(
        request,
        "catalog/my_orders.html",
        _page_context(
            request,
            personal=True,
            title="Your catalog orders",
            edition=catalog.edition,
            orders=orders,
        ),
    )


@login_required(login_url="staff-login")
@never_cache
@require_GET
def catalog_checkout_page(
    request: HttpRequest, edition_id: UUID, order_id: UUID
) -> HttpResponse:
    """Render catalog checkout page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    order_id : UUID
        The identifier of the order.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    order = _owned_order(
        order_id=order_id,
        edition_id=edition_id,
        actor=actor,
        capability_code=VIEW_SELF,
    )
    catalog = order.catalog
    return TemplateResponse(
        request,
        "catalog/checkout.html",
        _page_context(
            request,
            personal=True,
            title=f"Checkout {order.reference}",
            edition=order.edition,
            catalog=catalog,
            order=order,
            payment_form=CatalogPaymentForm(
                initial={
                    "expected_catalog_version": catalog.aggregate_version,
                    "expected_order_version": order.aggregate_version,
                }
            ),
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def start_catalog_hosted_payment_page(
    request: HttpRequest, edition_id: UUID, order_id: UUID
) -> HttpResponse:
    """Start catalog hosted payment page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    order_id : UUID
        The identifier of the order.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    order = _owned_order(
        order_id=order_id,
        edition_id=edition_id,
        actor=actor,
        capability_code=ORDER_SELF,
    )
    form = CatalogPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The checkout command was invalid.")
        return redirect("my-catalog-checkout", edition_id=edition_id, order_id=order_id)
    try:
        result = create_payment_intent(
            organization_id=order.organization_id,
            edition_id=edition_id,
            order_id=order.id,
            provider=CatalogPaymentIntent.Provider.HOSTED,
            actor=actor,
            expected_catalog_version=cast(
                "int", form.cleaned_data["expected_catalog_version"]
            ),
            expected_order_version=cast(
                "int", form.cleaned_data["expected_order_version"]
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="web",
        )
    except (AuthorizationDenied, ObjectDoesNotExist, ValidationError):
        messages.error(request, "Checkout changed; reload before retrying.")
    else:
        intent = CatalogPaymentIntent.objects.get(id=result.target_id)
        messages.success(
            request,
            "Hosted checkout is ready; provider reconciliation will confirm it.",
        )
        if intent.checkout_url:
            return redirect(intent.checkout_url)
    return redirect("my-catalog-checkout", edition_id=edition_id, order_id=order_id)


@login_required(login_url="staff-login")
@require_POST
def complete_catalog_demo_payment_page(
    request: HttpRequest, edition_id: UUID, order_id: UUID
) -> HttpResponse:
    """Complete catalog demo payment page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    order_id : UUID
        The identifier of the order.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    order = _owned_order(
        order_id=order_id,
        edition_id=edition_id,
        actor=actor,
        capability_code=ORDER_SELF,
    )
    form = CatalogPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The demo-payment command was invalid.")
        return redirect("my-catalog-checkout", edition_id=edition_id, order_id=order_id)
    try:
        complete_demo_payment(
            organization_id=order.organization_id,
            edition_id=edition_id,
            order_id=order.id,
            actor=actor,
            expected_catalog_version=cast(
                "int", form.cleaned_data["expected_catalog_version"]
            ),
            expected_order_version=cast(
                "int", form.cleaned_data["expected_order_version"]
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="web",
        )
    except (AuthorizationDenied, ObjectDoesNotExist, ValidationError):
        messages.error(request, "The demo payment could not be reconciled.")
    else:
        messages.success(request, "The deterministic demo payment was confirmed.")
    return redirect("my-catalog-checkout", edition_id=edition_id, order_id=order_id)


def _edition_route(
    *, organization_slug: str, series_slug: str, edition_slug: str
) -> EventEdition:
    return get_object_or_404(
        EventEdition.objects.select_related("organization", "series"),
        organization__slug=organization_slug,
        series__slug=series_slug,
        slug=edition_slug,
    )


def _staff_location(edition: EventEdition) -> str:
    return reverse(
        "catalog-staff-workspace",
        args=(edition.organization.slug, edition.series.slug, edition.slug),
    )


def _allowed(*, actor: Account, capability_code: str, edition: EventEdition) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_edition_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed


def _require_capability(
    *, actor: Account, capability_code: str, edition: EventEdition
) -> None:
    if not _allowed(actor=actor, capability_code=capability_code, edition=edition):
        raise Http404


def _confirmed_charities(edition: EventEdition) -> QuerySet[CharitySelection]:
    return (
        CharitySelection.objects.select_related("partner")
        .filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            status=CharitySelection.Status.CONFIRMED,
        )
        .order_by("partner__public_name", "id")
    )


def _execute_staff_command(
    request: HttpRequest,
    *,
    command: Callable[[], object],
    success_message: str,
    edition: EventEdition,
) -> HttpResponse:
    try:
        command()
    except AuthorizationDenied as error:
        raise Http404 from error
    except ObjectDoesNotExist as error:
        raise Http404 from error
    except ValidationError:
        messages.error(
            request,
            "The catalog changed or the submitted policy is invalid; nothing changed.",
        )
    except DatabaseError:
        return HttpResponse("Catalog commerce is temporarily unavailable.", status=503)
    else:
        messages.success(request, success_message)
    return redirect(_staff_location(edition))


def _invalid_staff_form(request: HttpRequest, edition: EventEdition) -> HttpResponse:
    messages.error(request, "Review the submitted fields; nothing changed.")
    return redirect(_staff_location(edition))


@login_required(login_url="staff-login")
@never_cache
@require_GET
def catalog_staff_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render catalog staff workspace.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    can_manage = _allowed(
        actor=actor,
        capability_code=MANAGE_CATALOG,
        edition=edition,
    )
    can_manage_stock = _allowed(
        actor=actor,
        capability_code=MANAGE_STOCK,
        edition=edition,
    )
    can_view_activity = _allowed(
        actor=actor,
        capability_code=VIEW_ACTIVITY,
        edition=edition,
    )
    if not (can_manage or can_manage_stock or can_view_activity):
        raise Http404
    catalog = (
        EditionCatalog.objects.prefetch_related("products__variants")
        .filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        .first()
    )
    activity: tuple[object, ...] = ()
    if catalog is not None and can_view_activity:
        try:
            activity = tuple(
                catalog_activity(
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    actor=actor,
                    correlation_id=_correlation_id(request),
                    source_channel="web",
                )
            )
        except AuthorizationDenied as error:
            raise Http404 from error
    variants: list[dict[str, object]] = []
    product_cards: list[dict[str, object]] = []
    if catalog is not None:
        for product in catalog.products.all():
            product_cards.append(
                {
                    "product": product,
                    "variant_form": (
                        CatalogVariantAddForm(
                            product_kind=product.kind,
                            initial={"expected_version": catalog.aggregate_version},
                            auto_id=f"catalog_variant_{product.id}_%s",
                        )
                        if can_manage and catalog.status == EditionCatalog.Status.DRAFT
                        else None
                    ),
                }
            )
            if not can_manage_stock:
                continue
            for variant in product.variants.all():
                if variant.initial_stock is None:
                    continue
                variants.append(
                    {
                        "product": product,
                        "variant": variant,
                        "effective_stock": effective_stock(variant),
                        "available_stock": available_stock(variant),
                        "form": CatalogStockForm(
                            initial={
                                "variant_id": variant.id,
                                "expected_version": catalog.aggregate_version,
                                "new_stock": effective_stock(variant),
                            },
                            auto_id=f"catalog_stock_{variant.id}_%s",
                        ),
                    }
                )
    is_draft = catalog is not None and catalog.status == EditionCatalog.Status.DRAFT
    charities = _confirmed_charities(edition)
    return TemplateResponse(
        request,
        "catalog/staff_workspace.html",
        _page_context(
            request,
            personal=False,
            title="Catalog commerce",
            organization=edition.organization,
            convention_series=edition.series,
            edition=edition,
            catalog=catalog,
            can_manage=can_manage,
            can_manage_stock=can_manage_stock,
            can_view_activity=can_view_activity,
            catalog_create_form=(
                CatalogCreateForm(
                    initial={
                        "currency": (
                            edition.currency_codes[0]
                            if edition.currency_codes
                            else "EUR"
                        )
                    }
                )
                if catalog is None and can_manage
                else None
            ),
            product_form=(
                CatalogProductAddForm(
                    edition_time_zone=edition.time_zone,
                    charity_selections=charities,
                    initial={"expected_version": catalog.aggregate_version},
                )
                if is_draft and can_manage and catalog is not None
                else None
            ),
            activation_form=(
                CatalogActivateForm(
                    initial={"expected_version": catalog.aggregate_version}
                )
                if is_draft and can_manage and catalog is not None
                else None
            ),
            product_cards=tuple(product_cards),
            variants=tuple(variants),
            activity=activity,
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def create_catalog_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Create catalog page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _require_capability(actor=actor, capability_code=MANAGE_CATALOG, edition=edition)
    form = CatalogCreateForm(request.POST)
    if not form.is_valid():
        return _invalid_staff_form(request, edition)
    return _execute_staff_command(
        request,
        command=lambda: create_catalog(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            currency=cast("str", form.cleaned_data["currency"]),
            actor=actor,
            reason=cast("str", form.cleaned_data["reason"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="web",
        ),
        success_message="The draft edition catalog was created.",
        edition=edition,
    )


@login_required(login_url="staff-login")
@require_POST
def add_catalog_product_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Add catalog product page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _require_capability(actor=actor, capability_code=MANAGE_CATALOG, edition=edition)
    form = CatalogProductAddForm(
        request.POST,
        edition_time_zone=edition.time_zone,
        charity_selections=_confirmed_charities(edition),
    )
    if not form.is_valid():
        return _invalid_staff_form(request, edition)
    selection = cast(
        "CharitySelection | None", form.cleaned_data["charity_selection_id"]
    )
    return _execute_staff_command(
        request,
        command=lambda: add_product(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=actor,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            reason=cast("str", form.cleaned_data["reason"]),
            code=cast("str", form.cleaned_data["code"]),
            kind=cast("str", form.cleaned_data["kind"]),
            name=cast("str", form.cleaned_data["name"]),
            description=cast("str", form.cleaned_data["description"]),
            beneficiary=cast("str", form.cleaned_data["beneficiary"]),
            charity_selection_id=selection.id if selection is not None else None,
            sale_opens_at=form.cleaned_data["sale_opens_at"],
            sale_closes_at=form.cleaned_data["sale_closes_at"],
            preorder_allowed=cast("bool", form.cleaned_data["preorder_allowed"]),
            fulfilment_mode=cast("str", form.cleaned_data["fulfilment_mode"]),
            per_order_limit=cast("int", form.cleaned_data["per_order_limit"]),
            source_channel="web",
        ),
        success_message="The draft product configuration was added.",
        edition=edition,
    )


@login_required(login_url="staff-login")
@require_POST
def add_catalog_variant_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    product_id: UUID,
) -> HttpResponse:
    """Add catalog variant page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    product_id : UUID
        The identifier of the product.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _require_capability(actor=actor, capability_code=MANAGE_CATALOG, edition=edition)
    product = get_object_or_404(
        CatalogProduct,
        id=product_id,
        catalog__organization_id=edition.organization_id,
        catalog__edition_id=edition.id,
    )
    form = CatalogVariantAddForm(request.POST, product_kind=product.kind)
    if not form.is_valid():
        return _invalid_staff_form(request, edition)
    return _execute_staff_command(
        request,
        command=lambda: add_variant(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=product.id,
            actor=actor,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            reason=cast("str", form.cleaned_data["reason"]),
            sku=cast("str", form.cleaned_data["sku"]),
            name=cast("str", form.cleaned_data["name"]),
            price_minor=cast("int", form.cleaned_data["price_minor"]),
            initial_stock=cast("int | None", form.cleaned_data["initial_stock"]),
            stock_ceiling=cast("int | None", form.cleaned_data["stock_ceiling"]),
            source_channel="web",
        ),
        success_message="The draft price and stock variant was added.",
        edition=edition,
    )


@login_required(login_url="staff-login")
@require_POST
def activate_catalog_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Activate catalog page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _require_capability(actor=actor, capability_code=MANAGE_CATALOG, edition=edition)
    form = CatalogActivateForm(request.POST)
    if not form.is_valid():
        return _invalid_staff_form(request, edition)
    return _execute_staff_command(
        request,
        command=lambda: activate_catalog(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=actor,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            reason=cast("str", form.cleaned_data["reason"]),
            source_channel="web",
        ),
        success_message="The catalog was activated for attendee ordering.",
        edition=edition,
    )


@login_required(login_url="staff-login")
@require_POST
def adjust_catalog_stock_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    variant_id: UUID,
) -> HttpResponse:
    """Render adjust catalog stock page.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    variant_id : UUID
        The identifier of the variant.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _actor(request)
    edition = _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _require_capability(actor=actor, capability_code=MANAGE_STOCK, edition=edition)
    get_object_or_404(
        CatalogVariant,
        id=variant_id,
        product__catalog__organization_id=edition.organization_id,
        product__catalog__edition_id=edition.id,
    )
    form = CatalogStockForm(request.POST)
    if not form.is_valid() or form.cleaned_data["variant_id"] != variant_id:
        messages.error(request, "The stock command was invalid; nothing changed.")
        return redirect(_staff_location(edition))
    return _execute_staff_command(
        request,
        command=lambda: adjust_stock(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            variant_id=variant_id,
            new_stock=cast("int", form.cleaned_data["new_stock"]),
            actor=actor,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            reason=cast("str", form.cleaned_data["reason"]),
            source_channel="web",
        ),
        success_message="The append-only stock adjustment was recorded.",
        edition=edition,
    )
