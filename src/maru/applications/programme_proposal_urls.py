"""Reserved personal intake routes; absent from production URL configuration."""

from django.urls import path

from .programme_decision_views import programme_decisions
from .programme_domain_reference_views import programme_domain_reference
from .programme_person_reference_views import programme_person_reference
from .programme_personal_views import programme_personal_tasks
from .programme_proposal_views import programme_proposals

_ROOT = "my/applications/programme/<uuid:organization_id>/<uuid:edition_id>/"
urlpatterns = [
    path(_ROOT + "decisions/", programme_decisions, name="my-programme-decisions"),
    path(
        _ROOT + "decisions/<uuid:decision_id>/",
        programme_decisions,
        name="my-programme-decision",
    ),
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
urlpatterns += [
    path(
        _WORK + "answer/<uuid:question_id>/domain/",
        programme_domain_reference,
        {"edit": True},
        name="my-programme-domain-select",
    ),
    path(
        _ROOT + "<uuid:proposal_id>/references/domain/<uuid:question_id>/",
        programme_domain_reference,
        name="my-programme-domain-reference",
    ),
    path(
        _ROOT
        + "<uuid:proposal_id>/revisions/<uuid:revision_id>/"
        + "references/domain/<uuid:question_id>/",
        programme_domain_reference,
        name="my-programme-frozen-domain-reference",
    ),
]
urlpatterns += [
    path(
        _WORK + "answer/<uuid:question_id>/person/",
        programme_person_reference,
        {"edit": True},
        name="my-programme-person-select",
    ),
    path(
        _ROOT + "<uuid:proposal_id>/references/person/<uuid:question_id>/",
        programme_person_reference,
        name="my-programme-person-reference",
    ),
    path(
        _ROOT
        + "<uuid:proposal_id>/revisions/<uuid:revision_id>/"
        + "references/person/<uuid:question_id>/",
        programme_person_reference,
        name="my-programme-frozen-person-reference",
    ),
]
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
