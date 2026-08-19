"""Server-rendered staff controls for governed registration commerce."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from maru.authorization.services import AuthorizationDenied
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.commerce import (
    adjust_registration_capacity,
    configuration_capacity_ceiling,
    effective_configuration_capacity,
    effective_product_capacity,
    offer_next_waitlist_batch,
    pending_target_capacity_holds,
    product_capacity_ceiling,
    registration_commerce_activity,
)
from maru.registration.commerce_forms import (
    CapacityAdjustmentForm,
    WaitlistBatchOfferForm,
)
from maru.registration.models import (
    AdmissionProduct,
    Registration,
    RegistrationCommerceControl,
    RegistrationConfiguration,
)


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise Http404
    return request.user


def _edition(
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> EventEdition:
    return get_object_or_404(
        EventEdition.objects.select_related("organization", "series"),
        organization__slug=organization_slug,
        series__slug=series_slug,
        slug=edition_slug,
    )


def _workspace_location(edition: EventEdition) -> str:
    return reverse(
        "registration-commerce-workspace",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
        ),
    )


def _workspace_context(
    *,
    request: HttpRequest,
    edition: EventEdition,
    actor: Account,
) -> dict[str, object]:
    activity = registration_commerce_activity(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=actor,
        correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
        source_channel="web",
    )
    configuration = get_object_or_404(
        RegistrationConfiguration.objects.prefetch_related("products"),
        organization_id=edition.organization_id,
        edition_id=edition.id,
        status="active",
    )
    control_version = (
        RegistrationCommerceControl.objects.filter(configuration=configuration)
        .values_list("aggregate_version", flat=True)
        .first()
        or 1
    )
    occupied = Registration.objects.filter(
        configuration=configuration,
        state__in=(
            Registration.State.PAYMENT_PENDING,
            Registration.State.CONFIRMED,
            Registration.State.CHECKED_IN,
        ),
    )
    waitlisted = Registration.objects.filter(
        configuration=configuration,
        state=Registration.State.WAITLISTED,
    )
    products: list[dict[str, object]] = []
    for product in configuration.products.all():
        products.append(  # noqa: PERF401 - forms need per-product local values.
            {
                "product": product,
                "effective_capacity": effective_product_capacity(product),
                "hard_ceiling": product_capacity_ceiling(product),
                "occupied": occupied.filter(product=product).count(),
                "holds": pending_target_capacity_holds(product),
                "waitlisted": waitlisted.filter(product=product).count(),
                "capacity_form": CapacityAdjustmentForm(
                    initial={
                        "product_id": product.id,
                        "new_capacity": effective_product_capacity(product),
                        "expected_control_version": control_version,
                    },
                    auto_id=f"id_capacity_{product.id}_%s",
                ),
                "batch_form": WaitlistBatchOfferForm(
                    initial={
                        "product_id": product.id,
                        "batch_size": 1,
                        "expected_control_version": control_version,
                    },
                    auto_id=f"id_batch_{product.id}_%s",
                ),
            }
        )
    return {
        "title": "Registration commerce",
        "organization": edition.organization,
        "convention_series": edition.series,
        "edition": edition,
        "configuration": configuration,
        "control_version": control_version,
        "overall_effective_capacity": effective_configuration_capacity(configuration),
        "overall_hard_ceiling": configuration_capacity_ceiling(configuration),
        "overall_occupied": occupied.count(),
        "overall_waitlisted": waitlisted.count(),
        "overall_capacity_form": CapacityAdjustmentForm(
            initial={
                "new_capacity": effective_configuration_capacity(configuration),
                "expected_control_version": control_version,
            },
            auto_id="id_overall_capacity_%s",
        ),
        "products": tuple(products),
        "activity": activity,
    }


@login_required(login_url="staff-login")
def registration_commerce_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> TemplateResponse:
    """Return registration commerce workspace.

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
    TemplateResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    edition = _edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    actor = _actor(request)
    try:
        context = _workspace_context(request=request, edition=edition, actor=actor)
    except AuthorizationDenied as error:
        raise Http404 from error
    return TemplateResponse(
        request,
        "registration/commerce_workspace.html",
        context,
    )


def _capacity_product(
    *,
    edition: EventEdition,
    product_id: UUID | None,
) -> AdmissionProduct | None:
    if product_id is None:
        return None
    return get_object_or_404(
        AdmissionProduct,
        id=product_id,
        configuration__edition=edition,
        configuration__organization_id=edition.organization_id,
        configuration__status="active",
    )


@login_required(login_url="staff-login")
@require_POST
def adjust_registration_capacity_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    product_id: UUID | None = None,
) -> HttpResponse:
    """Adjust registration capacity page.

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
    product_id : UUID | None, default=None
        The identifier of the product.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    edition = _edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    product = _capacity_product(edition=edition, product_id=product_id)
    form = CapacityAdjustmentForm(request.POST)
    if not form.is_valid() or form.cleaned_data["product_id"] != product_id:
        messages.error(request, "The capacity command was invalid; nothing changed.")
        return redirect(_workspace_location(edition))
    try:
        result = adjust_registration_capacity(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=product.id if product is not None else None,
            actor=_actor(request),
            new_capacity=cast("int", form.cleaned_data["new_capacity"]),
            reason=cast("str", form.cleaned_data["reason"]),
            expected_control_version=cast(
                "int",
                form.cleaned_data["expected_control_version"],
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except (AuthorizationDenied, ObjectDoesNotExist, ValidationError):
        messages.error(request, "Capacity changed or violates its governed ceiling.")
    else:
        messages.success(
            request,
            "Capacity was already recorded."
            if result.replayed
            else "The reasoned capacity adjustment was recorded.",
        )
    return redirect(_workspace_location(edition))


@login_required(login_url="staff-login")
@require_POST
def offer_waitlist_batch_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    product_id: UUID,
) -> HttpResponse:
    """Return offer waitlist batch page.

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

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    edition = _edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    product = _capacity_product(edition=edition, product_id=product_id)
    if product is None:
        raise Http404
    form = WaitlistBatchOfferForm(request.POST)
    if not form.is_valid() or form.cleaned_data["product_id"] != product.id:
        messages.error(request, "The FIFO batch command was invalid; nothing changed.")
        return redirect(_workspace_location(edition))
    try:
        result = offer_next_waitlist_batch(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            product_id=product.id,
            actor=_actor(request),
            batch_size=cast("int", form.cleaned_data["batch_size"]),
            reason=cast("str", form.cleaned_data["reason"]),
            expected_control_version=cast(
                "int",
                form.cleaned_data["expected_control_version"],
            ),
            idempotency_key=cast("UUID", form.cleaned_data["idempotency_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except (AuthorizationDenied, ObjectDoesNotExist, ValidationError):
        messages.error(request, "The waitlist changed; reload before offering places.")
    else:
        messages.success(
            request,
            f"Offered {result.batch.offered_count} strict FIFO place(s).",
        )
    return redirect(_workspace_location(edition))


__all__ = [
    "adjust_registration_capacity_page",
    "offer_waitlist_batch_page",
    "registration_commerce_workspace",
]
