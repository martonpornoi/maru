"""Provide apps support for the effects module."""

from django.apps import AppConfig


class EffectsConfig(AppConfig):
    """Configure the effects Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.effects"
    verbose_name = "Effects"
