"""Synthetic-only output routes alongside the real shared-shell destinations."""

from django.urls import include, path

urlpatterns = [
    path("", include("maru.scheduling.output_urls")),
    path("", include("maru.urls")),
]
