"""App-owned browser routes for profile-extension values."""

from django.urls import path

from maru.registration.profile_extension_views import (
    my_profile_extension_values,
    staff_profile_extension_values,
    update_my_profile_extension_value,
    update_staff_profile_extension_value,
)

urlpatterns = [
    path(
        "register/<uuid:edition_id>/profile/extensions/",
        my_profile_extension_values,
        name="my-profile-extension-values",
    ),
    path(
        "register/<uuid:edition_id>/profile/extensions/<uuid:field_id>/",
        update_my_profile_extension_value,
        name="update-my-profile-extension-value",
    ),
    path(
        (
            "admin/platform/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/<slug:edition_slug>/registration/"
            "registrations/<uuid:registration_id>/profile-extensions/"
        ),
        staff_profile_extension_values,
        name="staff-profile-extension-values",
    ),
    path(
        (
            "admin/platform/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/<slug:edition_slug>/registration/"
            "registrations/<uuid:registration_id>/profile-extensions/"
            "<uuid:field_id>/"
        ),
        update_staff_profile_extension_value,
        name="update-staff-profile-extension-value",
    ),
]

__all__ = ["urlpatterns"]
