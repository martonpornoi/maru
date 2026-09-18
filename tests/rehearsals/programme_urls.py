"""Joined test-only routes, without installing a profile or changing settings.

This URLconf composes the actual owner handlers and the existing shared shell.
Importing it does not select it as ROOT_URLCONF, grant authority or launch a
server. It is preparation, not an executable or accepted integrated fixture.
Existing routes remain available to exercise excluded-product denial as well as
the ordinary foundation, representation, Venue and Workforce journeys.
"""

from django.urls import include, path

OWNER_URLCONFS = (
    "maru.events.programme_setup_urls",
    "maru.authorization.programme_role_urls",
    "maru.workforce.programme_starter_urls",
    "maru.applications.programme_call_urls",
    "maru.applications.programme_proposal_urls",
    "maru.applications.programme_review_setup_urls",
    "maru.programme.workbench_urls",
    "maru.programme.host_urls",
    "maru.scheduling.planning_urls",
    "maru.scheduling.release_workspace_urls",
    "maru.scheduling.output_urls",
)

urlpatterns = [path("", include(module)) for module in OWNER_URLCONFS]
urlpatterns.append(path("", include("maru.urls")))
