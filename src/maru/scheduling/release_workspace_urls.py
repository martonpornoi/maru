"""Reserved release-task routes for isolated rehearsal; not production URL wiring."""

from django.urls import path

from .release_workspace_views import programme_release_workspace

_ROOT = (
    "admin/platform/organizations/<uuid:organization_id>/series/<uuid:series_id>/"
    "editions/<uuid:edition_id>/programme/release/"
)
urlpatterns = [
    path(_ROOT, programme_release_workspace, name="programme-release-workspace"),
    path(
        _ROOT + "<slug:task>/",
        programme_release_workspace,
        name="programme-release-task",
    ),
]
