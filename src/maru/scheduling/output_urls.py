"""Dormant synthetic-installable output URLs; never included by production routes."""

from django.urls import path

from .output_views import public_programme_timetable
from .personal_output_views import personal_timetable

urlpatterns = [
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
