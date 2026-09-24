"""Reserved stop routes, intentionally absent from production URL configuration."""

from django.urls import path

from .programme_stop_views import programme_stop

urlpatterns = [
    path(
        "admin/programme/stop/<uuid:organization_id>/<uuid:edition_id>/",
        programme_stop,
        name="programme-stop",
    ),
    path(
        "admin/programme/stop/<uuid:organization_id>/<uuid:edition_id>/<uuid:receipt_id>/",
        programme_stop,
        name="programme-stop-receipt",
    ),
]
