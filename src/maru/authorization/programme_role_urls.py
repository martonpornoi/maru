"""Reserved Programme approval routes; never mounted in current production URLs."""

from django.urls import path

from .programme_role_views import programme_role_workspace

_BASE = "admin/programme/access/<uuid:organization_id>/<uuid:edition_id>/"
_TARGETS = (
    ("organization", "organization/"),
    ("edition", "edition/"),
    ("department", "department/<uuid:department_id>/"),
    ("resource", "room/<uuid:department_id>/<uuid:resource_binding_id>/"),
)
urlpatterns = [
    path(
        _BASE + suffix + ending,
        programme_role_workspace,
        {"level": level},
        name=f"programme-access-{level}" + ("-request" if ending else ""),
    )
    for level, suffix in _TARGETS
    for ending in ("", "<uuid:request_id>/")
]
