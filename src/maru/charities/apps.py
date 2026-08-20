"""Provide apps support for the charities module."""

from django.apps import AppConfig


class CharitiesConfig(AppConfig):
    """Configure the charities Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.charities"
    verbose_name = "Charity partners"
