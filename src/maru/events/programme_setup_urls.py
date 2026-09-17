"""Reserved Programme setup routes, absent from current production URL patterns."""

from django.urls import path

from .programme_setup_views import programme_setup_receipt, programme_setup_workspace

_BASE = "admin/platform/setup/programme-operations/"
urlpatterns = [
    path(_BASE, programme_setup_workspace, name="programme-setup"),
    path(
        _BASE + "new/",
        programme_setup_workspace,
        {"mode": "new_foundation"},
        name="programme-setup-new",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/",
        programme_setup_workspace,
        {"mode": "existing_organization"},
        name="programme-setup-organization",
    ),
    path(
        _BASE + "organization/<uuid:organization_id>/series/<uuid:series_id>/",
        programme_setup_workspace,
        {"mode": "existing_series"},
        name="programme-setup-series",
    ),
    path(
        _BASE
        + "receipt/<uuid:organization_id>/<uuid:series_id>/"
        + "<uuid:edition_id>/<uuid:receipt_id>/",
        programme_setup_receipt,
        name="programme-setup-receipt",
    ),
]
