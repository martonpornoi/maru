"""App-owned HTML routes for registration commerce controls."""

from django.urls import path

from maru.registration.commerce_views import (
    adjust_registration_capacity_page,
    offer_waitlist_batch_page,
    registration_commerce_workspace,
)
from maru.registration.public_views import (
    create_local_hosted_payment,
    reserve_local_tier_replacement,
)

urlpatterns = [
    path(
        "my/registrations/<uuid:edition_id>/admission-upgrade/",
        reserve_local_tier_replacement,
        name="public-registration-tier-replacement",
    ),
    path(
        "my/registrations/<uuid:edition_id>/hosted-payment/",
        create_local_hosted_payment,
        name="public-registration-hosted-payment",
    ),
    path(
        "admin/platform/organizations/<slug:organization_slug>/series/"
        "<slug:series_slug>/editions/<slug:edition_slug>/registration/commerce/",
        registration_commerce_workspace,
        name="registration-commerce-workspace",
    ),
    path(
        "admin/platform/organizations/<slug:organization_slug>/series/"
        "<slug:series_slug>/editions/<slug:edition_slug>/registration/commerce/"
        "capacity/overall/",
        adjust_registration_capacity_page,
        name="registration-commerce-adjust-overall",
    ),
    path(
        "admin/platform/organizations/<slug:organization_slug>/series/"
        "<slug:series_slug>/editions/<slug:edition_slug>/registration/commerce/"
        "products/<uuid:product_id>/capacity/",
        adjust_registration_capacity_page,
        name="registration-commerce-adjust-product",
    ),
    path(
        "admin/platform/organizations/<slug:organization_slug>/series/"
        "<slug:series_slug>/editions/<slug:edition_slug>/registration/commerce/"
        "products/<uuid:product_id>/waitlist-offers/",
        offer_waitlist_batch_page,
        name="registration-commerce-offer-batch",
    ),
]

__all__ = ["urlpatterns"]
