"""Exact scope and edition-profile checks for durable effect delivery routes."""

from collections.abc import Iterable, Mapping
from uuid import UUID

from django.core.exceptions import ValidationError

EFFECT_PROFILE_NOT_ALLOWED = "effect_profile_not_allowed"

_PAYLOAD_SCOPED_AUTHORIZATION_EVENTS = frozenset(
    {
        "authorization.capability.delegated.v1",
        "authorization.capability.direct_granted.v1",
        "authorization.capability.revoked.v1",
        "authorization.role.assigned.v1",
        "authorization.role.revoked.v1",
    }
)
_EDITION_AUTHORIZATION_SCOPE_LEVELS = frozenset(
    {
        "edition",
        "department",
        "resource",
    }
)


def validated_effect_route_catalog(
    routes: Iterable[tuple[str, str]],
) -> frozenset[tuple[str, str]]:
    """Freeze route declarations after rejecting duplicate entries.

    Parameters
    ----------
    routes : Iterable[tuple[str, str]]
        Literal event and destination declarations in source order.

    Returns
    -------
    frozenset[tuple[str, str]]
        The unique closed route catalog.

    Raises
    ------
    RuntimeError
        If a route is declared more than once.
    """
    declared = tuple(routes)
    catalog = frozenset(declared)
    if len(catalog) != len(declared):
        raise RuntimeError("Effect route declarations must be unique.")
    return catalog


NON_EDITION_EFFECT_ROUTES = validated_effect_route_catalog(
    (
        ("authorization.capability.delegated.v1", "internal"),
        ("authorization.capability.direct_granted.v1", "internal"),
        ("authorization.capability.revoked.v1", "internal"),
        ("authorization.role.assigned.v1", "internal"),
        ("authorization.role.revoked.v1", "internal"),
        ("authorization.role_bundle.version_created.v1", "internal"),
        ("charities.media.changed.v1", "internal"),
        ("charities.partner.changed.v1", "internal"),
        ("identity.account_restriction.applied.v1", "internal"),
        ("identity.account_restriction.applied.v1", "notifications"),
        ("logistics.record.changed.v1", "internal"),
        ("organizations.convention_series.created.v1", "internal"),
        ("organizations.convention_series.updated.v1", "internal"),
        ("organizations.representation.changed.v1", "internal"),
        ("system.effect.probe_requested.v1", "internal"),
        ("venues.record.changed.v1", "internal"),
    )
)


def effect_delivery_is_allowed(
    *,
    organization_id: UUID,
    event_edition_id: UUID | None,
    event_name: str,
    destination: str,
    payload: Mapping[str, object],
) -> bool:
    """Return whether one durable delivery is permitted for its exact scope.

    Platform- and organization-scoped facts declare that scope with a null
    edition identifier and retain their existing non-edition delivery policy.
    Edition-scoped facts must resolve an exact tenant-bound edition profile and
    an explicitly pinned event/destination route.

    Parameters
    ----------
    organization_id : UUID
        The organization that owns the domain event.
    event_edition_id : UUID | None
        The exact edition identifier, or ``None`` for an explicit non-edition
        fact.
    event_name : str
        The registered versioned domain-event name.
    destination : str
        The registered delivery destination.
    payload : Mapping[str, object]
        The validated event payload used to confirm hybrid authorization scope.

    Returns
    -------
    bool
        ``True`` only for an explicit non-edition fact or a route pinned by the
        exact persisted edition profile.
    """
    if event_name in _PAYLOAD_SCOPED_AUTHORIZATION_EVENTS:
        scope_level = payload.get("scope_level")
        if event_edition_id is None:
            return (
                scope_level == "organization"
                and (event_name, destination) in NON_EDITION_EFFECT_ROUTES
            )
        if scope_level not in _EDITION_AUTHORIZATION_SCOPE_LEVELS:
            return False

    if event_edition_id is None:
        return (event_name, destination) in NON_EDITION_EFFECT_ROUTES

    # Keep cross-module imports lazy so the Events profile catalog can validate
    # effect identifiers without creating an import cycle through the worker.
    from maru.events.adoption import profile_allows_effect  # noqa: PLC0415
    from maru.events.queries import (  # noqa: PLC0415
        edition_adoption_profile_reference,
    )

    profile = edition_adoption_profile_reference(
        organization_id=organization_id,
        edition_id=event_edition_id,
    )
    return profile is not None and profile_allows_effect(
        profile.code,
        profile.version,
        event_name,
        destination,
    )


def require_effect_delivery_allowed(
    *,
    organization_id: UUID,
    event_edition_id: UUID | None,
    event_name: str,
    destination: str,
    payload: Mapping[str, object],
) -> None:
    """Reject a delivery route outside its exact scope and profile contract.

    Parameters
    ----------
    organization_id : UUID
        The organization that owns the domain event.
    event_edition_id : UUID | None
        The exact edition identifier, or ``None`` for an explicit non-edition
        fact.
    event_name : str
        The registered versioned domain-event name.
    destination : str
        The registered delivery destination.
    payload : Mapping[str, object]
        The validated event payload used to confirm hybrid authorization scope.

    Raises
    ------
    ValidationError
        If the route violates its non-edition scope contract or an edition
        cannot resolve a profile that explicitly pins it.
    """
    if not effect_delivery_is_allowed(
        organization_id=organization_id,
        event_edition_id=event_edition_id,
        event_name=event_name,
        destination=destination,
        payload=payload,
    ):
        raise ValidationError(
            "The effect route is unavailable for this scope or edition profile.",
            code=EFFECT_PROFILE_NOT_ALLOWED,
        )
