"""Settings shared by all Maru environments."""

import os
from pathlib import Path

from maru.settings.environment import csv_value, postgres_database

BASE_DIR = Path(__file__).resolve().parents[3]

DEBUG = False
SECRET_KEY = os.environ.get("MARU_SECRET_KEY", "")
ALLOWED_HOSTS = csv_value(os.environ, "MARU_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "maru.core",
    "maru.identity",
    "maru.organizations",
    "maru.events",
    "maru.participation",
    "maru.authorization",
    "maru.audit",
    "maru.effects",
    "maru.communications",
    "maru.registration",
    "maru.workforce",
    "maru.accreditation",
    "maru.privacyops",
]

MIDDLEWARE = [
    "maru.core.middleware.CorrelationIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "maru.core.cors.RegistrationClientCorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "maru.identity.middleware.AccountSessionInventoryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "maru.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "src" / "maru" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "maru.wsgi.application"
ASGI_APPLICATION = "maru.asgi.application"

DATABASES = {
    "default": postgres_database(
        os.environ.get(
            "MARU_DATABASE_URL",
            "postgresql://maru:maru@127.0.0.1:5432/maru",
        )
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.Account"
LOGIN_REDIRECT_URL = "/staff/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "EXCEPTION_HANDLER": "maru.core.problems.problem_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Maru API",
    "DESCRIPTION": "Versioned API for the Maru convention operating platform.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "OAS_VERSION": "3.1.0",
    "ENUM_NAME_OVERRIDES": {
        "EditionLifecycleEnum": "maru.events.models.EDITION_LIFECYCLE_CHOICES",
        "RegistrationStateEnum": (
            "maru.registration.models.REGISTRATION_STATE_CHOICES"
        ),
        "AccountRestrictionKindEnum": (
            "maru.identity.models.ACCOUNT_RESTRICTION_KIND_CHOICES"
        ),
        "ActiveRevokedStatusEnum": (
            "maru.identity.models.ACTIVE_REVOKED_STATUS_CHOICES"
        ),
        "FinancialOperationKindEnum": (
            "maru.registration.models.FINANCIAL_OPERATION_KIND_CHOICES"
        ),
        "PaymentExceptionKindEnum": (
            "maru.registration.models.PAYMENT_EXCEPTION_KIND_CHOICES"
        ),
        "SubjectRightsRequestKindEnum": (
            "maru.privacyops.models.SUBJECT_RIGHTS_REQUEST_KIND_CHOICES"
        ),
        "FinancialOperationStatusEnum": (
            "maru.registration.models.FINANCIAL_OPERATION_STATUS_CHOICES"
        ),
        "PaymentExceptionStatusEnum": (
            "maru.registration.models.PAYMENT_EXCEPTION_STATUS_CHOICES"
        ),
        "PostEditionCorrectionStatusEnum": (
            "maru.privacyops.models.POST_EDITION_CORRECTION_STATUS_CHOICES"
        ),
        "SubjectRightsRequestStatusEnum": (
            "maru.privacyops.models.SUBJECT_RIGHTS_REQUEST_STATUS_CHOICES"
        ),
    },
}

BUILD_VERSION = os.environ.get("MARU_BUILD_VERSION", "development")
BUILD_COMMIT = os.environ.get("MARU_BUILD_COMMIT", "unknown")
LOG_LEVEL = os.environ.get("MARU_LOG_LEVEL", "INFO")
DEMO_PAYMENT_ADAPTER_ENABLED = False
MARU_PUBLIC_BASE_URL = os.environ.get("MARU_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_FROM_EMAIL = os.environ.get("MARU_DEFAULT_FROM_EMAIL", "no-reply@maru.invalid")
IDENTITY_EXPOSE_TEST_TOKENS = False
ALLOW_PROVISIONAL_PUBLIC_REGISTRATION = False
REQUIRE_PRIVILEGED_STEP_UP = True
MARU_PAYMENT_RETURN_ORIGINS = csv_value(
    os.environ,
    "MARU_PAYMENT_RETURN_ORIGINS",
) or [MARU_PUBLIC_BASE_URL.rstrip("/")]
MARU_PAYMENT_PROVIDER_HOSTS = [
    host.casefold() for host in csv_value(os.environ, "MARU_PAYMENT_PROVIDER_HOSTS")
]
MARU_REGISTRATION_CLIENT_ORIGINS = csv_value(
    os.environ,
    "MARU_REGISTRATION_CLIENT_ORIGINS",
) or [MARU_PUBLIC_BASE_URL.rstrip("/")]
MARU_MEDIA_SCANNER = os.environ.get("MARU_MEDIA_SCANNER", "disabled")
MARU_MEDIA_SCANNER_HOST = os.environ.get("MARU_MEDIA_SCANNER_HOST", "")
MARU_MEDIA_SCANNER_PORT = int(os.environ.get("MARU_MEDIA_SCANNER_PORT", "3310"))
MARU_MEDIA_SCANNER_TIMEOUT_SECONDS = float(
    os.environ.get("MARU_MEDIA_SCANNER_TIMEOUT_SECONDS", "5")
)
MEDIA_REQUIRE_SAFETY_RECEIPT = True
MARU_OFFLINE_MANIFEST_SECRET = os.environ.get("MARU_OFFLINE_MANIFEST_SECRET", "")
MARU_EXPOSE_TEST_CREDENTIAL_TOKENS = False
ENFORCE_EDITION_CLOSURE_GATES = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "maru.core.logging.SafeJsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}
