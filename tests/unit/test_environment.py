from types import MappingProxyType

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import override_settings

from maru.registration.payments import _validate_provider_url
from maru.settings.environment import (
    boolean,
    csv_value,
    postgres_database,
    required,
    validate_production,
)


def test_required_strips_a_present_value() -> None:
    environment = MappingProxyType({"VALUE": " useful "})

    assert required(environment, "VALUE") == "useful"


@pytest.mark.parametrize("value", ["", "  "])
def test_required_rejects_missing_or_empty_value(value: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="VALUE is required"):
        required({"VALUE": value}, "VALUE")


def test_csv_value_removes_empty_and_surrounding_space() -> None:
    assert csv_value({"VALUE": "one, two ,,three"}, "VALUE") == [
        "one",
        "two",
        "three",
    ]


@pytest.mark.parametrize("value", ["1", "TRUE", " yes ", "on"])
def test_boolean_accepts_documented_true_values(value: str) -> None:
    assert boolean({"VALUE": value}, "VALUE", default=False)


@pytest.mark.parametrize("value", ["0", "FALSE", " no ", "off"])
def test_boolean_accepts_documented_false_values(value: str) -> None:
    assert not boolean({"VALUE": value}, "VALUE", default=True)


def test_boolean_uses_default_only_when_absent() -> None:
    assert boolean({}, "VALUE", default=True)


def test_boolean_rejects_ambiguous_value() -> None:
    with pytest.raises(ImproperlyConfigured, match="VALUE must be one of"):
        boolean({"VALUE": "enabled"}, "VALUE", default=False)


def test_postgres_database_parses_and_decodes_url() -> None:
    database = postgres_database(
        "postgresql://maru:user%20secret@db.example:5433/maru_test?sslmode=require"
    )

    assert database == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "maru_test",
        "USER": "maru",
        "PASSWORD": "user secret",
        "HOST": "db.example",
        "PORT": "5433",
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": "require", "connect_timeout": "3"},
    }


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///maru.sqlite3",
        "postgresql:///maru",
        "postgresql://localhost/",
        "postgresql://localhost/one/two",
    ],
)
def test_postgres_database_rejects_unsafe_or_incomplete_url(url: str) -> None:
    with pytest.raises(ImproperlyConfigured):
        postgres_database(url)


def test_validate_production_accepts_safe_baseline() -> None:
    validate_production(
        secret_key="s" * 50,
        allowed_hosts=["maru.example"],
        debug=False,
        database={"ENGINE": "django.db.backends.postgresql"},
        public_base_url="https://maru.example",
        default_from_email="registration@maru.example",
        email_backend="django.core.mail.backends.smtp.EmailBackend",
        email_host="smtp.maru.example",
        email_use_tls=True,
        email_use_ssl=False,
        payment_return_origins=["https://register.maru.example"],
        payment_provider_hosts=["payments.example"],
        registration_client_origins=["https://register.maru.example"],
        csrf_trusted_origins=["https://register.maru.example"],
        media_scanner="clamav",
        media_scanner_host="scanner.internal",
        offline_manifest_secret="o" * 32,
        allow_provisional_registration=False,
        expose_identity_test_tokens=False,
        expose_credential_test_tokens=False,
        require_privileged_step_up=True,
        enforce_closure_gates=True,
    )


def test_validate_production_reports_all_unsafe_values() -> None:
    with pytest.raises(ImproperlyConfigured) as captured:
        validate_production(
            secret_key="development-secret",
            allowed_hosts=["*"],
            debug=True,
            database={"ENGINE": "django.db.backends.sqlite3"},
            public_base_url="http://maru.invalid",
            default_from_email="no-reply@maru.invalid",
            email_backend="django.core.mail.backends.console.EmailBackend",
            email_host="",
            email_use_tls=False,
            email_use_ssl=False,
            payment_return_origins=["http://maru.invalid"],
            payment_provider_hosts=["https://bad.example/path"],
            registration_client_origins=["http://register.maru.invalid"],
            csrf_trusted_origins=[],
            media_scanner="test_clean",
            media_scanner_host="",
            offline_manifest_secret="short",
            allow_provisional_registration=True,
            expose_identity_test_tokens=True,
            expose_credential_test_tokens=True,
            require_privileged_step_up=False,
            enforce_closure_gates=False,
        )

    message = str(captured.value)
    assert "MARU_SECRET_KEY" in message
    assert "wildcard" in message
    assert "DEBUG" in message
    assert "PostgreSQL" in message
    assert "MARU_PUBLIC_BASE_URL" in message
    assert "MARU_DEFAULT_FROM_EMAIL" in message
    assert "production email" in message
    assert "MARU_PAYMENT_RETURN_ORIGINS" in message
    assert "MARU_PAYMENT_PROVIDER_HOSTS" in message
    assert "MARU_REGISTRATION_CLIENT_ORIGINS" in message
    assert "MARU_CSRF_TRUSTED_ORIGINS" in message
    assert "MARU_MEDIA_SCANNER" in message
    assert "MARU_OFFLINE_MANIFEST_SECRET" in message
    assert "provisional" in message
    assert "test bearer-token" in message
    assert "step-up" in message
    assert "closure gates" in message


@override_settings(MARU_PAYMENT_PROVIDER_HOSTS=["api.payments.example"])
def test_payment_provider_url_requires_an_explicit_allowed_https_host() -> None:
    assert (
        _validate_provider_url("https://api.payments.example/v1/intents")
        == "https://api.payments.example/v1/intents"
    )
    with pytest.raises(ValidationError, match="not permitted"):
        _validate_provider_url("https://metadata.internal/latest")
    with pytest.raises(ValidationError, match="not permitted"):
        _validate_provider_url("http://api.payments.example/v1/intents")
