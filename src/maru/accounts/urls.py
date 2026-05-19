from __future__ import annotations

from django.contrib.auth.views import LogoutView
from django.urls import path

from maru.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path(
        "oauth/google/start/",
        views.google_login_start_view,
        name="google_login_start",
    ),
    path(
        "oauth/google/callback/",
        views.google_oauth_callback_view,
        name="google_oauth_callback",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("my-events/", views.my_events_view, name="my_events"),
    path("accounts/", views.access_grant_list_view, name="access_grant_list"),
    path(
        "accounts/export.csv",
        views.export_access_grants_view,
        name="export_access_grants",
    ),
    path(
        "accounts/import/",
        views.import_access_grants_view,
        name="import_access_grants",
    ),
    path("accounts/new/", views.create_access_grant_view, name="create_access_grant"),
    path(
        "accounts/<int:pk>/edit/",
        views.edit_access_grant_view,
        name="edit_access_grant",
    ),
    path(
        "accounts/<int:pk>/profile/unlock/",
        views.unlock_access_grant_profile_view,
        name="unlock_access_grant_profile",
    ),
    path(
        "accounts/<int:pk>/profile/lock/",
        views.lock_access_grant_profile_view,
        name="lock_access_grant_profile",
    ),
    path(
        "accounts/audit/<int:pk>/",
        views.access_grant_audit_log_detail_view,
        name="access_grant_audit_log_detail",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.mark_notification_read_view,
        name="mark_notification_read",
    ),
    path("profiles/<int:pk>/", views.profile_detail_view, name="profile_detail"),
    path("profile/edit/", views.profile_edit_view, name="profile_edit"),
]
