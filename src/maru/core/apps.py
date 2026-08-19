"""Provide apps support for the core module."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configure the core Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.core"
    verbose_name = "Platform core"
