"""Ordinary platform routes for the explicit Announcements-only setup."""

from django.urls import path

from .announcements_setup_views import announcements_setup_workspace

_BASE = "admin/platform/setup/announcements/"
urlpatterns = [
    path(_BASE, announcements_setup_workspace, name="announcements-setup"),
    path(
        _BASE + "new/",
        announcements_setup_workspace,
        {"mode": "new_foundation"},
        name="announcements-setup-new",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/",
        announcements_setup_workspace,
        {"mode": "existing_organization"},
        name="announcements-setup-organization",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/series/<uuid:series_id>/",
        announcements_setup_workspace,
        {"mode": "existing_series"},
        name="announcements-setup-series",
    ),
]
