"""Settings for automated tests."""

import os

os.environ.setdefault(
    "MARU_DATABASE_URL",
    "postgresql://maru:maru@127.0.0.1:5432/maru_test",
)

from maru.settings.base import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "maru.demo"]  # noqa: F405
DEMO_PAYMENT_ADAPTER_ENABLED = True

SECRET_KEY = "tests-only-secret-key-never-valid-outside-the-test-suite"
ALLOWED_HOSTS = ["testserver"]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
IDENTITY_EXPOSE_TEST_TOKENS = True
ALLOW_PROVISIONAL_PUBLIC_REGISTRATION = True
REQUIRE_PRIVILEGED_STEP_UP = False
MARU_MEDIA_SCANNER = "test_clean"
MEDIA_REQUIRE_SAFETY_RECEIPT = False
MARU_OFFLINE_MANIFEST_SECRET = "test-only-offline-manifest-secret"
MARU_EXPOSE_TEST_CREDENTIAL_TOKENS = True
ENFORCE_EDITION_CLOSURE_GATES = False
