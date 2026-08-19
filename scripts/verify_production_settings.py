"""Verify production settings with one deterministic, non-secret fixture."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
MANAGE_PY: Final = REPOSITORY_ROOT / "src" / "manage.py"
EXACT_PROVENANCE_ENVIRONMENT: Final = "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE"
WORKER_PRIVATE_KEY_ENVIRONMENT: Final = "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON"
EXACT_PROVENANCE_VALUES: Final[tuple[Literal["false", "true"], ...]] = (
    "false",
    "true",
)

_INVITATION_PUBLIC_KEY_B64: Final = (
    "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0KTUlJQklqQU5CZ2txaGtpRzl3MEJBUUVGQUFPQ0"
    "FROEFNSUlCQ2dLQ0FRRUF0TVUwd1ZQVVZwSzZEOFU5RXVjOQpIY3Irc2YrL3l5ay9ya3NEYTdT"
    "YWpDR0lqSDFCOVZKSG0wZnh1am52azk5SWhPNHdkZ3BKeXltNUlIdWd0cmtoCm5JSTlvdHRGRF"
    "RqWHlSKzZ5Yis3a0NkTlRvU2xoU1lFaitPYnFiTXJaaTBFdHZrRmFTYzl3SHV3WFZVMHFSTG8K"
    "SHhUdUpwMXkxQmNMY1dLd0xjSU9mUmJMdTJpMEJ3eDN4YytLV3FLUFM5ZVNta0tKUnh3VE1obG"
    "d3OGNBK3dQUApBRm1uQXZQRnVLRUxnYXVseEw3L2FkdFJsaTEvZVpiNm4wWjZKS09iWGJHWmo1"
    "bEtPVEw5OHpUWURpRXlzcFdDClF6OTZmd3A5R0xLeHlob0dUSmdaV2JqMlE0ZUoxRjFGMFMraE"
    "xPZmdtS3RtNkNYQzgzYzRmUWhzQnFzNkdnREwKWFFJREFRQUIKLS0tLS1FTkQgUFVCTElDIEtF"
    "WS0tLS0tCg=="
)

# These values validate configuration shape only. They are intentionally synthetic,
# public, deterministic, and unsuitable for a deployed Maru environment.
VERIFICATION_ENVIRONMENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DJANGO_SETTINGS_MODULE": "maru.settings.production",
        "MARU_SETTINGS_MODULE": "maru.settings.production",
        "MARU_SECRET_KEY": (
            "verification-only-not-a-production-secret-at-least-50-characters"
        ),
        "MARU_ALLOWED_HOSTS": "maru.example.invalid",
        "MARU_DATABASE_URL": ("postgresql://maru:maru@127.0.0.1:5432/maru"),
        "MARU_RUNTIME_DATABASE_ROLE": "maru_runtime",
        "MARU_PUBLIC_BASE_URL": "https://maru.example.invalid",
        "MARU_DEFAULT_FROM_EMAIL": "registration@example.com",
        "MARU_EMAIL_HOST": "smtp.example.invalid",
        "MARU_EMAIL_PORT": "587",
        "MARU_EMAIL_HOST_USER": "verification-user",
        "MARU_EMAIL_HOST_PASSWORD": ("verification-password"),
        "MARU_EMAIL_USE_TLS": "true",
        "MARU_EMAIL_USE_SSL": "false",
        "MARU_CSRF_TRUSTED_ORIGINS": (
            "https://maru.example.invalid,https://register.maru.example.invalid"
        ),
        "MARU_PAYMENT_RETURN_ORIGINS": ("https://register.maru.example.invalid"),
        "MARU_PAYMENT_PROVIDER_HOSTS": (
            "payments.example.invalid,checkout.example.invalid"
        ),
        "MARU_REGISTRATION_CLIENT_ORIGINS": ("https://register.maru.example.invalid"),
        "MARU_MEDIA_SCANNER": "clamav",
        "MARU_MEDIA_SCANNER_HOST": "scanner.internal",
        "MARU_OFFLINE_MANIFEST_SECRET": (
            "verification-only-offline-manifest-secret-value"
        ),
        "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID": ("verification-key-2026-08"),
        "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64": _INVITATION_PUBLIC_KEY_B64,
        "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID": (
            "verification-digest-2026-08"
        ),
        "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON": (
            '{"verification-digest-2026-08":'
            '"AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="}'
        ),
    }
)


def verification_environment(
    parent_environment: Mapping[str, str],
    *,
    exact_provenance_required: Literal["false", "true"],
) -> dict[str, str]:
    """Build one isolated child environment without inherited Maru settings."""

    environment = {
        name: value
        for name, value in parent_environment.items()
        if not name.startswith("MARU_") and name != "DJANGO_SETTINGS_MODULE"
    }
    environment.update(VERIFICATION_ENVIRONMENT)
    environment[EXACT_PROVENANCE_ENVIRONMENT] = exact_provenance_required
    return environment


def verify_production_settings(
    parent_environment: Mapping[str, str] | None = None,
) -> int:
    """Run both supported exact-provenance settings in separate processes."""

    inherited_environment = (
        os.environ if parent_environment is None else parent_environment
    )
    command = (sys.executable, str(MANAGE_PY), "check", "--deploy")
    first_failure = 0
    for exact_provenance_required in EXACT_PROVENANCE_VALUES:
        completed = subprocess.run(  # noqa: S603 - fixed local command
            command,
            cwd=REPOSITORY_ROOT,
            env=verification_environment(
                inherited_environment,
                exact_provenance_required=exact_provenance_required,
            ),
            check=False,
        )
        if completed.returncode != 0 and first_failure == 0:
            first_failure = completed.returncode
    return first_failure


def main() -> None:
    raise SystemExit(verify_production_settings())


if __name__ == "__main__":
    main()
