"""Reserved personal intake routes; absent from production URL configuration."""

from django.urls import path

from .programme_personal_views import programme_personal_tasks
from .programme_proposal_views import programme_proposals

_ROOT = "my/applications/programme/<uuid:organization_id>/<uuid:edition_id>/"
urlpatterns = [
    path(_ROOT, programme_proposals, name="my-programme-proposals"),
    path(
        _ROOT + "calls/",
        programme_proposals,
        {"task": "calls"},
        name="my-programme-calls",
    ),
    path(
        _ROOT + "calls/<uuid:call_id>/start/",
        programme_proposals,
        {"task": "start"},
        name="my-programme-start",
    ),
    path(
        _ROOT + "<uuid:proposal_id>/",
        programme_proposals,
        {"task": "detail"},
        name="my-programme-proposal",
    ),
]

_WORK = _ROOT + "<uuid:proposal_id>/work/"
urlpatterns += [path(_WORK, programme_personal_tasks, name="my-programme-work")]
for _action in (
    "selection",
    "profile",
    "invite",
    "reinvite",
    "accept-invitation",
    "decline-invitation",
    "leave",
    "seal",
    "reopen",
    "frozen",
    "acknowledge",
    "decline-revision",
    "submit",
    "withdraw",
):
    urlpatterns.append(
        path(
            _WORK + _action + "/",
            programme_personal_tasks,
            {"action": _action},
            name=f"my-programme-{_action}",
        )
    )
for _action in ("answer", "remove"):
    urlpatterns.append(
        path(
            _WORK + _action + "/<uuid:selected_id>/",
            programme_personal_tasks,
            {"action": _action},
            name=f"my-programme-{_action}",
        )
    )
