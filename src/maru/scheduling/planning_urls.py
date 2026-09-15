"""Reserved canonical timetable URL for isolated composition, not production wiring."""

from django.urls import path

from .planning_workspace_views import programme_timetable_workspace

urlpatterns = [
    path(
        "admin/platform/organizations/<uuid:organization_id>/series/<uuid:series_id>/"
        "editions/<uuid:edition_id>/programme/timetable/",
        programme_timetable_workspace,
        name="programme-timetable-workspace",
    ),
]
