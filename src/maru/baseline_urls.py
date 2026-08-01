"""Deliberately minimal browser routes for the page-by-page rebuild."""

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from maru.core.views import (
    baseline_administration_home,
    baseline_clear_event_edition,
    baseline_convention_series_record,
    baseline_create_convention_series,
    baseline_create_event_edition,
    baseline_create_organization,
    baseline_delete_organization,
    baseline_event_edition_record,
    baseline_organization_record,
    baseline_root,
    baseline_select_event_edition,
)
from maru.identity.forms import EmailOrHandleAuthenticationForm
from maru.urls import API_URLPATTERNS, PLATFORM_URLPATTERNS

urlpatterns = [
    path("", baseline_root, name="baseline-root"),
    path(
        "accounts/login/",
        LoginView.as_view(
            template_name="core/baseline_login.html",
            authentication_form=EmailOrHandleAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="staff-login",
    ),
    path("accounts/logout/", LogoutView.as_view(), name="staff-logout"),
    path("admin/", baseline_administration_home, name="baseline-admin-home"),
    path(
        "admin/organizations/new/",
        baseline_create_organization,
        name="baseline-create-organization",
    ),
    path(
        "admin/organizations/<slug:organization_slug>/",
        baseline_organization_record,
        name="baseline-organization-record",
    ),
    path(
        "admin/organizations/<slug:organization_slug>/series/new/",
        baseline_create_convention_series,
        name="baseline-create-convention-series",
    ),
    path(
        ("admin/organizations/<slug:organization_slug>/series/<slug:series_slug>/"),
        baseline_convention_series_record,
        name="baseline-convention-series-record",
    ),
    path(
        (
            "admin/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/new/"
        ),
        baseline_create_event_edition,
        name="baseline-create-event-edition",
    ),
    path(
        (
            "admin/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/<slug:edition_slug>/"
        ),
        baseline_event_edition_record,
        name="baseline-event-edition-record",
    ),
    path(
        (
            "admin/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/<slug:edition_slug>/select/"
        ),
        baseline_select_event_edition,
        name="baseline-select-event-edition",
    ),
    path(
        (
            "admin/organizations/<slug:organization_slug>/series/"
            "<slug:series_slug>/editions/<slug:edition_slug>/clear/"
        ),
        baseline_clear_event_edition,
        name="baseline-clear-event-edition",
    ),
    path(
        "admin/organizations/<slug:organization_slug>/delete/",
        baseline_delete_organization,
        name="baseline-delete-organization",
    ),
    *PLATFORM_URLPATTERNS,
    *API_URLPATTERNS,
]
