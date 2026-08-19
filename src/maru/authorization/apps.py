"""Provide apps support for the authorization module."""

from django.apps import AppConfig


class AuthorizationConfig(AppConfig):
    """Configure the authorization Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.authorization"
    verbose_name = "Authorization"
