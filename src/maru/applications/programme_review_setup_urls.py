"""Reserved review setup routes for isolated rehearsal, not production mounting."""

from django.urls import path

from .programme_review_intake_views import programme_review_intake
from .programme_review_setup_views import programme_review_setup

_ROOT = (
    "admin/applications/programme-review/<uuid:organization_id>/"
    "<uuid:edition_id>/<uuid:department_id>/"
)
urlpatterns = [
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
