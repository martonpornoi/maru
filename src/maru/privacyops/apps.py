"""Provide apps support for the privacyops module."""

from django.apps import AppConfig


class PrivacyOpsConfig(AppConfig):
    """Configure the privacy ops Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.privacyops"
    verbose_name = "Privacy operations"
