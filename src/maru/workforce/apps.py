"""Workforce application configuration."""

from django.apps import AppConfig


class WorkforceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.workforce"
    verbose_name = "Workforce and onboarding"

    def ready(self) -> None:
        from maru.workforce import signals  # noqa: F401, PLC0415
