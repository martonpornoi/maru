"""Template access to the bootstrap-administration edition selector."""

from typing import TYPE_CHECKING, cast

from django import template
from django.http import HttpRequest

from maru.core.navigation import project_shell_navigation
from maru.events.admin_context import (
    admin_edition_options,
    admin_organization_navigation,
    admin_shell_access,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

register = template.Library()


@register.simple_tag(takes_context=True)
def maru_shell_navigation(context: template.Context) -> dict[str, object]:
    """Return maru shell navigation.

    Parameters
    ----------
    context : template.Context
        The resolved context for the operation.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for maru shell navigation.
    """
    request = context["request"]
    page_context = cast("Mapping[str, object]", context.flatten())
    return project_shell_navigation(
        request,
        available_apps=context.get("available_apps") or (),
        page_context=page_context,
        personal_surface=bool(context.get("maru_personal_surface")),
    )


@register.simple_tag
def admin_edition_context(request: HttpRequest) -> dict[str, object]:
    """Return admin edition context.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for admin edition context.
    """
    return admin_edition_options(request)


@register.simple_tag
def maru_admin_shell_access(request: HttpRequest) -> dict[str, bool]:
    """Return maru admin shell access.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    dict[str, bool]
        A disclosure-safe mapping for maru admin shell access.
    """
    return admin_shell_access(request)


@register.simple_tag
def maru_admin_organization_navigation(
    request: HttpRequest,
) -> tuple[dict[str, object], ...]:
    """Return maru admin organization navigation.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    tuple[dict[str, object], ...]
        A disclosure-safe mapping for maru admin organization navigation.
    """
    return admin_organization_navigation(request)
