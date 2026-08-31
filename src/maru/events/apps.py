"""Provide apps support for the events module."""

from django.apps import AppConfig


class EventsConfig(AppConfig):
    """Configure the events Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.events"
    verbose_name = "Events"

    def ready(self) -> None:
        """Register Events-owned adoption compatibility checks."""
        from maru.events import checks as events_checks  # noqa: F401, PLC0415
