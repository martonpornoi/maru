"""Reserved call-task routes for isolated rehearsal, not production mounting."""

from django.urls import path

from .programme_call_views import programme_calls

_ROOT = (
    "admin/applications/programme-calls/<uuid:organization_id>/"
    "<uuid:edition_id>/<uuid:department_id>/"
)
urlpatterns = [
    path(_ROOT, programme_calls, name="programme-calls"),
    path(
        _ROOT + "<uuid:call_id>/<slug:task>/",
        programme_calls,
        name="programme-call-task",
    ),
    path(
        _ROOT + "<uuid:call_id>/<slug:task>/<int:row>/",
        programme_calls,
        name="programme-call-row",
    ),
]
