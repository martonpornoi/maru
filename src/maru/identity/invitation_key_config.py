"""Process-separated key configuration for invitation delivery.

Web processes load only the active public key from Django settings. Delivery
workers opt in to loading a bounded private-key ring from their own process
environment. Keeping the worker secret out of Django settings makes accidental
use by request handlers visible and testable.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import TYPE_CHECKING, Final

from django.conf import settings

from maru.identity.invitation_crypto import (
    MAX_PRIVATE_KEYRING_KEYS,
    InvitationCryptoConfigurationError,
    InvitationEncryptionKey,
    InvitationPrivateKeyring,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

PUBLIC_KEY_ID_SETTING: Final = "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID"
PUBLIC_KEY_SETTING: Final = "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64"
PRIVATE_KEYRING_ENVIRONMENT: Final = "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON"
MAX_BASE64_PEM_CHARACTERS: Final = 48_000
MAX_PRIVATE_KEYRING_JSON_CHARACTERS: Final = 1_600_000


def _configuration_error() -> InvitationCryptoConfigurationError:
    return InvitationCryptoConfigurationError()


def _decode_base64_pem(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_BASE64_PEM_CHARACTERS
        or any(character.isspace() for character in value)
    ):
        raise _configuration_error()
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise _configuration_error() from None
    if base64.b64encode(decoded) != encoded:
        raise _configuration_error()
    return decoded


def active_invitation_encryption_key() -> InvitationEncryptionKey:
    """Load the public key that the current web release may use.

    Returns
    -------
    InvitationEncryptionKey
        The InvitationEncryptionKey produced by active invitation encryption
        key.

    Raises
    ------
    _configuration_error
        If the operation encounters a configuration error condition.
    """
    key_id = getattr(settings, PUBLIC_KEY_ID_SETTING, "")
    public_key_b64 = getattr(settings, PUBLIC_KEY_SETTING, "")
    if not isinstance(key_id, str):
        raise _configuration_error()
    return InvitationEncryptionKey.from_pem(
        encryption_key_id=key_id,
        public_key_pem=_decode_base64_pem(public_key_b64),
    )


def worker_invitation_private_keyring(
    environment: Mapping[str, str] | None = None,
) -> InvitationPrivateKeyring:
    """Load worker-only private keys without copying them into settings.

    Parameters
    ----------
    environment : Mapping[str, str] | None, default=None
        The environment mapping to validate or transform.

    Returns
    -------
    InvitationPrivateKeyring
        The InvitationPrivateKeyring produced by worker invitation private
        keyring.

    Raises
    ------
    _configuration_error
        If the operation encounters a configuration error condition.
    """
    source = os.environ if environment is None else environment
    raw = source.get(PRIVATE_KEYRING_ENVIRONMENT, "")
    if not isinstance(raw, str) or not (
        1 <= len(raw) <= MAX_PRIVATE_KEYRING_JSON_CHARACTERS
    ):
        raise _configuration_error()
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        raise _configuration_error() from None
    if (
        not isinstance(decoded, dict)
        or not 1 <= len(decoded) <= MAX_PRIVATE_KEYRING_KEYS
        or any(not isinstance(key, str) for key in decoded)
    ):
        raise _configuration_error()
    private_key_pems: dict[str, bytes] = {}
    for key_id, encoded_pem in decoded.items():
        private_key_pems[key_id] = _decode_base64_pem(encoded_pem)
    return InvitationPrivateKeyring.from_pem(private_key_pems)


def invitation_encryption_is_ready() -> bool:
    """Return a value-safe readiness signal for the request process.

    Returns
    -------
    bool
        `True` when Return a value-safe readiness signal for the request
        process; otherwise `False`.
    """
    try:
        active_invitation_encryption_key()
    except InvitationCryptoConfigurationError:
        return False
    return True


__all__ = [
    "PRIVATE_KEYRING_ENVIRONMENT",
    "PUBLIC_KEY_ID_SETTING",
    "PUBLIC_KEY_SETTING",
    "active_invitation_encryption_key",
    "invitation_encryption_is_ready",
    "worker_invitation_private_keyring",
]
