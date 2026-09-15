"""Synthetic-only personal connections alongside unchanged shared-shell routes."""

from django.urls import include, path

urlpatterns = [
    path("", include("maru.applications.programme_proposal_urls")),
    path("", include("maru.programme.host_urls")),
    path("", include("maru.scheduling.output_urls")),
    path("", include("maru.urls")),
]
