"""Template access to the bootstrap-administration edition selector."""

from collections.abc import Mapping
from typing import cast

from django import template
from django.http import HttpRequest

from maru.core.navigation import project_shell_navigation
from maru.events.admin_context import (
    admin_edition_options,
    admin_organization_navigation,
    admin_shell_access,
)

register = template.Library()


@register.simple_tag(takes_context=True)
def maru_shell_navigation(context: template.Context) -> dict[str, object]:
    request = context["request"]
    page_context = cast(Mapping[str, object], context.flatten())
    return project_shell_navigation(
        request,
        available_apps=context.get("available_apps") or (),
        page_context=page_context,
        personal_surface=bool(context.get("maru_personal_surface")),
    )


@register.simple_tag
def admin_edition_context(request: HttpRequest) -> dict[str, object]:
    return admin_edition_options(request)


@register.simple_tag
def maru_admin_shell_access(request: HttpRequest) -> dict[str, bool]:
    return admin_shell_access(request)


@register.simple_tag
def maru_admin_organization_navigation(
    request: HttpRequest,
) -> tuple[dict[str, object], ...]:
    return admin_organization_navigation(request)
