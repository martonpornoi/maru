"""Provide apps support for the participation module."""

from django.apps import AppConfig


class ParticipationConfig(AppConfig):
    """Configure the participation Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.participation"
    verbose_name = "Participation"
