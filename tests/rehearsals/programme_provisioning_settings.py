"""Fenced current-schema provisioning settings, never a running Programme app.

Do not inherit test/local settings: their relaxed authority and synthetic adapters
cannot certify runtime privilege separation. This settings module admits only
the dedicated migration and runtime-verification subprocesses.
"""

from tests.rehearsals.programme_provisioning import (
    require_provisioning_process_environment,
)

require_provisioning_process_environment()

from maru.settings.base import *  # noqa: F403, E402

REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
REQUIRE_PRIVILEGED_STEP_UP = True
DEBUG = False
DEMO_PAYMENT_ADAPTER_ENABLED = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
