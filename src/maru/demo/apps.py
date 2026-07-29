from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.demo"
    verbose_name = "Synthetic demonstration data"
