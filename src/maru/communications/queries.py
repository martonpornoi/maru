"""Exact-profile inbox projections owned by Communications."""

from django.db.models import Exists, OuterRef, Q, QuerySet

from maru.communications.models import NotificationMessage
from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES
from maru.effects.models import DomainEvent
from maru.events.adoption import ADOPTION_PROFILES
from maru.events.models import EventEdition
from maru.identity.models import Account


def notification_messages_for_account(
    *, account: Account
) -> QuerySet[NotificationMessage]:
    """Return only inbox messages admitted by their exact delivery route.

    Organization-wide messages must retain an explicit non-edition
    notification route. Edition messages additionally require a tenant-bound
    edition whose exact persisted profile pins the originating event's
    ``notifications`` route. The query applies both checks before any rendered
    message body is materialized.

    Parameters
    ----------
    account : Account
        Active or retained account that owns the private inbox projection.

    Returns
    -------
    QuerySet[NotificationMessage]
        The account-owned, exact-route-compatible messages.
    """
    non_edition_event_names = tuple(
        sorted(
            event_name
            for event_name, destination in NON_EDITION_EFFECT_ROUTES
            if destination == "notifications"
        )
    )
    non_edition_events = DomainEvent.objects.filter(
        id=OuterRef("domain_event_id"),
        organization_id=OuterRef("organization_id"),
        event_edition_id__isnull=True,
        event_name__in=non_edition_event_names,
    )

    edition_route_scope = Q(event_name__in=())
    for profile in ADOPTION_PROFILES.values():
        event_names = tuple(
            sorted(
                route.event_name
                for route in profile.effect_routes
                if route.destination == "notifications"
            )
        )
        if not event_names:
            continue
        compatible_editions = EventEdition.objects.filter(
            organization_id=OuterRef("organization_id"),
            adoption_profile_code=profile.code.value,
            adoption_profile_version=profile.version,
        ).values("id")
        edition_route_scope |= Q(
            event_name__in=event_names,
            event_edition_id__in=compatible_editions,
        )
    edition_events = DomainEvent.objects.filter(
        edition_route_scope,
        id=OuterRef("domain_event_id"),
        organization_id=OuterRef("organization_id"),
        event_edition_id=OuterRef("edition_id"),
    )

    return (
        NotificationMessage.objects.filter(account=account)
        .annotate(
            _non_edition_route_allowed=Exists(non_edition_events),
            _edition_route_allowed=Exists(edition_events),
        )
        .filter(
            Q(
                edition_id__isnull=True,
                _non_edition_route_allowed=True,
            )
            | Q(
                edition_id__isnull=False,
                _edition_route_allowed=True,
            )
        )
    )
