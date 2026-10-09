"""Ordinary platform routes for the explicit Guidance-only setup."""

from django.urls import path

from .guidance_activation_views import guidance_activation_workspace
from .guidance_setup_views import guidance_setup_workspace

_BASE = "admin/platform/setup/guidance/"
urlpatterns = [
    path(
        _BASE + "activate/<uuid:organization_id>/<uuid:edition_id>/",
        guidance_activation_workspace,
        {"action": "start"},
        name="guidance-activation-start",
    ),
    path(
        "admin/guidance-setup/tasks/",
        guidance_activation_workspace,
        name="guidance-activation-tasks",
    ),
    path(
        "admin/guidance-setup/requests/<uuid:request_id>/",
        guidance_activation_workspace,
        {"action": "detail"},
        name="guidance-activation-detail",
    ),
    *(
        path(
            "admin/guidance-setup/requests/<uuid:request_id>/" + action + "/",
            guidance_activation_workspace,
            {"action": action},
            name=f"guidance-activation-{action}",
        )
        for action in ("answer", "apply")
    ),
    path(_BASE, guidance_setup_workspace, name="guidance-setup"),
    path(
        _BASE + "new/",
        guidance_setup_workspace,
        {"mode": "new_foundation"},
        name="guidance-setup-new",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/",
        guidance_setup_workspace,
        {"mode": "existing_organization"},
        name="guidance-setup-organization",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/series/<uuid:series_id>/",
        guidance_setup_workspace,
        {"mode": "existing_series"},
        name="guidance-setup-series",
    ),
]
