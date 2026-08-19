"""Provide apps support for the applications module."""

from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    """Configure the applications Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.applications"
    verbose_name = "Applications"
