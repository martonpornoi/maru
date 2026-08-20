"""Provide apps support for the registration module."""

from django.apps import AppConfig


class RegistrationConfig(AppConfig):
    """Configure the registration Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.registration"
    verbose_name = "Registration"
