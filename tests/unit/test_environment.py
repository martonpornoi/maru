import base64
import json
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import override_settings

from maru.registration.payments import _validate_provider_url
from maru.settings.environment import (
    POSTGRES_CONNECTION_OPTIONS,
    boolean,
    csv_value,
    invitation_public_key_configuration_is_valid,
    invitation_token_key_configuration_is_valid,
    normalized_https_origin,
    postgres_database,
    required,
    required_boolean,
    validate_production,
)

_VALID_DIGEST_KEY_ID = "digest-2026-08"
_VALID_DIGEST_KEYS_JSON = json.dumps(
    {_VALID_DIGEST_KEY_ID: base64.b64encode(b"d" * 32).decode("ascii")},
    separators=(",", ":"),
)


@pytest.fixture(scope="module")
def invitation_public_key_configuration() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_key_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        "production-key-2026-08",
        base64.b64encode(public_key_pem).decode("ascii"),
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("false", False)],
)
def test_required_boolean_requires_an_explicit_valid_value(
    value: str,
    expected: bool,
) -> None:
    assert required_boolean({"VALUE": value}, "VALUE") is expected


def test_required_boolean_rejects_an_absent_value() -> None:
    with pytest.raises(ImproperlyConfigured, match="VALUE is required"):
        required_boolean({}, "VALUE")


def test_test_settings_default_to_compatible_authority_provenance(
    settings: object,
) -> None:
    assert settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is False  # type: ignore[attr-defined]


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
        "OPTIONS": {
            "sslmode": "require",
            "connect_timeout": "3",
            "options": POSTGRES_CONNECTION_OPTIONS,
        },
    }


def test_postgres_database_rejects_caller_controlled_libpq_options() -> None:
    with pytest.raises(ImproperlyConfigured, match="owns the connection search path"):
        postgres_database(
            "postgresql://maru:secret@db.example:5432/maru"
            "?options=-c%20search_path%3Devil%2Cpublic"
        )


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


def _validate_safe_production(
    *,
    invitation_key_id: str,
    invitation_public_key_b64: str,
    invitation_digest_active_key_id: str = _VALID_DIGEST_KEY_ID,
    invitation_digest_keys_json: str = _VALID_DIGEST_KEYS_JSON,
) -> None:
    validate_production(
        secret_key="s" * 50,
        allowed_hosts=["maru.example"],
        debug=False,
        database={
            "ENGINE": "django.db.backends.postgresql",
            "OPTIONS": {"options": POSTGRES_CONNECTION_OPTIONS},
        },
        runtime_database_role="maru_runtime",
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
        invitation_encryption_key_id=invitation_key_id,
        invitation_public_key_b64=invitation_public_key_b64,
        invitation_digest_active_key_id=invitation_digest_active_key_id,
        invitation_digest_keys_json=invitation_digest_keys_json,
        allow_provisional_registration=False,
        expose_identity_test_tokens=False,
        expose_credential_test_tokens=False,
        require_privileged_step_up=True,
        enforce_closure_gates=True,
    )


def test_validate_production_accepts_safe_baseline(
    invitation_public_key_configuration: tuple[str, str],
) -> None:
    invitation_key_id, invitation_public_key_b64 = invitation_public_key_configuration

    _validate_safe_production(
        invitation_key_id=invitation_key_id,
        invitation_public_key_b64=invitation_public_key_b64,
    )


def test_validate_production_rejects_invitation_key_without_releasing_values() -> None:
    unsafe_key_id = "unsafe/key-id"
    unsafe_public_key = "sensitive-malformed-public-key"

    with pytest.raises(ImproperlyConfigured) as captured:
        _validate_safe_production(
            invitation_key_id=unsafe_key_id,
            invitation_public_key_b64=unsafe_public_key,
        )

    message = str(captured.value)
    assert "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID" in message
    assert "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64" in message
    assert unsafe_key_id not in message
    assert unsafe_public_key not in message


def test_validate_production_rejects_digest_keys_without_releasing_values(
    invitation_public_key_configuration: tuple[str, str],
) -> None:
    invitation_key_id, invitation_public_key_b64 = invitation_public_key_configuration
    unsafe_key_id = "unsafe/digest-key"
    unsafe_keyring = '{"unsafe/digest-key":"sensitive-material"}'

    with pytest.raises(ImproperlyConfigured) as captured:
        _validate_safe_production(
            invitation_key_id=invitation_key_id,
            invitation_public_key_b64=invitation_public_key_b64,
            invitation_digest_active_key_id=unsafe_key_id,
            invitation_digest_keys_json=unsafe_keyring,
        )

    message = str(captured.value)
    assert "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID" in message
    assert "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON" in message
    assert unsafe_key_id not in message
    assert unsafe_keyring not in message


