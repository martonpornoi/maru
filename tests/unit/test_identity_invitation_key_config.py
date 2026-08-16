from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings

from maru.identity.invitation_crypto import (
    InvitationCryptoConfigurationError,
    decrypt_invitation_payload,
    encrypt_invitation_payload,
)
from maru.identity.invitation_key_config import (
    PRIVATE_KEYRING_ENVIRONMENT,
    active_invitation_encryption_key,
    invitation_encryption_is_ready,
    worker_invitation_private_keyring,
)


def _key_material() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return (
        base64.b64encode(public_pem).decode("ascii"),
        base64.b64encode(private_pem).decode("ascii"),
    )


def test_web_public_key_and_worker_private_keyring_are_separate() -> None:
    public_key_b64, private_key_b64 = _key_material()
    environment = {
        PRIVATE_KEYRING_ENVIRONMENT: json.dumps({"2026-08-primary": private_key_b64})
    }
    with override_settings(
        MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="2026-08-primary",
        MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64=public_key_b64,
    ):
        public_key = active_invitation_encryption_key()
        assert invitation_encryption_is_ready() is True
    private_keyring = worker_invitation_private_keyring(environment)

    envelope = encrypt_invitation_payload(
        payload=b"single-use-secret",
        aad=b"invitation/123/version/1",
        active_key=public_key,
    )
    assert (
        decrypt_invitation_payload(
            envelope=envelope,
            expected_aad=b"invitation/123/version/1",
            private_keyring=private_keyring,
        )
        == b"single-use-secret"
    )


@override_settings(
    MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID="",
    MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64="",
)
def test_missing_web_key_fails_closed_without_exposing_configuration() -> None:
    assert invitation_encryption_is_ready() is False
    with pytest.raises(
        InvitationCryptoConfigurationError,
        match="configuration is invalid",
    ):
        active_invitation_encryption_key()


@pytest.mark.parametrize(
    "raw",
    ["", "[]", "not-json", '{"bad id!":"AAAA"}', '{"key":"not base64"}'],
)
def test_worker_keyring_rejects_invalid_or_empty_configuration(raw: str) -> None:
    with pytest.raises(
        InvitationCryptoConfigurationError,
        match="configuration is invalid",
    ):
        worker_invitation_private_keyring({PRIVATE_KEYRING_ENVIRONMENT: raw})
