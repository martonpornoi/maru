"""Isolated candidate's real internal handlers, without runtime registration."""

from maru.effects import handlers as owner_handlers
from maru.effects.handlers import acknowledge_internal_fact
from maru.effects.worker import HandlerRegistration, HandlerRegistry
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)

_BASELINE_FACTORY = owner_handlers.built_in_handler_registry


def candidate_internal_handler_registry() -> HandlerRegistry:
    """Build only the candidate's explicit internal-fact delivery boundary.

    Returns
    -------
    HandlerRegistry
        Independent registry using the real Effects internal acknowledgement
        handler. Nothing is installed into the production registry. This neither
        sends a message nor supplies invitation, human or native worker evidence.
    """
    registry = HandlerRegistry()
    for route in sorted(PROGRAMME_REHEARSAL_PROFILE.effect_routes):
        if route.destination != "internal":
            raise ValueError(
                "Candidate delivery requires an explicitly reviewed handler."
            )
        registry.register(
            HandlerRegistration(
                event_name=route.event_name,
                destination=route.destination,
                handler=acknowledge_internal_fact,
            )
        )
    return registry


def joined_handler_registry() -> HandlerRegistry:
    """Preserve every built-in handler and add only explicit candidate facts.

    Returns
    -------
    HandlerRegistry
        A fresh real registry. Existing handlers are not replaced; an unexpected
        owner of a candidate internal route fails closed.
    """
    registry = _BASELINE_FACTORY()
    for route in sorted(PROGRAMME_REHEARSAL_PROFILE.effect_routes):
        if route.destination != "internal":
            raise ValueError("Unexpected candidate effect destination.")
        existing = registry.resolve(event_name=route.event_name, destination="internal")
        if existing is not None and existing is not acknowledge_internal_fact:
            raise ValueError("Unexpected candidate effect owner.")
        if existing is None:
            registry.register(
                HandlerRegistration(
                    event_name=route.event_name,
                    destination="internal",
                    handler=acknowledge_internal_fact,
                )
            )
    return registry


def install_isolated_candidate_handlers() -> None:
    """Install only in an explicitly scoped child before any worker command loads."""
    require_programme_runtime_environment()
    if owner_handlers.built_in_handler_registry is not _BASELINE_FACTORY:
        raise RuntimeError("candidate_effect_factory_changed")
    joined_handler_registry()  # Validate before changing the child-only entrypoint.
    owner_handlers.built_in_handler_registry = joined_handler_registry
