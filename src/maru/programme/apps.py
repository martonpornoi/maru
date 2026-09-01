"""Django application configuration for the Programme bounded context."""

from django.apps import AppConfig


class ProgrammeConfig(AppConfig):
    """Configure the dormant Programme Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.programme"
    verbose_name = "Programme"

    def ready(self) -> None:
        """Register Programme-owned compatibility checks."""
        from maru.programme import checks as programme_checks  # noqa: F401, PLC0415
