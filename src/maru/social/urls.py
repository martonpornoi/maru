from __future__ import annotations

from django.urls import path

from maru.social import views

app_name = "social"

urlpatterns = [
    path("social-media/", views.social_post_list_view, name="list"),
    path(
        "projects/<slug:slug>/social-media/",
        views.social_post_list_view,
        name="project_list",
    ),
    path("social-media/new/", views.create_social_post_view, name="create"),
    path(
        "projects/<slug:slug>/social-media/new/",
        views.create_social_post_view,
        name="project_create",
    ),
    path("social-media/<int:pk>/", views.social_post_detail_view, name="detail"),
    path(
        "projects/<slug:slug>/social-media/<int:pk>/",
        views.social_post_detail_view,
        name="project_detail",
    ),
    path("social-media/<int:pk>/edit/", views.edit_social_post_view, name="edit"),
    path(
        "projects/<slug:slug>/social-media/<int:pk>/edit/",
        views.edit_social_post_view,
        name="project_edit",
    ),
]
