"""Explicit read contracts owned by the events module."""

from django.db.models import QuerySet

from maru.events.models import EventEdition


def platform_editions() -> QuerySet[EventEdition]:
    """Return edition identity for an already-authorized platform projection."""

    return EventEdition.objects.select_related("organization", "series").order_by(
        "-starts_on",
        "name",
        "id",
    )
