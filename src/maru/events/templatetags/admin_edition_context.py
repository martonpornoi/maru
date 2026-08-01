"""Template access to the bootstrap-administration edition selector."""

from django import template
from django.http import HttpRequest

from maru.events.admin_context import (
    admin_edition_options,
    admin_organization_navigation,
    admin_shell_access,
)

register = template.Library()


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
