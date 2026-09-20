"""Reserved archive rehearsal routes; absent from production URL configuration."""

from django.urls import path

from .archive_views import programme_archive, programme_archive_download

urlpatterns = [
    path(
        "admin/programme/archive/<uuid:organization_id>/<uuid:edition_id>/",
        programme_archive,
        name="programme-archive",
    ),
    path(
        "admin/programme/archive/<uuid:organization_id>/<uuid:edition_id>/<uuid:task_id>/",
        programme_archive,
        name="programme-archive-task",
    ),
    path(
        "admin/programme/archive/<uuid:organization_id>/<uuid:edition_id>/<uuid:task_id>/download/",
        programme_archive_download,
        name="programme-archive-download",
    ),
]
