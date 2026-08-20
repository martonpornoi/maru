"""Provide apps support for the logistics module."""

from django.apps import AppConfig


class LogisticsConfig(AppConfig):
    """Configure the logistics Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.logistics"
    verbose_name = "Logistics"
