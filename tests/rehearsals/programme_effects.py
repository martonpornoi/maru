"""Isolated candidate's real internal handlers, without runtime registration."""

from maru.effects.handlers import acknowledge_internal_fact
from maru.effects.worker import HandlerRegistration, HandlerRegistry
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE


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
