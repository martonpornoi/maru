"""Reserved personal intake routes; absent from production URL configuration."""

from django.urls import path

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
