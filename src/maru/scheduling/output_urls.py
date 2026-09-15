"""Dormant synthetic-installable output URLs; never included by production routes."""

from django.urls import path

from .change_notice_views import personal_programme_changes, programme_change_notices
from .continuity_views import (
    operator_programme_now,
    personal_programme_now,
    public_programme_now,
)
from .operator_entry_views import operator_entry
from .operator_output_views import operator_run_sheet
from .output_views import public_programme_timetable
from .personal_discovery_views import personal_timetable_editions
from .personal_output_views import personal_timetable

urlpatterns = [
    path(
        "my/programme/timetables/",
        personal_timetable_editions,
        name="my-programme-timetable-editions",
    ),
    path(
        "admin/programme/run-sheets/<uuid:organization_id>/<uuid:edition_id>/",
        operator_entry,
        name="programme-operator-entry",
    ),
    path(
        "programme/<uuid:organization_id>/<uuid:edition_id>/now/",
        public_programme_now,
        name="programme-public-now",
    ),
    path(
        "my/<uuid:organization_id>/<uuid:edition_id>/programme-now/",
        personal_programme_now,
        name="my-programme-now",
    ),
    path(
        "admin/programme/now/<uuid:organization_id>/<uuid:edition_id>/"
        "<str:scope_kind>/<uuid:target_id>/",
        operator_programme_now,
        name="programme-operator-now",
    ),
    path(
        "admin/programme/changes/<uuid:organization_id>/<uuid:edition_id>/",
        programme_change_notices,
        name="programme-change-notices",
    ),
    path(
        "my/<uuid:organization_id>/<uuid:edition_id>/programme-changes/",
        personal_programme_changes,
        name="my-programme-changes",
    ),
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
