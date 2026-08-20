"""Provide apps support for the audit module."""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Configure the audit Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.audit"
    verbose_name = "Audit"
