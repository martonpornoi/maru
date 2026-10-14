"""Exact scope and edition-profile checks for durable effect delivery routes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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


# This catalog does not change any immutable edition manifest. Every fallback
# also requires an exact retained owner record and the complete event identity.
TRANSITION_EFFECT_ROUTES = validated_effect_route_catalog(
    (("events.guidance_adoption.changed.v1", "internal"),)
)


@dataclass(frozen=True, slots=True)
class EffectEventIdentity:
    """Carry the immutable event identity needed by retained transition routing.

    Attributes
    ----------
    schema_version
        Exact registered event schema version.
    aggregate_type
        Exact owning evidence family.
    aggregate_id
        Immutable owning record identifier, not its parent request.
    aggregate_version
        Version of that exact immutable evidence record.
    actor_kind
        Recorded principal kind, without present-day reauthorization.
    actor_id
        Recorded actual principal identifier.
    causation_id
        Original accepted mutation audit identifier.
    correlation_id
        Original immutable operation correlation identifier.
    """

    schema_version: int
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    actor_kind: str
    actor_id: UUID | None
    causation_id: UUID | None
    correlation_id: UUID


def effect_delivery_is_allowed(  # noqa: PLR0911 - separate closed route families
    *,
    organization_id: UUID,
    event_edition_id: UUID | None,
    event_name: str,
    destination: str,
    payload: Mapping[str, object],
    identity: EffectEventIdentity | None = None,
) -> bool:
    """Return whether one durable delivery is permitted for its exact scope.

    Platform- and organization-scoped facts declare that scope with a null
    edition identifier and retain their existing non-edition delivery policy.
    Edition-scoped facts must resolve an exact tenant-bound edition profile and
    an explicitly pinned event/destination route or the one evidence-backed
    foundation transition declared separately under ADR 0124.

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
    identity : EffectEventIdentity | None, default=None
        Complete original identity; missing evidence cannot use a transition route.

    Returns
    -------
    bool
        ``True`` only for an explicit non-edition fact or a route pinned by the
        exact persisted edition profile, or exact retained transition evidence.
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
    if profile is None:
        return False
    if profile_allows_effect(
        profile.code,
        profile.version,
        event_name,
        destination,
    ):
        return True
    if (
        (event_name, destination) not in TRANSITION_EFFECT_ROUTES
        or (profile.code, profile.version)
        not in {("announcements_only", 1), ("announcements_guidance", 1)}
        or type(identity) is not EffectEventIdentity
        or type(identity.schema_version) is not int
        or type(identity.aggregate_version) is not int
        or identity.schema_version != 1
        or identity.aggregate_version != 1
        or not isinstance(identity.aggregate_type, str)
        or not all(
            isinstance(value, UUID)
            for value in (
                identity.aggregate_id,
                identity.actor_id,
                identity.causation_id,
                identity.correlation_id,
            )
        )
    ):
        return False

    from maru.events.guidance_effects import (  # noqa: PLC0415
        guidance_adoption_effect_reference,
    )

    reference = guidance_adoption_effect_reference(
        organization_id=organization_id,
        edition_id=event_edition_id,
        aggregate_type=identity.aggregate_type,
        aggregate_id=identity.aggregate_id,
    )
    return reference is not None and (
        identity.actor_kind == "account"
        and identity.actor_id == reference.actor_id
        and identity.causation_id == reference.source_audit_id
        and identity.correlation_id == reference.correlation_id
        and payload == {"operation": reference.operation}
    )


def require_effect_delivery_allowed(
    *,
    organization_id: UUID,
    event_edition_id: UUID | None,
    event_name: str,
    destination: str,
    payload: Mapping[str, object],
    identity: EffectEventIdentity | None = None,
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
    identity : EffectEventIdentity | None, default=None
        Complete original identity; missing evidence cannot use a transition route.

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
        identity=identity,
    ):
        raise ValidationError(
            "The effect route is unavailable for this scope or edition profile.",
            code=EFFECT_PROFILE_NOT_ALLOWED,
        )
