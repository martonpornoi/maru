"""Compatibility checks for the dormant Programme contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.checks import CheckMessage, Error, Tags, register

from maru.programme.authorization import PROGRAMME_CAPABILITY_CODES
from maru.programme.events import (
    PROGRAMME_ITEM_CHANGED_EVENT,
    PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.apps import AppConfig


def programme_dormancy_problem_codes() -> tuple[str, ...]:
    """Return deterministic defects in registration or profile dormancy.

    Returns
    -------
    tuple[str, ...]
        Sorted stable problem codes, or an empty tuple when Programme remains
        fully declared and profile-dormant.
    """
    from maru.authorization.catalog import CAPABILITIES  # noqa: PLC0415
    from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES  # noqa: PLC0415
    from maru.effects.registry import event_definition  # noqa: PLC0415
    from maru.events.adoption import (  # noqa: PLC0415
        ADOPTION_PROFILES,
        AdoptionProfileCode,
    )
    from maru.events.adoption_persistence import (  # noqa: PLC0415
        PERSISTED_ADOPTION_PROFILE_KEYS,
    )
    from maru.programme.adoption import (  # noqa: PLC0415
        PROGRAMME_ADOPTION_ADAPTERS,
        PROGRAMME_ADOPTION_CONFLICT_SOURCES,
    )

    problems: set[str] = set()
    if not PROGRAMME_CAPABILITY_CODES.issubset(CAPABILITIES):
        problems.add("catalog.capability-missing")

    definition = event_definition(PROGRAMME_ITEM_CHANGED_EVENT)
    if definition is None:
        problems.add("catalog.event-missing")
    elif definition.schema_version != PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION:
        problems.add("catalog.event-version-mismatch")

    if any(
        event_name == PROGRAMME_ITEM_CHANGED_EVENT
        for event_name, _destination in NON_EDITION_EFFECT_ROUTES
    ):
        problems.add("dormancy.non-edition-effect-route")
    if any(member.value == "programme_operations" for member in AdoptionProfileCode):
        problems.add("dormancy.profile-enum-active")
    if any(
        code == "programme_operations"
        for code, _version in PERSISTED_ADOPTION_PROFILE_KEYS
    ):
        problems.add("dormancy.profile-persistence-active")

    for profile in ADOPTION_PROFILES.values():
        if "programme" in profile.modules:
            problems.add("dormancy.module-adopted")
        if profile.capability_codes & PROGRAMME_CAPABILITY_CODES:
            problems.add("dormancy.capability-adopted")
        if any(
            route.event_name == PROGRAMME_ITEM_CHANGED_EVENT
            for route in profile.effect_routes
        ):
            problems.add("dormancy.effect-route-adopted")
        if profile.adapter_codes & frozenset(PROGRAMME_ADOPTION_ADAPTERS):
            problems.add("dormancy.adapter-adopted")
        if profile.conflict_source_codes & frozenset(
            PROGRAMME_ADOPTION_CONFLICT_SOURCES
        ):
            problems.add("dormancy.conflict-source-adopted")
    return tuple(sorted(problems))


@register(Tags.compatibility)
def check_programme_dormancy(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Fail deployment when the dormant slice is incomplete or activated.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        Optional Django application subset; Programme validates its complete
        cross-catalog dormancy contract regardless of this filter.
    **kwargs : object
        Reserved Django system-check options.

    Returns
    -------
    list[CheckMessage]
        An empty list for a complete dormant contract, or one minimized error
        carrying the deterministic problem codes.
    """
    del app_configs, kwargs
    problem_codes = programme_dormancy_problem_codes()
    if not problem_codes:
        return []
    return [
        Error(
            "The dormant Programme contract is incomplete or profile-active.",
            hint=(
                "Keep catalog declarations registered but leave every current exact "
                "profile closed. Problems: " + ", ".join(problem_codes)
            ),
            id="programme.E001",
        )
    ]


__all__ = ["check_programme_dormancy", "programme_dormancy_problem_codes"]
