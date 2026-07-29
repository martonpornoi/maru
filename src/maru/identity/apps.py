from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.identity"
    verbose_name = "Identity"

    def ready(self) -> None:
        from maru.identity import signals  # noqa: F401, PLC0415
