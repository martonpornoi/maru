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
    path(
        "my-events/archive/<int:pk>/",
        views.archived_participation_detail_view,
        name="archived_participation_detail",
    ),
    path("accounts/", views.access_grant_list_view, name="access_grant_list"),
    path("accounts/users/", views.user_directory_view, name="user_directory"),
    path(
        "projects/<slug:slug>/users/",
        views.user_directory_view,
        name="project_user_directory",
    ),
    path("volunteers/", views.volunteer_group_list_view, name="volunteer_groups"),
    path(
        "volunteers/new/",
        views.create_volunteer_group_view,
        name="create_volunteer_group",
    ),
    path(
        "volunteers/<slug:slug>/",
        views.volunteer_group_detail_view,
        name="volunteer_group_detail",
    ),
    path(
        "volunteers/<slug:slug>/edit/",
        views.edit_volunteer_group_view,
        name="edit_volunteer_group",
    ),
    path(
        "volunteers/<slug:slug>/delete/",
        views.delete_volunteer_group_view,
        name="delete_volunteer_group",
    ),
    path("statistics/", views.statistics_view, name="statistics"),
    path(
        "projects/<slug:slug>/statistics/",
        views.statistics_view,
        name="project_statistics",
    ),
    path(
        "setup/user-colors/",
        views.user_tile_color_rule_list_view,
        name="user_tile_color_rules",
    ),
    path(
        "projects/<slug:slug>/setup/user-colors/",
        views.user_tile_color_rule_list_view,
        name="project_user_tile_color_rules",
    ),
    path(
        "setup/user-colors/<int:pk>/edit/",
        views.edit_user_tile_color_rule_view,
        name="edit_user_tile_color_rule",
    ),
    path(
        "setup/user-colors/<int:pk>/delete/",
        views.delete_user_tile_color_rule_view,
        name="delete_user_tile_color_rule",
    ),
    path("setup/roles/", views.roles_access_view, name="roles_access"),
    path(
        "projects/<slug:slug>/setup/roles/",
        views.roles_access_view,
        name="project_roles_access",
    ),
    path(
        "setup/roles/<int:pk>/edit/",
        views.edit_role_definition_view,
        name="edit_role_definition",
    ),
    path(
        "setup/statuses/",
        views.statuses_benefits_view,
        name="statuses_benefits",
    ),
    path(
        "projects/<slug:slug>/setup/statuses/",
        views.statuses_benefits_view,
        name="project_statuses_benefits",
    ),
    path("setup/labels/", views.labels_view, name="labels"),
    path(
        "projects/<slug:slug>/setup/labels/",
        views.labels_view,
        name="project_labels",
    ),
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
        "accounts/<int:pk>/history/",
        views.access_grant_history_view,
        name="access_grant_history",
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
    path(
        "profiles/<int:pk>/edit/",
        views.profile_edit_view,
        name="profile_edit_detail",
    ),
    path("profiles/<int:pk>/", views.profile_detail_view, name="profile_detail"),
    path("profile/", views.my_profile_view, name="my_profile"),
    path("profile/edit/", views.profile_edit_view, name="profile_edit"),
]
