"""Optional Programme continuations on the existing lazy organizer Shift pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.template.response import TemplateResponse

from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.workspace_navigation import programme_workspace_links

if TYPE_CHECKING:
    from django.http import HttpRequest

    from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink


def organizer_programme_response(
    request: HttpRequest, template: str, context: dict[str, Any], *, status: int = 200
) -> TemplateResponse:
    """Attach independently admitted navigation without redispatching a Shift action.

    Parameters
    ----------
    request : HttpRequest
        Existing authenticated organizer request with trusted correlation ID.
    template : str
        Existing organizer list or detail template.
    context : dict[str, Any]
        Already authorized native context, including original bound forms.
    status : int, default=200
        Original success, validation or command-conflict status.

    Returns
    -------
    TemplateResponse
        Lazy native response whose optional links are rechecked after rendering.

    Notes
    -----
    No inventory, selected candidate, personnel directory or command is loaded.
    If an optional destination moves, rerender only the same context without links;
    keep the native forms, errors, versions, retry keys, headers and status intact.
    Normal destination admission and source-page audits remain with their owners.
    """
    context["programme_workspace_links"] = ()
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        return TemplateResponse(request, template, context, status=status)
    scope = SchedulingReadRequest(
        actor_id,
        context["organization"].id,
        context["edition"].id,
        UUID(request.correlation_id),  # type: ignore[attr-defined]
    )

    def links() -> tuple[ProgrammeWorkspaceLink, ...]:
        return programme_workspace_links(
            scope,
            current="shifts",
            series_id=context["convention_series"].id,
            urlconf=getattr(request, "urlconf", None),
        )

    context["programme_workspace_links"] = links()
    response = TemplateResponse(request, template, context, status=status)

    def finish(rendered: TemplateResponse) -> None:
        if context["programme_workspace_links"] != links():
            context["programme_workspace_links"] = ()
            rendered.content = rendered.rendered_content

    response.add_post_render_callback(finish)
    return response
