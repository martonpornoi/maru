from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.checks import Error, Tags, run_checks
from django.core.checks import Warning as CheckWarning
from django.test import override_settings

from maru.identity.checks import (
    check_invitation_digest_key_configuration,
    check_invitation_encryption_configuration,
    check_invitation_public_origin_configuration,
)
from maru.identity.invitation_key_config import PRIVATE_KEYRING_ENVIRONMENT


@pytest.fixture(scope="module")
def public_key_configuration() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_key_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        "system-check-key-2026-08",
        base64.b64encode(public_key_pem).decode("ascii"),
    )


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=False,
    MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="",
    MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64="",
)
def test_unconfigured_local_environment_warns_and_fails_commands_closed() -> None:
    messages = check_invitation_encryption_configuration()

    assert len(messages) == 1
    assert isinstance(messages[0], CheckWarning)
    assert messages[0].id == "identity.W001"
    assert "commands fail closed" in messages[0].msg
    assert "Private keys" in messages[0].hint


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
    MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="unsafe key id",
    MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64="sensitive-malformed-public-value",
)
def test_required_environment_reports_value_safe_error() -> None:
    messages = check_invitation_encryption_configuration()

    assert len(messages) == 1
    assert isinstance(messages[0], Error)
    assert messages[0].id == "identity.E001"
    rendered = repr(messages[0])
    assert "unsafe key id" not in rendered
    assert "sensitive-malformed-public-value" not in rendered


def test_valid_public_configuration_is_ready_without_a_private_key_setting(
    public_key_configuration: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id, public_key_b64 = public_key_configuration
    worker_only_value = '{"worker-key":"private-material-must-not-be-read"}'
    monkeypatch.setenv(PRIVATE_KEYRING_ENVIRONMENT, worker_only_value)

    with override_settings(
        IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
        MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID=key_id,
        MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64=public_key_b64,
    ):
        assert check_invitation_encryption_configuration() == []


def test_identity_check_is_registered_under_the_security_tag() -> None:
    with override_settings(
        IDENTITY_INVITATION_ENCRYPTION_REQUIRED=False,
        MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="",
        MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64="",
    ):
        identity_messages = [
            message
            for message in run_checks(tags=[Tags.security])
            if message.id == "identity.W001"
        ]

    assert len(identity_messages) == 1


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
    MARU_PUBLIC_BASE_URL="https://operator@maru.example/invitations?unsafe=1",
)
def test_required_invitation_origin_reports_a_value_safe_error() -> None:
    messages = check_invitation_public_origin_configuration()

    assert len(messages) == 1
    assert isinstance(messages[0], Error)
    assert messages[0].id == "identity.E002"
    rendered = repr(messages[0])
    assert "operator" not in rendered
    assert "unsafe" not in rendered


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
    MARU_PUBLIC_BASE_URL="https://maru.example",
)
def test_required_invitation_origin_accepts_one_normalized_https_origin() -> None:
    assert check_invitation_public_origin_configuration() == []


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=False,
    MARU_PUBLIC_BASE_URL="http://127.0.0.1:8000",
)
def test_optional_local_invitation_origin_remains_development_compatible() -> None:
    assert check_invitation_public_origin_configuration() == []


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
    MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID="unsafe/key",
    MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=(
        '{"unsafe/key":"sensitive-malformed-value"}'
    ),
)
def test_required_digest_keyring_reports_a_value_safe_error() -> None:
    messages = check_invitation_digest_key_configuration()

    assert len(messages) == 1
    assert isinstance(messages[0], Error)
    assert messages[0].id == "identity.E003"
    rendered = repr(messages[0])
    assert "unsafe/key" not in rendered
    assert "sensitive-malformed-value" not in rendered


@override_settings(
    IDENTITY_INVITATION_ENCRYPTION_REQUIRED=False,
    MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID="",
    MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON="",
)
def test_optional_local_digest_keyring_remains_development_compatible() -> None:
    assert check_invitation_digest_key_configuration() == []
