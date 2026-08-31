"""Import-safe deployment checks for governed effect routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.checks import CheckMessage, Error, Tags, register
from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.apps import AppConfig


@register(Tags.compatibility)
def check_governed_effect_routes(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Reject governed routes without one registered event and handler.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        The installed Django application configurations to inspect.
    **kwargs : object
        Keyword arguments forwarded by Django's check framework.

    Returns
    -------
    list[CheckMessage]
        A value-safe deployment error when a governed route is unresolved.
    """
    del app_configs, kwargs

    # Both imports remain inside the check so Events can own the manifests
    # without taking an eager dependency on Effects handler construction.
    from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES  # noqa: PLC0415
    from maru.effects.handlers import built_in_handler_registry  # noqa: PLC0415
    from maru.effects.registry import event_definition  # noqa: PLC0415
    from maru.events.adoption import ADOPTION_PROFILES  # noqa: PLC0415

    try:
        handlers = built_in_handler_registry()
    except ValidationError:
        return [_unresolved_effect_route_error()]

    routes = set(NON_EDITION_EFFECT_ROUTES) | {
        (route.event_name, route.destination)
        for profile in ADOPTION_PROFILES.values()
        for route in profile.effect_routes
    }
    if any(
        event_definition(event_name) is None
        or handlers.resolve(
            event_name=event_name,
            destination=destination,
        )
        is None
        for event_name, destination in routes
    ):
        return [_unresolved_effect_route_error()]
    return []


def _unresolved_effect_route_error() -> Error:
    return Error(
        "A governed effect route is unresolved.",
        hint=(
            "Pin only versioned Effects events and destinations owned by exactly "
            "one built-in handler."
        ),
        id="effects.E001",
    )


__all__ = ["check_governed_effect_routes"]
