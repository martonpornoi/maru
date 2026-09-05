"""Compatibility checks for dormant Programme call and proposal contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.checks import CheckMessage, Error, Tags, register

from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_IMPORT_ADAPTER,
    APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
    APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
    APPLICATION_PROGRAMME_SELF_ADAPTER,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_PROGRAMME_CAPABILITY_CODES,
)
from maru.applications.programme_events import (
    APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION,
    APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
)
from maru.applications.programme_import_authorization import (
    APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
    APPLICATIONS_IMPORT_PROGRAMME,
)
from maru.applications.programme_import_events import (
    APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION,
)
from maru.applications.programme_review_authorization import (
    PROGRAMME_REVIEW_CAPABILITIES,
)
from maru.applications.programme_review_events import PROGRAMME_REVIEW_CHANGED_EVENT

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.apps import AppConfig

_PROGRAMME_APPLICATION_EVENTS = frozenset(
    {
        APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
        APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
        APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT,
        PROGRAMME_REVIEW_CHANGED_EVENT,
    }
)
_PROGRAMME_APPLICATION_ADAPTERS = frozenset(
    {
        APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
        APPLICATION_PROGRAMME_SELF_ADAPTER,
        APPLICATION_PROGRAMME_IMPORT_ADAPTER,
    }
)
_ALL_PROGRAMME_APPLICATION_CAPABILITIES = (
    APPLICATIONS_PROGRAMME_CAPABILITY_CODES
    | PROGRAMME_REVIEW_CAPABILITIES
    | {
        APPLICATIONS_IMPORT_PROGRAMME,
        APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
    }
)


def applications_programme_dormancy_problem_codes() -> tuple[str, ...]:
    """Return deterministic defects in the registered dormant contract.

    Returns
    -------
    tuple[str, ...]
        Sorted stable problem codes, or an empty tuple when every declaration
        is registered and every current executable profile remains closed.
    """
    from maru.applications.adoption import (  # noqa: PLC0415
        APPLICATIONS_ADOPTION_ADAPTERS,
        TARGET_ADAPTER_CODES,
    )
    from maru.authorization.catalog import CAPABILITIES  # noqa: PLC0415
    from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES  # noqa: PLC0415
    from maru.effects.handlers import (  # noqa: PLC0415
        ACKNOWLEDGED_DORMANT_EVENTS,
    )
    from maru.effects.registry import event_definition  # noqa: PLC0415
    from maru.events.adoption import ADOPTION_PROFILES  # noqa: PLC0415

    problems: set[str] = set()
    if not _ALL_PROGRAMME_APPLICATION_CAPABILITIES.issubset(CAPABILITIES):
        problems.add("catalog.capability-missing")
    if not _PROGRAMME_APPLICATION_ADAPTERS.issubset(APPLICATIONS_ADOPTION_ADAPTERS):
        problems.add("catalog.adapter-missing")
    if (
        TARGET_ADAPTER_CODES.get(APPLICATION_PROGRAMME_ITEM_TARGET_KIND)
        != APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER
    ):
        problems.add("catalog.target-adapter-mismatch")

    for event_name in _PROGRAMME_APPLICATION_EVENTS:
        definition = event_definition(event_name)
        if definition is None:
            problems.add("catalog.event-missing")
        elif definition.schema_version != (
            APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION
            if event_name == APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT
            else APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION
        ):
            problems.add("catalog.event-version-mismatch")
        if event_name not in ACKNOWLEDGED_DORMANT_EVENTS:
            problems.add("dormancy.event-not-acknowledged")

    if any(
        event_name in _PROGRAMME_APPLICATION_EVENTS
        for event_name, _destination in NON_EDITION_EFFECT_ROUTES
    ):
        problems.add("dormancy.non-edition-effect-route")

    for profile in ADOPTION_PROFILES.values():
        if profile.capability_codes & _ALL_PROGRAMME_APPLICATION_CAPABILITIES:
            problems.add("dormancy.capability-adopted")
        if profile.adapter_codes & _PROGRAMME_APPLICATION_ADAPTERS:
            problems.add("dormancy.adapter-adopted")
        if any(
            route.event_name in _PROGRAMME_APPLICATION_EVENTS
            for route in profile.effect_routes
        ):
            problems.add("dormancy.effect-route-adopted")
    return tuple(sorted(problems))


@register(Tags.compatibility)
def check_applications_programme_dormancy(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Fail deployment when Programme application declarations activate.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        Optional Django application subset; the complete cross-catalog
        contract is checked regardless of this filter.
    **kwargs : object
        Reserved Django system-check options.

    Returns
    -------
    list[CheckMessage]
        Empty for a complete dormant contract, otherwise one minimized error.
    """
    del app_configs, kwargs
    problem_codes = applications_programme_dormancy_problem_codes()
    if not problem_codes:
        return []
    return [
        Error(
            "The Applications Programme contract is incomplete or profile-active.",
            hint=(
                "Keep declarations registered while every current exact profile "
                "remains closed. Problems: " + ", ".join(problem_codes)
            ),
            id="applications.E002",
        )
    ]


__all__ = [
    "applications_programme_dormancy_problem_codes",
    "check_applications_programme_dormancy",
]
