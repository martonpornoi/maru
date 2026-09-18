"""Policy-fenced loopback candidate settings, not a production settings mode."""

import os

from tests.rehearsals.programme_provisioning import (
    require_provisioning_process_environment,
)
from tests.rehearsals.programme_registration import (
    register_isolated_programme_candidate,
)

require_provisioning_process_environment()
if os.environ.get("MARU_PROGRAMME_REHEARSAL_PROCESS") != "maru_runtime":
    raise RuntimeError("candidate_runtime_login_required")
register_isolated_programme_candidate()

from maru.settings.base import *  # noqa: F403, E402

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1"]
ROOT_URLCONF = "tests.rehearsals.programme_urls"
MIGRATION_MODULES = {"events": "tests.rehearsals.programme_event_migrations"}
REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
REQUIRE_PRIVILEGED_STEP_UP = True
ENFORCE_EDITION_CLOSURE_GATES = True
IDENTITY_INVITATION_ENCRYPTION_REQUIRED = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
