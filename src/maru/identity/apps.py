"""Provide apps support for the identity module."""

from django.apps import AppConfig


class IdentityConfig(AppConfig):
    """Configure the identity Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.identity"
    verbose_name = "Identity"

    def ready(self) -> None:
        """Initialize the Django application integrations."""
        from maru.identity import checks as identity_checks  # noqa: F401, PLC0415
        from maru.identity import signals  # noqa: F401, PLC0415
