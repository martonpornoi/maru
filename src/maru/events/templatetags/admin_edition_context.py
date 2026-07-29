"""Template access to the bootstrap-administration edition selector."""

from django import template
from django.http import HttpRequest

from maru.events.admin_context import admin_edition_options

register = template.Library()


@register.simple_tag
def admin_edition_context(request: HttpRequest) -> dict[str, object]:
    return admin_edition_options(request)
