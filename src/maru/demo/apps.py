"""Provide apps support for the demo module."""

from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Configure the demo Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.demo"
    verbose_name = "Synthetic demonstration data"
