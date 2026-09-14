"""Reserved review setup routes for isolated rehearsal, not production mounting."""

from django.urls import path

from .programme_conversion_views import programme_conversion
from .programme_decider_views import programme_decider
from .programme_moderation_views import programme_moderation
from .programme_review_intake_views import programme_review_intake
from .programme_review_management_views import programme_review_management
from .programme_review_setup_views import programme_review_setup
from .programme_reviewer_views import programme_reviewer_work

_ROOT = (
    "admin/applications/programme-review/<uuid:organization_id>/"
    "<uuid:edition_id>/<uuid:department_id>/"
)
urlpatterns = [
    path(
        _ROOT + "conversion/", programme_conversion, name="programme-conversion-sources"
    ),
    path(
        _ROOT + "conversion/<uuid:decision_id>/",
        programme_conversion,
        name="programme-conversion",
    ),
    path(_ROOT + "decisions/", programme_decider, name="programme-decision-cases"),
    path(
        _ROOT + "decisions/<uuid:case_id>/",
        programme_decider,
        name="programme-decision-case",
    ),
    *[
        path(
            _ROOT + "decisions/<uuid:case_id>/" + task + "/",
            programme_decider,
            {"task": task},
            name="programme-decision-" + task,
        )
        for task in ("decide", "context", "answers", "evidence", "messages")
    ],
    path(_ROOT + "moderation/", programme_moderation, name="programme-moderation"),
    path(
        _ROOT + "moderation/<uuid:case_id>/",
        programme_moderation,
        name="programme-moderation-case",
    ),
    *[
        path(
            _ROOT + "moderation/<uuid:case_id>/" + task + "/",
            programme_moderation,
            {"task": task},
            name="programme-moderation-" + task,
        )
        for task in ("moderate", "advance", "reopen", "context", "answers", "evidence")
    ],
    path(_ROOT + "mine/", programme_reviewer_work, name="programme-review-mine"),
    path(
        _ROOT + "mine/<uuid:case_id>/<uuid:assignment_id>/",
        programme_reviewer_work,
        name="programme-review-own-assignment",
    ),
    *[
        path(
            _ROOT + "mine/<uuid:case_id>/<uuid:assignment_id>/" + task + "/",
            programme_reviewer_work,
            {"task": task},
            name="programme-review-own-" + task,
        )
        for task in (
            "clear",
            "recuse",
            "score",
            "discuss",
            "context",
            "answers",
            "evidence",
        )
    ],
    path(_ROOT + "cases/", programme_review_management, name="programme-review-cases"),
    path(
        _ROOT + "cases/<uuid:case_id>/",
        programme_review_management,
        name="programme-review-case",
    ),
    path(
        _ROOT + "cases/<uuid:case_id>/assign/",
        programme_review_management,
        {"task": "assign"},
        name="programme-review-assign",
    ),
    path(
        _ROOT + "cases/<uuid:case_id>/assignments/<uuid:assignment_id>/remove/",
        programme_review_management,
        {"task": "remove"},
        name="programme-review-remove",
    ),
    path(
        _ROOT + "<uuid:call_id>/policies/<int:version>/cases/",
        programme_review_intake,
        name="programme-review-intake",
    ),
    path(
        _ROOT + "<uuid:call_id>/policies/<int:version>/cases/<uuid:revision_id>/",
        programme_review_intake,
        name="programme-review-open",
    ),
    path(_ROOT, programme_review_setup, name="programme-review-setup"),
    path(
        _ROOT + "<uuid:call_id>/",
        programme_review_setup,
        name="programme-review-policy-compose",
    ),
    path(
        _ROOT + "<uuid:call_id>/policies/<int:version>/",
        programme_review_setup,
        name="programme-review-policy",
    ),
]
