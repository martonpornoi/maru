"""Provide apps support for the applications module."""

from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    """Configure the applications Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.applications"
    verbose_name = "Applications"

    def ready(self) -> None:
        """Register Applications-owned compatibility checks."""
        from maru.applications import (  # noqa: F401, PLC0415
            programme_checks,
        )
