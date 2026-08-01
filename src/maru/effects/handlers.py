"""Explicit built-in handlers for currently internal-only domain facts."""

from typing import cast

from django.utils import timezone

from maru.effects.models import DomainEvent
from maru.effects.worker import (
    EffectContext,
    EffectHandler,
    EffectTimeoutError,
    HandlerRegistration,
    HandlerRegistry,
)

ACKNOWLEDGED_INTERNAL_EVENTS = frozenset(
    {
        "organizations.convention_series.created.v1",
        "organizations.convention_series.updated.v1",
        "events.edition.created.v1",
        "events.edition.details_updated.v1",
        "events.edition.lifecycle_transitioned.v1",
        "authorization.capability.delegated.v1",
        "authorization.capability.direct_granted.v1",
        "authorization.capability.revoked.v1",
        "authorization.role_bundle.version_created.v1",
        "authorization.role.assigned.v1",
        "authorization.role.revoked.v1",
        "identity.account_restriction.applied.v1",
        "system.effect.probe_requested.v1",
        "registration.configuration.draft_created.v1",
        "registration.configuration.activated.v1",
        "registration.template.published.v1",
        "registration.submitted.v1",
        "registration.profile.updated.v1",
        "registration.profile.media_reviewed.v1",
        "registration.payment.reconciled.v1",
        "registration.payment.deadline_changed.v1",
        "registration.payment.waived.v1",
        "registration.payment.expired.v1",
        "registration.waitlist.offered.v1",
        "registration.cancelled.v1",
        "registration.checked_in.v1",
        "registration.guardian.accepted.v1",
        "workforce.application.submitted.v1",
        "workforce.document.reviewed.v1",
        "workforce.position_assignment.activated.v1",
    }
)


def acknowledge_internal_fact(
    event: DomainEvent,
    context: EffectContext,
) -> None:
    """Acknowledge durable facts whose downstream projection is not yet installed."""

    del event
    if timezone.now() >= context.deadline:
        raise EffectTimeoutError


def built_in_handler_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    for event_name in sorted(ACKNOWLEDGED_INTERNAL_EVENTS):
        registry.register(
            HandlerRegistration(
                event_name=event_name,
                destination="internal",
                handler=acknowledge_internal_fact,
            )
        )
    from maru.communications.services import (  # noqa: PLC0415
        EVENT_LABELS,
        deliver_registration_notification,
        deliver_restriction_notification,
    )

    for event_name in sorted(EVENT_LABELS):
        registry.register(
            HandlerRegistration(
                event_name=event_name,
                destination="notifications",
                handler=cast(EffectHandler, deliver_registration_notification),
            )
        )
    registry.register(
        HandlerRegistration(
            event_name="identity.account_restriction.applied.v1",
            destination="notifications",
            handler=cast(EffectHandler, deliver_restriction_notification),
        )
    )
    return registry
