"""Strict application settings for the owned, HTTP-loopback Workforce rehearsal.

This source-development fixture is not HTTPS deployment acceptance. Invitation
keys are still required by its bootstrap and worker, with no public token hooks.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from maru.settings.base import *  # noqa: F403 -- inherit the actual security defaults

_endpoint = urlsplit(os.environ.get("MARU_DATABASE_URL", ""))
_origin = urlsplit(os.environ.get("MARU_PUBLIC_BASE_URL", ""))
_directory = Path(os.environ.get("MARU_WORKFORCE_REHEARSAL_DIRECTORY", ""))
if not (
    os.environ.get("MARU_WORKFORCE_REHEARSAL") == "owned-loopback"
    and _endpoint.scheme == "postgresql"
    and _endpoint.hostname == "127.0.0.1"
    and _endpoint.path == "/maru"
    and _endpoint.username in {"maru_migration", "maru_runtime"}
    and _origin.scheme == "http"
    and _origin.hostname == "127.0.0.1"
    and _origin.port
    and not (
        _origin.username
        or _origin.password
        or _origin.path
        or _origin.query
        or _origin.fragment
    )
    and _directory.is_absolute()
    and _directory.is_dir()
    and os.environ.get("MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE") == "true"
    and os.environ.get("MARU_RUNTIME_DATABASE_ROLE") == "maru_runtime"
):
    raise ImproperlyConfigured("The owned Workforce rehearsal boundary is unavailable.")
if (
    os.environ.get("MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON")
    and os.environ.get("MARU_WORKFORCE_REHEARSAL_PROCESS") != "worker"
):
    raise ImproperlyConfigured("Invitation private keys belong only to the worker.")

ALLOWED_HOSTS = ["127.0.0.1"]
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = _directory / "mail.private"
STATIC_ROOT = _directory / "static"
MEDIA_ROOT = _directory / "media"
