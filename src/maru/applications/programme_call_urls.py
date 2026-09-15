"""Reserved call-task routes for isolated rehearsal, not production mounting."""

from django.urls import path

from .programme_call_composer_views import programme_call_composer
from .programme_call_department_views import programme_call_departments
from .programme_call_views import programme_calls
from .programme_department_task_views import programme_department_tasks

_ROOT = (
    "admin/applications/programme-calls/<uuid:organization_id>/"
    "<uuid:edition_id>/<uuid:department_id>/"
)
urlpatterns = [
    path(
        "admin/applications/programme-calls/<uuid:organization_id>/<uuid:edition_id>/",
        programme_department_tasks,
        name="programme-department-tasks",
    ),
    path(_ROOT, programme_calls, name="programme-calls"),
    path(
        _ROOT + "departments/",
        programme_call_departments,
        name="programme-call-departments",
    ),
    path(
        _ROOT + "<uuid:call_id>/reassign/",
        programme_call_departments,
        name="programme-call-reassign",
    ),
    path(_ROOT + "new/", programme_call_composer, name="programme-call-create"),
    path(
        _ROOT + "<uuid:call_id>/compose/section/",
        programme_call_composer,
        {"task": "section"},
        name="programme-call-add-section",
    ),
    path(
        _ROOT + "<uuid:call_id>/compose/section/<int:section>/",
        programme_call_composer,
        {"task": "section"},
        name="programme-call-edit-section",
    ),
    path(
        _ROOT + "<uuid:call_id>/compose/question/<int:section>/",
        programme_call_composer,
        {"task": "question"},
        name="programme-call-add-question",
    ),
    path(
        _ROOT + "<uuid:call_id>/compose/question/<int:section>/<int:row>/",
        programme_call_composer,
        {"task": "question"},
        name="programme-call-edit-question",
    ),
    path(
        _ROOT + "<uuid:call_id>/compose/remove-section/<int:section>/",
        programme_call_composer,
        {"task": "remove-section"},
        name="programme-call-remove-section",
    ),
    path(
        _ROOT + "<uuid:call_id>/compose/remove-question/<int:section>/<int:row>/",
        programme_call_composer,
        {"task": "remove-question"},
        name="programme-call-remove-question",
    ),
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
