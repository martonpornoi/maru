"""Small, strict environment configuration helpers."""

import base64
import binascii
import ipaddress
import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

from maru.identity.invitation_crypto import (
    InvitationCryptoConfigurationError,
    InvitationEncryptionKey,
)
from maru.identity.invitation_token_keys import (
    InvitationTokenKeyConfigurationError,
    InvitationTokenKeyring,
)

TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES: Final = frozenset({"0", "false", "no", "off"})
MINIMUM_PRODUCTION_SECRET_LENGTH: Final = 50
MINIMUM_OFFLINE_SECRET_LENGTH: Final = 32
POSTGRES_CONNECTION_OPTIONS: Final = "-c search_path=public,pg_temp"
POSTGRES_IDENTIFIER_MAX_BYTES: Final = 63
MAX_INVITATION_PUBLIC_KEY_B64_CHARACTERS: Final = 48_000
HTTPS_DEFAULT_PORT: Final = 443
DNS_HOSTNAME_MAX_CHARACTERS: Final = 253
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required")
    return value


def csv_value(environment: Mapping[str, str], name: str) -> list[str]:
    raw_value = environment.get(name, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def boolean(
    environment: Mapping[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    raw_value = environment.get(name)
    if raw_value is None:
        return default

    value = raw_value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of: {', '.join(sorted(TRUE_VALUES | FALSE_VALUES))}"
    )


def required_boolean(environment: Mapping[str, str], name: str) -> bool:
    """Parse one explicitly declared boolean environment value."""

    required(environment, name)
    return boolean(environment, name, default=False)


def postgres_database(url: str) -> dict[str, object]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("MARU_DATABASE_URL must use PostgreSQL")
    if not parsed.hostname:
        raise ImproperlyConfigured("MARU_DATABASE_URL must include a host")

    database_name = parsed.path.removeprefix("/")
    if not database_name or "/" in database_name:
        raise ImproperlyConfigured("MARU_DATABASE_URL must include one database name")

    options = dict(parse_qsl(parsed.query, keep_blank_values=False))
    if "options" in options:
        raise ImproperlyConfigured(
            "MARU_DATABASE_URL cannot set PostgreSQL options; Maru owns the "
            "connection search path"
        )
    options.setdefault("connect_timeout", "3")
    options["options"] = POSTGRES_CONNECTION_OPTIONS
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(database_name),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }


def invitation_public_key_configuration_is_valid(
    encryption_key_id: object,
    public_key_b64: object,
) -> bool:
    """Validate public-only invitation key configuration without releasing values."""

    if (
        not isinstance(encryption_key_id, str)
        or not isinstance(public_key_b64, str)
        or not 1 <= len(public_key_b64) <= MAX_INVITATION_PUBLIC_KEY_B64_CHARACTERS
        or any(character.isspace() for character in public_key_b64)
    ):
        return False
    try:
        encoded = public_key_b64.encode("ascii")
        public_key_pem = base64.b64decode(encoded, validate=True)
        if base64.b64encode(public_key_pem) != encoded:
            return False
        InvitationEncryptionKey.from_pem(
            encryption_key_id=encryption_key_id,
            public_key_pem=public_key_pem,
        )
    except (
        UnicodeEncodeError,
        binascii.Error,
        ValueError,
        InvitationCryptoConfigurationError,
    ):
        return False
    return True


def normalized_https_origin(value: object) -> str | None:  # noqa: PLR0911
    """Return one canonical HTTPS origin, or ``None`` for any URL-like value.

    Invitation links are a bearer-secret boundary.  Requiring the configured
    public base URL to already equal its canonical origin form prevents a
    user-info component, path, query, fragment, default-port alias, Unicode
    hostname alias, or case variant from changing where that secret is sent.
    """

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isprintable()
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port == HTTPS_DEFAULT_PORT
    ):
        return None
    hostname = parsed.hostname
    if hostname is None or hostname.endswith("."):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").casefold()
        except UnicodeError:
            return None
        labels = ascii_hostname.split(".")
        if (
            len(ascii_hostname) > DNS_HOSTNAME_MAX_CHARACTERS
            or not labels
            or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        ):
            return None
        canonical_host = ascii_hostname
    else:
        canonical_host = (
            f"[{address.compressed}]"
            if isinstance(address, ipaddress.IPv6Address)
            else address.compressed
        )
    canonical_netloc = canonical_host if port is None else f"{canonical_host}:{port}"
    canonical_origin = f"https://{canonical_netloc}"
    return canonical_origin if value == canonical_origin else None


def invitation_token_key_configuration_is_valid(
    active_key_id: object,
    keyring_json: object,
) -> bool:
    """Validate the bounded versioned HMAC keyring without releasing values."""

    try:
        InvitationTokenKeyring.from_json(
            active_key_id=active_key_id,
            keyring_json=keyring_json,
        )
    except InvitationTokenKeyConfigurationError:
        return False
    return True


