"""Provide apps support for the organizations module."""

from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    """Configure the organizations Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.organizations"
    verbose_name = "Organizations"
