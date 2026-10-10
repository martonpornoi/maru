"""Django registration for the standalone Announcements owner."""

from django.apps import AppConfig


class AnnouncementsConfig(AppConfig):
    """Register the Announcements-owned schema and public workflow."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "maru.announcements"
    verbose_name = "Announcements"
