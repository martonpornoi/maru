"""Canonical native Guidance routes; route-owned actions never come from input."""

from django.urls import path

from .access_views import guidance_access_workspace
from .tasks_views import guidance_tasks
from .views import guidance_workspace

_BASE = "admin/guidance/<uuid:organization_id>/<uuid:edition_id>/"
urlpatterns = [
    path("admin/guidance-tasks/", guidance_tasks, name="guidance-tasks"),
    path(
        _BASE + "access/", guidance_access_workspace, name="guidance-access-workspace"
    ),
    path(
        _BASE + "access/new/",
        guidance_access_workspace,
        {"action": "new"},
        name="guidance-access-new",
    ),
    path(
        _BASE + "access/<uuid:assignment_id>/remove/",
        guidance_access_workspace,
        {"action": "revoke"},
        name="guidance-access-revoke",
    ),
    path(
        "admin/guidance-access/tasks/",
        guidance_access_workspace,
        {"action": "tasks"},
        name="guidance-access-tasks",
    ),
    path(
        "admin/guidance-access/requests/<uuid:request_id>/",
        guidance_access_workspace,
        {"action": "detail"},
        name="guidance-access-detail",
    ),
    path(
        "admin/guidance-access/requests/<uuid:request_id>/answer/",
        guidance_access_workspace,
        {"action": "answer"},
        name="guidance-access-answer",
    ),
    path(_BASE, guidance_workspace, name="guidance-inventory"),
    path(
        _BASE + "current/",
        guidance_workspace,
        {"action": "library"},
        name="guidance-library",
    ),
    path(_BASE + "work/", guidance_workspace, {"action": "work"}, name="guidance-work"),
    *(
        path(
            _BASE + action + "/",
            guidance_workspace,
            {"action": action},
            name=f"guidance-{action}",
        )
        for action in ("new", "settings", "stop", "resume")
    ),
    path(
        _BASE + "current/<uuid:item_id>/",
        guidance_workspace,
        {"action": "current"},
        name="guidance-current",
    ),
    path(
        _BASE + "work/<uuid:item_id>/",
        guidance_workspace,
        {"action": "detail"},
        name="guidance-detail",
    ),
    *(
        path(
            _BASE + "work/<uuid:item_id>/" + action + "/",
            guidance_workspace,
            {"action": action},
            name=f"guidance-{action}",
        )
        for action in ("edit", "request-review", "review", "withdraw", "evidence")
    ),
    *(
        path(
            _BASE + "current/<uuid:item_id>/" + action + "/",
            guidance_workspace,
            {"action": action},
            name=f"guidance-{action}",
        )
        for action in ("download", "text-download")
    ),
]
