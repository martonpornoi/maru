"""Provide apps support for the catalog module."""

from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """Configure the catalog Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.catalog"
    verbose_name = "Catalog and orders"
