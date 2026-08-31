"""Provide apps support for the effects module."""

from django.apps import AppConfig


class EffectsConfig(AppConfig):
    """Configure the effects Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.effects"
    verbose_name = "Effects"

    def ready(self) -> None:
        """Register Effects-owned deployment checks."""
        from maru.effects import checks as effects_checks  # noqa: F401, PLC0415
