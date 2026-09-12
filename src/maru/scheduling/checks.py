"""Compatibility checks keep declared Scheduling contracts profile-dormant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.checks import CheckMessage, Error, Tags, register

from .authorization import SCHEDULING_CAPABILITIES
from .events import (
    SCHEDULING_CHANGED_EVENT,
    SCHEDULING_CHANGED_SCHEMA_VERSION,
    SCHEDULING_RELEASE_CHANGED_EVENT,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.apps import AppConfig


def scheduling_dormancy_problem_codes() -> tuple[str, ...]:
    """Check exact declarations without querying a database or activating a profile.

    Returns
    -------
    tuple[str, ...]
        Deterministic missing or accidentally activated declaration codes.
    """
    from maru.authorization.catalog import CAPABILITIES  # noqa: PLC0415
    from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES  # noqa: PLC0415
    from maru.effects.registry import event_definition  # noqa: PLC0415
    from maru.events.adoption import (  # noqa: PLC0415
        ADOPTION_MODULE_NAMESPACE_CATALOG,
        ADOPTION_PROFILES,
    )
    from maru.scheduling.adoption import (  # noqa: PLC0415
        SCHEDULING_ADOPTION_ADAPTERS,
        SCHEDULING_ADOPTION_CONFLICT_SOURCES,
    )

    problems: set[str] = set()
    if "scheduling" not in ADOPTION_MODULE_NAMESPACE_CATALOG:
        problems.add("catalog.module-missing")
    if not SCHEDULING_CAPABILITIES.issubset(CAPABILITIES):
        problems.add("catalog.capability-missing")
    event_names = {SCHEDULING_CHANGED_EVENT, SCHEDULING_RELEASE_CHANGED_EVENT}
    for name in event_names:
        event = event_definition(name)
        if event is None or event.schema_version != SCHEDULING_CHANGED_SCHEMA_VERSION:
            problems.add("catalog.event-missing-or-mismatched")
    if any(name in event_names for name, _ in NON_EDITION_EFFECT_ROUTES):
        problems.add("dormancy.non-edition-effect-route")
    for profile in ADOPTION_PROFILES.values():
        if "scheduling" in profile.modules:
            problems.add("dormancy.module-adopted")
        if profile.capability_codes & SCHEDULING_CAPABILITIES:
            problems.add("dormancy.capability-adopted")
        if profile.adapter_codes & frozenset(SCHEDULING_ADOPTION_ADAPTERS):
            problems.add("dormancy.adapter-adopted")
        if profile.conflict_source_codes & frozenset(
            SCHEDULING_ADOPTION_CONFLICT_SOURCES
        ):
            problems.add("dormancy.conflict-source-adopted")
        if any(route.event_name in event_names for route in profile.effect_routes):
            problems.add("dormancy.effect-route-adopted")
    return tuple(sorted(problems))


@register(Tags.compatibility)
def check_scheduling_dormancy(
    app_configs: Iterable[AppConfig] | None = None, **kwargs: object
) -> list[CheckMessage]:
    """Reject incomplete registration or premature current-profile activation.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        Optional Django subset; this owner validates its complete contract.
    **kwargs : object
        Reserved Django system-check arguments.

    Returns
    -------
    list[CheckMessage]
        Empty for the declared dormant boundary, otherwise one minimized error.
    """
    del app_configs, kwargs
    problems = scheduling_dormancy_problem_codes()
    if not problems:
        return []
    return [
        Error(
            "The dormant Scheduling contract is incomplete or profile-active.",
            hint="Keep exact declarations registered and current profiles closed: "
            + ", ".join(problems),
            id="scheduling.E001",
        )
    ]
