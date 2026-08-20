"""Explainable admission-product availability for APIs and reference clients."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

from maru.identity.models import Account
from maru.participation.models import ParticipationCapacity
from maru.registration.models import AdmissionProduct, Registration

if TYPE_CHECKING:
    from django.db.models import QuerySet


@dataclass(frozen=True, slots=True)
class ProductAvailability:
    """Describe product availability.

    Attributes
    ----------
    selectable
        The selectable retained in this immutable projection.
    code
        The stable domain code to resolve or validate.
    explanation
        The disclosure-safe explanation presented to the caller.
    waitlist
        The waitlist retained in this immutable projection.
    """

    selectable: bool
    code: str
    explanation: str
    waitlist: bool = False


OCCUPIED_REGISTRATION_STATES = (
    Registration.State.PAYMENT_PENDING,
    Registration.State.CONFIRMED,
    Registration.State.CHECKED_IN,
)


def assess_product_availability(  # noqa: PLR0911 - each denial stays explicit
    *,
    product: AdmissionProduct,
    account: Account | None,
    at: datetime | None = None,
    ignore_sale_window: bool = False,
) -> ProductAvailability:
    """Return one attendee-safe, server-authoritative availability decision.

    Parameters
    ----------
    product : AdmissionProduct
        The edition-owned product whose policy or capacity is evaluated.
    account : Account | None
        The platform account whose state or access is being evaluated.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.
    ignore_sale_window : bool, default=False
        The ignore sale window evaluated while assess product availability.

    Returns
    -------
    ProductAvailability
        The resolved ProductAvailability for assess product availability.
    """
    current_time = at or timezone.now()
    configuration = product.configuration
    if product.status != AdmissionProduct.Status.AVAILABLE:
        return ProductAvailability(
            selectable=False,
            code="product_hidden",
            explanation="This admission option is not currently offered.",
        )
    if (
        not ignore_sale_window
        and product.sales_open_at is not None
        and current_time < product.sales_open_at
    ):
        return ProductAvailability(
            selectable=False,
            code="product_sales_not_open",
            explanation=(
                f"This offer opens on {product.sales_open_at:%Y-%m-%d %H:%M %Z}."
            ),
        )
    if (
        not ignore_sale_window
        and product.sales_close_at is not None
        and current_time >= product.sales_close_at
    ):
        return ProductAvailability(
            selectable=False,
            code="product_sales_closed",
            explanation="This offer has ended.",
        )
    if product.required_capacity_codes:
        if account is None:
            return ProductAvailability(
                selectable=False,
                code="product_sign_in_required",
                explanation=(
                    product.eligibility_explanation
                    or "Sign in to verify whether this offer applies to you."
                ),
            )
        eligible = ParticipationCapacity.objects.filter(
            participation__account=account,
            participation__edition_id=configuration.edition_id,
            status=ParticipationCapacity.Status.ACTIVE,
            code__in=product.required_capacity_codes,
        ).exists()
        if not eligible:
            return ProductAvailability(
                selectable=False,
                code="product_capacity_required",
                explanation=(
                    product.eligibility_explanation
                    or "This offer is limited to an assigned convention role."
                ),
            )

    occupied: QuerySet[Registration] = Registration.objects.filter(
        configuration=configuration,
        state__in=OCCUPIED_REGISTRATION_STATES,
    )
    product_full = occupied.filter(product=product).count() >= product.capacity
    edition_full = occupied.count() >= configuration.capacity
    if product_full or edition_full:
        if configuration.waitlist_enabled and product.waitlist_enabled:
            return ProductAvailability(
                selectable=True,
                code="waitlist_available",
                explanation=(
                    "Capacity is currently full. Submitting will join the waitlist; "
                    "payment is requested only if a place is offered."
                ),
                waitlist=True,
            )
        return ProductAvailability(
            selectable=False,
            code="capacity_reached",
            explanation="This admission option is currently full.",
        )
    return ProductAvailability(
        selectable=True,
        code="available",
        explanation="A place can currently be reserved.",
    )
