"""Reserved hosting routes for isolated rehearsal, absent from production routing."""

from django.urls import path

from .host_personal_views import personal_programme_hosts
from .host_views import programme_hosts

_ORGANIZER = (
    "admin/programme/hosts/<uuid:organization_id>/<uuid:edition_id>/<uuid:item_id>/"
)
_PERSONAL = "my/programme/hosting/<uuid:organization_id>/<uuid:edition_id>/"

urlpatterns = [
    path(_ORGANIZER, programme_hosts, name="programme-hosts"),
    path(_ORGANIZER + "<slug:task>/", programme_hosts, name="programme-host-task"),
    path(
        _ORGANIZER + "host/<uuid:host_id>/<slug:task>/",
        programme_hosts,
        name="programme-host-selection",
    ),
    path(_PERSONAL, personal_programme_hosts, name="my-programme-hosts"),
    path(
        _PERSONAL + "<uuid:item_id>/<slug:task>/",
        personal_programme_hosts,
        name="my-programme-host-task",
    ),
]
