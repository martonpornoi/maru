"""Versioned HMAC keys for invitation-token lookup and abuse buckets."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from django.conf import settings

ACTIVE_KEY_ID_SETTING: Final = "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID"
KEYRING_SETTING: Final = "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON"
MAX_DIGEST_KEYS: Final = 4
MIN_DIGEST_KEY_BYTES: Final = 32
MAX_DIGEST_KEY_BYTES: Final = 64
MAX_KEYRING_JSON_CHARACTERS: Final = 1_024
MAX_DIGEST_INPUT_CHARACTERS: Final = 4_096
_KEY_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
_PURPOSE_PATTERN: Final = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_DOMAIN_SEPARATOR: Final = b"maru.page10.invitation-digest.v1\0"


class InvitationTokenKeyConfigurationError(RuntimeError):
    """A value-safe signal that token-digest keys are unavailable or malformed."""

    def __init__(self) -> None:
        super().__init__("Invitation token protection is unavailable.")


def _configuration_error() -> InvitationTokenKeyConfigurationError:
    return InvitationTokenKeyConfigurationError()


def _decode_key(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() for character in value)
    ):
        raise _configuration_error()
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise _configuration_error() from None
    if (
        not MIN_DIGEST_KEY_BYTES <= len(decoded) <= MAX_DIGEST_KEY_BYTES
        or base64.b64encode(decoded) != encoded
    ):
        raise _configuration_error()
    return decoded


@dataclass(frozen=True, slots=True)
class InvitationTokenKeyring:
    """One active digest key plus bounded fallback keys for safe rotation."""

    active_key_id: str
    _keys: MappingProxyType[str, bytes]

    @classmethod
    def from_json(
        cls,
        *,
        active_key_id: object,
        keyring_json: object,
    ) -> InvitationTokenKeyring:
        if (
            not isinstance(active_key_id, str)
            or _KEY_ID_PATTERN.fullmatch(active_key_id) is None
            or not isinstance(keyring_json, str)
            or not 1 <= len(keyring_json) <= MAX_KEYRING_JSON_CHARACTERS
        ):
            raise _configuration_error()
        try:
            decoded = json.loads(keyring_json)
        except (TypeError, ValueError):
            raise _configuration_error() from None
        if (
            not isinstance(decoded, dict)
            or not 1 <= len(decoded) <= MAX_DIGEST_KEYS
            or active_key_id not in decoded
            or any(
                not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None
                for key_id in decoded
            )
        ):
            raise _configuration_error()
        keys = {key_id: _decode_key(value) for key_id, value in decoded.items()}
        return cls(
            active_key_id=active_key_id,
            _keys=MappingProxyType(keys),
        )

    @property
    def key_ids(self) -> tuple[str, ...]:
        return (
            self.active_key_id,
            *(key_id for key_id in self._keys if key_id != self.active_key_id),
        )

    def digest(self, value: str, *, purpose: str, key_id: str | None = None) -> str:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= MAX_DIGEST_INPUT_CHARACTERS
            or _PURPOSE_PATTERN.fullmatch(purpose) is None
        ):
            raise _configuration_error()
        selected_key_id = self.active_key_id if key_id is None else key_id
        key = self._keys.get(selected_key_id)
        if key is None:
            raise _configuration_error()
        message = _DOMAIN_SEPARATOR + purpose.encode("ascii") + b"\0" + value.encode()
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def candidates(self, value: str, *, purpose: str) -> tuple[tuple[str, str], ...]:
        return tuple(
            (key_id, self.digest(value, purpose=purpose, key_id=key_id))
            for key_id in self.key_ids
        )


def invitation_token_keyring() -> InvitationTokenKeyring:
    """Load the web-visible token digest keyring from value-safe settings."""

    return InvitationTokenKeyring.from_json(
        active_key_id=getattr(settings, ACTIVE_KEY_ID_SETTING, ""),
        keyring_json=getattr(settings, KEYRING_SETTING, ""),
    )


def invitation_token_keys_are_ready() -> bool:
    try:
        invitation_token_keyring()
    except InvitationTokenKeyConfigurationError:
        return False
    return True


__all__ = [
    "ACTIVE_KEY_ID_SETTING",
    "KEYRING_SETTING",
    "InvitationTokenKeyConfigurationError",
    "InvitationTokenKeyring",
    "invitation_token_keyring",
    "invitation_token_keys_are_ready",
]
