"""Django owner registration for reviewed internal Guidance."""

from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    """Keep the Knowledge domain independent from other content owners."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.knowledge"
    verbose_name = "Guidance"
