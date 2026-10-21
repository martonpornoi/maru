"""Template access to the bootstrap-administration edition selector."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django import template

from maru.core.home_guidance import HomeGuidance, project_home_guidance
from maru.core.navigation import NavigationItem, project_shell_navigation
from maru.events.admin_context import (
    admin_edition_options,
    admin_organization_navigation,
    admin_shell_access,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.http import HttpRequest

    from maru.events.adoption import AdoptionProfile
    from maru.events.models import EventEdition

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


@register.simple_tag
def maru_home_navigation(
    navigation: Mapping[str, object], selected_profile: object
) -> dict[str, tuple[NavigationItem, ...]]:
    """Select home shortcuts from the already authorized live registry.

    Parameters
    ----------
    navigation : Mapping[str, object]
        Current shell projection, including reauthorized pinned destinations.
    selected_profile : object
        Supported selected-event profile, or a false value when none is available.

    Returns
    -------
    dict[str, tuple[NavigationItem, ...]]
        Bounded work, setup, account and platform shortcuts. No new authority,
        destination, record query or operational-completion state is inferred.
    """
    groups = cast("Iterable[Mapping[str, object]]", navigation.get("groups", ()))
    items = {
        item.code: item
        for group in groups
        for item in cast("Iterable[NavigationItem]", group["items"])
        if item.kind == "destination"
    }
    work_kinds = (
        "edition.guidance",
        "edition.announcements",
        "work.workforce",
        "work.attendee-service",
        "work.people",
        "work.reports",
        "work.today",
    )
    work = tuple(
        item
        for kind in work_kinds
        for item in items.values()
        if selected_profile and item.profile_destination_kind == kind
    )
    return {
        "work": work,
        "setup": tuple(
            item
            for code, item in items.items()
            if selected_profile and code == "work.setup"
        ),
        "account": tuple(
            item for code, item in items.items() if code == "work.security"
        ),
        "platform": tuple(
            items[code]
            for code in ("platform.organizations", "platform.accounts")
            if code in items
        ),
    }


@register.simple_tag
def maru_home_guidance(
    request: HttpRequest,
    selected: EventEdition | None,
    selected_profile: AdoptionProfile | None,
) -> HomeGuidance | None:
    """Return current owner guidance for the authorized selected event.

    Parameters
    ----------
    request : HttpRequest
        Current request with its middleware-owned correlation.
    selected : EventEdition | None
        The selected event, independently authorized by its owner again.
    selected_profile : AdoptionProfile | None
        Exact profile used to filter provider invocation.

    Returns
    -------
    HomeGuidance | None
        One minimized continuation, or no contribution.
    """
    return project_home_guidance(request, selected, selected_profile)