def validate_production(  # noqa: PLR0912, PLR0915
    *,
    secret_key: str,
    allowed_hosts: list[str],
    debug: bool,
    database: Mapping[str, object],
    runtime_database_role: str,
    public_base_url: str,
    default_from_email: str,
    email_backend: str,
    email_host: str,
    email_use_tls: bool,
    email_use_ssl: bool,
    payment_return_origins: list[str],
    payment_provider_hosts: list[str],
    registration_client_origins: list[str],
    csrf_trusted_origins: list[str],
    media_scanner: str,
    media_scanner_host: str,
    offline_manifest_secret: str,
    invitation_encryption_key_id: str,
    invitation_public_key_b64: str,
    invitation_digest_active_key_id: str,
    invitation_digest_keys_json: str,
    allow_provisional_registration: bool,
    expose_identity_test_tokens: bool,
    expose_credential_test_tokens: bool,
    require_privileged_step_up: bool,
    enforce_closure_gates: bool,
) -> None:
    errors: list[str] = []
    if len(secret_key) < MINIMUM_PRODUCTION_SECRET_LENGTH or secret_key.startswith(
        ("development", "change-me")
    ):
        errors.append(
            "MARU_SECRET_KEY must be a strong value of at least 50 characters"
        )
    if not allowed_hosts:
        errors.append("MARU_ALLOWED_HOSTS must contain at least one host")
    if "*" in allowed_hosts:
        errors.append("MARU_ALLOWED_HOSTS cannot contain a wildcard")
    if debug:
        errors.append("DEBUG cannot be enabled in production")
    if database.get("ENGINE") != "django.db.backends.postgresql":
        errors.append("production requires PostgreSQL")
    database_name = str(database.get("NAME", "")).strip()
    if database_name.casefold().startswith("test_"):
        errors.append("production database names cannot use the test_ prefix")
    database_options = database.get("OPTIONS")
    if not isinstance(database_options, Mapping) or (
        str(database_options.get("options", "")).strip() != POSTGRES_CONNECTION_OPTIONS
    ):
        errors.append("production requires Maru's fixed PostgreSQL search path")
    if isinstance(database_options, Mapping) and (
        "maru.authority_provenance_test_reset"
        in str(database_options.get("options", "")).casefold()
    ):
        errors.append(
            "the authority provenance test-reset database option is forbidden "
            "in production"
        )
    runtime_role_bytes = runtime_database_role.encode("utf-8")
    if (
        not runtime_database_role
        or runtime_database_role != runtime_database_role.strip()
        or len(runtime_role_bytes) > POSTGRES_IDENTIFIER_MAX_BYTES
        or not runtime_database_role.isprintable()
    ):
        errors.append(
            "MARU_RUNTIME_DATABASE_ROLE must name one explicit printable "
            "PostgreSQL role of at most 63 UTF-8 bytes"
        )
    if normalized_https_origin(public_base_url) is None:
        errors.append(
            "MARU_PUBLIC_BASE_URL must be one normalized HTTPS origin without "
            "userinfo, path, query, or fragment"
        )
    if "@" not in default_from_email or default_from_email.casefold().endswith(
        ".invalid"
    ):
        errors.append("MARU_DEFAULT_FROM_EMAIL must be a deliverable address")
    if (
        email_backend != "django.core.mail.backends.smtp.EmailBackend"
        or not email_host.strip()
        or email_use_tls == email_use_ssl
    ):
        errors.append(
            "production email must use an SMTP host with exactly one of TLS or SSL"
        )
    if not payment_return_origins or any(
        urlsplit(origin).scheme != "https" or not urlsplit(origin).netloc
        for origin in payment_return_origins
    ):
        errors.append("MARU_PAYMENT_RETURN_ORIGINS must contain only HTTPS origins")
    if not payment_provider_hosts or any(
        not host
        or "://" in host
        or "/" in host
        or host.startswith(".")
        or host.endswith(".")
        for host in payment_provider_hosts
    ):
        errors.append(
            "MARU_PAYMENT_PROVIDER_HOSTS must contain explicit provider host names"
        )
    if not registration_client_origins or any(
        urlsplit(origin).scheme != "https" or not urlsplit(origin).netloc
        for origin in registration_client_origins
    ):
        errors.append(
            "MARU_REGISTRATION_CLIENT_ORIGINS must contain only explicit HTTPS origins"
        )
    if not set(registration_client_origins).issubset(set(csrf_trusted_origins)):
        errors.append(
            "MARU_CSRF_TRUSTED_ORIGINS must include every registration client origin"
        )
    if media_scanner != "clamav" or not media_scanner_host.strip():
        errors.append(
            "MARU_MEDIA_SCANNER must be clamav and MARU_MEDIA_SCANNER_HOST is required"
        )
    if len(offline_manifest_secret) < MINIMUM_OFFLINE_SECRET_LENGTH:
        errors.append(
            "MARU_OFFLINE_MANIFEST_SECRET must contain at least 32 characters"
        )
    if not invitation_public_key_configuration_is_valid(
        invitation_encryption_key_id,
        invitation_public_key_b64,
    ):
        errors.append(
            "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID and "
            "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 must configure one "
            "supported RSA public key"
        )
    if not invitation_token_key_configuration_is_valid(
        invitation_digest_active_key_id,
        invitation_digest_keys_json,
    ):
        errors.append(
            "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID and "
            "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON must configure one "
            "bounded versioned HMAC keyring"
        )
    if allow_provisional_registration:
        errors.append("provisional public registration cannot be enabled")
    if expose_identity_test_tokens or expose_credential_test_tokens:
        errors.append("test bearer-token exposure cannot be enabled")
    if not require_privileged_step_up:
        errors.append("privileged step-up cannot be disabled")
    if not enforce_closure_gates:
        errors.append("edition closure gates cannot be disabled")

    if errors:
        raise ImproperlyConfigured("; ".join(errors))
