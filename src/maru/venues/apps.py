"""Provide apps support for the venues module."""

from django.apps import AppConfig


class VenuesConfig(AppConfig):
    """Configure the venues Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.venues"
    verbose_name = "Venues"
