"""Dormant synthetic-installable output URLs; never included by production routes."""

from django.urls import path

from .operator_output_views import operator_run_sheet
from .output_views import public_programme_timetable
from .personal_output_views import personal_timetable

urlpatterns = [
    path(
        "admin/programme/run-sheets/<uuid:organization_id>/<uuid:edition_id>/"
        "<str:scope_kind>/<uuid:target_id>/",
        operator_run_sheet,
        name="programme-operator-run-sheet",
    ),
    path(
        "my/<uuid:organization_id>/<uuid:edition_id>/timetable/",
        personal_timetable,
        name="my-hosting-work-timetable",
    ),
    path(
        "programme/<uuid:organization_id>/<uuid:edition_id>/timetable/",
        public_programme_timetable,
        name="programme-public-timetable",
    ),
]
