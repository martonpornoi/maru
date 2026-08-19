from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.catalog"
    verbose_name = "Catalog and orders"
