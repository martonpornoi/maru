"""Django registration for the dormant Scheduling owner."""

from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    """Register owned schema without activating a Programme Operations profile."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.scheduling"
    verbose_name = "Scheduling"

    def ready(self) -> None:
        """Register owner compatibility checks without a runtime workflow."""
        from maru.scheduling import checks as scheduling_checks  # noqa: F401, PLC0415
