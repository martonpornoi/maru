from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]


SECRET_KEY = os.environ.get(
    "MARU_SECRET_KEY", "dev-only-change-me-before-production"
)
DEBUG = _env_bool("MARU_DEBUG", True)
ALLOWED_HOSTS = _env_list("MARU_ALLOWED_HOSTS", "127.0.0.1,localhost")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "maru.accounts",
    "maru.projects",
    "maru.social",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "maru.urls"
WSGI_APPLICATION = "maru.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "maru.projects.context_processors.review_permissions",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("MARU_DB", BASE_DIR / "db.sqlite3"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("MARU_TIME_ZONE", "Europe/Budapest")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_SSL_REDIRECT = _env_bool("MARU_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = int(
    os.environ.get("MARU_SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    "MARU_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG
)
SECURE_HSTS_PRELOAD = _env_bool("MARU_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = _env_bool("MARU_SESSION_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = _env_bool("MARU_CSRF_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = _env_list("MARU_CSRF_TRUSTED_ORIGINS")
X_FRAME_OPTIONS = "DENY"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:my_profile"
LOGOUT_REDIRECT_URL = "accounts:login"

MARU_GOOGLE_EMAIL_DOMAINS = ("gmail.com", "googlemail.com")
MARU_DEV_LOGIN_ENABLED = DEBUG and _env_bool("MARU_DEV_LOGIN_ENABLED", True)

MARU_GOOGLE_OAUTH_CLIENT_ID = os.environ.get("MARU_GOOGLE_OAUTH_CLIENT_ID", "")
MARU_GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get(
    "MARU_GOOGLE_OAUTH_CLIENT_SECRET", ""
)
MARU_GOOGLE_OAUTH_REDIRECT_URI = os.environ.get(
    "MARU_GOOGLE_OAUTH_REDIRECT_URI", ""
)
MARU_GOOGLE_OAUTH_AUTHORIZATION_URL = os.environ.get(
    "MARU_GOOGLE_OAUTH_AUTHORIZATION_URL",
    "https://accounts.google.com/o/oauth2/v2/auth",
)
MARU_GOOGLE_OAUTH_TOKEN_URL = os.environ.get(
    "MARU_GOOGLE_OAUTH_TOKEN_URL",
    "https://oauth2.googleapis.com/token",
)
MARU_GOOGLE_OAUTH_USERINFO_URL = os.environ.get(
    "MARU_GOOGLE_OAUTH_USERINFO_URL",
    "https://openidconnect.googleapis.com/v1/userinfo",
)
MARU_GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile")