def test_validate_production_reports_all_unsafe_values(
    invitation_public_key_configuration: tuple[str, str],
) -> None:
    invitation_key_id, invitation_public_key_b64 = invitation_public_key_configuration
    with pytest.raises(ImproperlyConfigured) as captured:
        validate_production(
            secret_key="development-secret",
            allowed_hosts=["*"],
            debug=True,
            database={
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": "test_production",
                "OPTIONS": {"options": "-c maru.authority_provenance_test_reset=on"},
            },
            runtime_database_role="\n",
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
            invitation_encryption_key_id=invitation_key_id,
            invitation_public_key_b64=invitation_public_key_b64,
            invitation_digest_active_key_id="digest-2026-08",
            invitation_digest_keys_json=json.dumps(
                {"digest-2026-08": base64.b64encode(b"d" * 32).decode("ascii")},
                separators=(",", ":"),
            ),
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
    assert "test_ prefix" in message
    assert "fixed PostgreSQL search path" in message
    assert "test-reset database option" in message
    assert "MARU_RUNTIME_DATABASE_ROLE" in message
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


def test_invitation_public_key_configuration_validation_is_strict_and_value_safe(
    invitation_public_key_configuration: tuple[str, str],
) -> None:
    invitation_key_id, invitation_public_key_b64 = invitation_public_key_configuration
    assert invitation_public_key_configuration_is_valid(
        invitation_key_id,
        invitation_public_key_b64,
    )

    invalid_configurations = [
        ("", invitation_public_key_b64),
        ("invalid/key-id", invitation_public_key_b64),
        (invitation_key_id, "not-base64"),
        (invitation_key_id, f" {invitation_public_key_b64}"),
    ]
    for key_id, public_key_b64 in invalid_configurations:
        assert not invitation_public_key_configuration_is_valid(
            key_id,
            public_key_b64,
        )


def test_invitation_token_key_configuration_validation_is_value_safe() -> None:
    encoded_key = base64.b64encode(b"k" * 32).decode("ascii")
    keyring_json = json.dumps({"digest-current": encoded_key}, separators=(",", ":"))
    assert invitation_token_key_configuration_is_valid(
        "digest-current",
        keyring_json,
    )
    assert not invitation_token_key_configuration_is_valid(
        "digest-missing",
        keyring_json,
    )


@pytest.mark.parametrize(
    "origin",
    [
        "https://maru.example",
        "https://maru.example:8443",
        "https://127.0.0.1:8443",
        "https://[2001:db8::1]:8443",
        "https://xn--maru-9ta.example",
    ],
)
def test_normalized_https_origin_accepts_only_canonical_origins(origin: str) -> None:
    assert normalized_https_origin(origin) == origin


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        " https://maru.example",
        "HTTPS://maru.example",
        "http://maru.example",
        "https://operator@maru.example",
        "https://operator:secret@maru.example",
        "https://maru.example/",
        "https://maru.example/invitations",
        "https://maru.example?next=elsewhere",
        "https://maru.example#fragment",
        "https://MARU.example",
        "https://maru.example:443",
        "https://maru.example.",
        "https://máru.example",
        "https://bad_host.example",
        "https://maru.example\n.evil.invalid",
    ],
)
def test_normalized_https_origin_rejects_aliases_and_url_components(
    candidate: object,
) -> None:
    assert normalized_https_origin(candidate) is None


def test_validate_production_rejects_a_non_origin_public_base_url(
    invitation_public_key_configuration: tuple[str, str],
) -> None:
    invitation_key_id, invitation_public_key_b64 = invitation_public_key_configuration
    with pytest.raises(ImproperlyConfigured, match="normalized HTTPS origin"):
        validate_production(
            secret_key="s" * 50,
            allowed_hosts=["maru.example"],
            debug=False,
            database={
                "ENGINE": "django.db.backends.postgresql",
                "OPTIONS": {"options": POSTGRES_CONNECTION_OPTIONS},
            },
            runtime_database_role="maru_runtime",
            public_base_url="https://operator@maru.example/invitations?unsafe=1",
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
            invitation_encryption_key_id=invitation_key_id,
            invitation_public_key_b64=invitation_public_key_b64,
            invitation_digest_active_key_id="digest-2026-08",
            invitation_digest_keys_json=json.dumps(
                {"digest-2026-08": base64.b64encode(b"d" * 32).decode("ascii")},
                separators=(",", ":"),
            ),
            allow_provisional_registration=False,
            expose_identity_test_tokens=False,
            expose_credential_test_tokens=False,
            require_privileged_step_up=True,
            enforce_closure_gates=True,
        )


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
