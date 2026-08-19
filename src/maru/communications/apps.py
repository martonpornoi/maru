"""Provide apps support for the communications module."""

from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    """Configure the communications Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.communications"
    verbose_name = "Communications"
