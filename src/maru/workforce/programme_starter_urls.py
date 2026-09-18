"""Reserved own-person starter routes, never mounted in current production URLs."""

from django.urls import path

from .programme_starter_creation_views import programme_starter_creation
from .programme_starter_views import programme_starter_workspace

_BASE = (
    "admin/programme/volunteer-starter/<uuid:organization_id>/"
    "<uuid:series_id>/<uuid:edition_id>/"
)
urlpatterns = [
    path(_BASE, programme_starter_workspace, name="programme-volunteer-starter"),
    path(
        _BASE + "new/",
        programme_starter_creation,
        name="programme-volunteer-starter-new",
    ),
    path(
        _BASE + "<uuid:request_id>/",
        programme_starter_workspace,
        name="programme-volunteer-starter-request",
    ),
]
