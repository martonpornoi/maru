"""Production settings. Unsafe or missing configuration fails at startup."""

import os

from maru.settings.base import *  # noqa: F403
from maru.settings.environment import (
    boolean,
    csv_value,
    postgres_database,
    required,
    required_boolean,
    validate_production,
)

DEBUG = boolean(os.environ, "MARU_DEBUG", default=False)
SECRET_KEY = required(os.environ, "MARU_SECRET_KEY")
ALLOWED_HOSTS = csv_value(os.environ, "MARU_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = csv_value(os.environ, "MARU_CSRF_TRUSTED_ORIGINS")
DATABASES = {"default": postgres_database(required(os.environ, "MARU_DATABASE_URL"))}
RUNTIME_DATABASE_ROLE = required(os.environ, "MARU_RUNTIME_DATABASE_ROLE")
MARU_PUBLIC_BASE_URL = required(os.environ, "MARU_PUBLIC_BASE_URL")
DEFAULT_FROM_EMAIL = required(os.environ, "MARU_DEFAULT_FROM_EMAIL")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = required(os.environ, "MARU_EMAIL_HOST")
EMAIL_PORT = int(required(os.environ, "MARU_EMAIL_PORT"))
EMAIL_HOST_USER = required(os.environ, "MARU_EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = required(os.environ, "MARU_EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = boolean(os.environ, "MARU_EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = boolean(os.environ, "MARU_EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = 10
MARU_PAYMENT_RETURN_ORIGINS = csv_value(
    os.environ,
    "MARU_PAYMENT_RETURN_ORIGINS",
)
MARU_PAYMENT_PROVIDER_HOSTS = [
    host.casefold() for host in csv_value(os.environ, "MARU_PAYMENT_PROVIDER_HOSTS")
]
MARU_REGISTRATION_CLIENT_ORIGINS = csv_value(
    os.environ,
    "MARU_REGISTRATION_CLIENT_ORIGINS",
)
MARU_MEDIA_SCANNER = required(os.environ, "MARU_MEDIA_SCANNER")
MARU_MEDIA_SCANNER_HOST = required(os.environ, "MARU_MEDIA_SCANNER_HOST")
MARU_OFFLINE_MANIFEST_SECRET = required(
    os.environ,
    "MARU_OFFLINE_MANIFEST_SECRET",
)
MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = required(
    os.environ,
    "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID",
)
MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = required(
    os.environ,
    "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64",
)
MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = required(
    os.environ,
    "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID",
)
MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = required(
    os.environ,
    "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON",
)
IDENTITY_INVITATION_ENCRYPTION_REQUIRED = True
ALLOW_PROVISIONAL_PUBLIC_REGISTRATION = boolean(
    os.environ,
    "MARU_ALLOW_PROVISIONAL_PUBLIC_REGISTRATION",
    default=False,
)
IDENTITY_EXPOSE_TEST_TOKENS = boolean(
    os.environ,
    "MARU_IDENTITY_EXPOSE_TEST_TOKENS",
    default=False,
)
MARU_EXPOSE_TEST_CREDENTIAL_TOKENS = boolean(
    os.environ,
    "MARU_EXPOSE_TEST_CREDENTIAL_TOKENS",
    default=False,
)
REQUIRE_PRIVILEGED_STEP_UP = boolean(
    os.environ,
    "MARU_REQUIRE_PRIVILEGED_STEP_UP",
    default=True,
)
ENFORCE_EDITION_CLOSURE_GATES = boolean(
    os.environ,
    "MARU_ENFORCE_EDITION_CLOSURE_GATES",
    default=True,
)
REQUIRE_EXACT_AUTHORITY_PROVENANCE = required_boolean(
    os.environ,
    "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE",
)

SECURE_SSL_REDIRECT = boolean(os.environ, "MARU_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "None"
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

validate_production(
    secret_key=SECRET_KEY,
    allowed_hosts=ALLOWED_HOSTS,
    debug=DEBUG,
    database=DATABASES["default"],
    runtime_database_role=RUNTIME_DATABASE_ROLE,
    public_base_url=MARU_PUBLIC_BASE_URL,
    default_from_email=DEFAULT_FROM_EMAIL,
    email_backend=EMAIL_BACKEND,
    email_host=EMAIL_HOST,
    email_use_tls=EMAIL_USE_TLS,
    email_use_ssl=EMAIL_USE_SSL,
    payment_return_origins=MARU_PAYMENT_RETURN_ORIGINS,
    payment_provider_hosts=MARU_PAYMENT_PROVIDER_HOSTS,
    registration_client_origins=MARU_REGISTRATION_CLIENT_ORIGINS,
    csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
    media_scanner=MARU_MEDIA_SCANNER,
    media_scanner_host=MARU_MEDIA_SCANNER_HOST,
    offline_manifest_secret=MARU_OFFLINE_MANIFEST_SECRET,
    invitation_encryption_key_id=MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID,
    invitation_public_key_b64=MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64,
    invitation_digest_active_key_id=(MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID),
    invitation_digest_keys_json=MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON,
    allow_provisional_registration=ALLOW_PROVISIONAL_PUBLIC_REGISTRATION,
    expose_identity_test_tokens=IDENTITY_EXPOSE_TEST_TOKENS,
    expose_credential_test_tokens=MARU_EXPOSE_TEST_CREDENTIAL_TOKENS,
    require_privileged_step_up=REQUIRE_PRIVILEGED_STEP_UP,
    enforce_closure_gates=ENFORCE_EDITION_CLOSURE_GATES,
)
