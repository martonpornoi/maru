"""Provide apps support for the accreditation module."""

from django.apps import AppConfig


class AccreditationConfig(AppConfig):
    """Configure the accreditation Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.accreditation"
    verbose_name = "Accreditation"
