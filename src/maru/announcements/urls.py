"""Canonical native Announcements routes with route-owned actions."""

from django.urls import path

from .views import announcements_workspace

_BASE = "admin/announcements/<uuid:organization_id>/<uuid:edition_id>/"
urlpatterns = [
    path(_BASE, announcements_workspace, name="announcements-inventory"),
    *(
        path(
            _BASE + action + "/",
            announcements_workspace,
            {"action": action},
            name=f"announcements-{action}",
        )
        for action in ("new", "settings", "stop", "resume")
    ),
    path(
        _BASE + "<uuid:announcement_id>/",
        announcements_workspace,
        {"action": "detail"},
        name="announcements-detail",
    ),
    *(
        path(
            _BASE + "<uuid:announcement_id>/" + action + "/",
            announcements_workspace,
            {"action": action},
            name=f"announcements-{action}",
        )
        for action in (
            "edit",
            "request-review",
            "review",
            "report",
            "cancel",
            "copy",
            "download",
            "text-download",
            "evidence",
        )
    ),
    path(
        _BASE + "<uuid:announcement_id>/reports/<uuid:report_id>/correct/",
        announcements_workspace,
        {"action": "correct-report"},
        name="announcements-correct-report",
    ),
]
