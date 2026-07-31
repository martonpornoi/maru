"""Safe local-development settings."""

import os

from maru.settings.base import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "maru.demo"]  # noqa: F405

DEBUG = True
DEMO_PAYMENT_ADAPTER_ENABLED = True
SECRET_KEY = os.environ.get(
    "MARU_SECRET_KEY",
    "development-only-key-not-valid-for-any-shared-environment",
)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
MARU_MEDIA_SCANNER = os.environ.get(
    "MARU_MEDIA_SCANNER",
    "local_rehearsal_clean",
)
