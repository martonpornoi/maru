"""Closed route contract for the registration profile-field catalog."""

from django.urls import resolve, reverse

from maru.registration.setup_definition_views import (
    registration_setup_profile_fields_dispatch,
)


def test_profile_field_catalog_uses_one_get_and_post_dispatch_route() -> None:
    location = reverse(
        "registration-setup-profile-fields",
        kwargs={
            "organization_slug": "synthetic-organization",
            "series_slug": "synthetic-series",
            "edition_slug": "synthetic-edition",
        },
    )

    match = resolve(location)

    assert match.func is registration_setup_profile_fields_dispatch
