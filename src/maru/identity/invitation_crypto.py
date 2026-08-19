"""Bounded envelope encryption for invitation delivery payloads.

The web process needs only :class:`InvitationEncryptionKey`.  A delivery
worker must explicitly construct an :class:`InvitationPrivateKeyring` before
it can decrypt an envelope.  No key is read from Django settings or process
environment in this module.

Binary ciphertext fields are unpadded base64url stored as ASCII ``bytes`` so
they are safe for a database binary field and for transports which require a
URL-safe alphabet.  The nonce remains its exact 12-byte AES-GCM value.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENCRYPTION_ALGORITHM: Final = "aes-256-gcm+rsa-oaep-sha256-v1"
MAX_ENCRYPTION_KEY_ID_LENGTH: Final = 64
MAX_INVITATION_PAYLOAD_BYTES: Final = 4_096
MAX_INVITATION_AAD_BYTES: Final = 1_024
MAX_PRIVATE_KEYRING_KEYS: Final = 32
MAX_PEM_BYTES: Final = 32_768
MAX_PRIVATE_KEY_PASSWORD_BYTES: Final = 1_024

_AES_KEY_BYTES: Final = 32
_AES_GCM_NONCE_BYTES: Final = 12
_AES_GCM_TAG_BYTES: Final = 16
_SUPPORTED_RSA_KEY_SIZES: Final = frozenset({2_048, 3_072, 4_096})
_MIN_WRAPPED_KEY_BYTES: Final = min(_SUPPORTED_RSA_KEY_SIZES) // 8
_MAX_WRAPPED_KEY_BYTES: Final = max(_SUPPORTED_RSA_KEY_SIZES) // 8
_MAX_ENCRYPTED_PAYLOAD_BYTES: Final = MAX_INVITATION_PAYLOAD_BYTES + _AES_GCM_TAG_BYTES
_MAX_ENCODED_PAYLOAD_BYTES: Final = (_MAX_ENCRYPTED_PAYLOAD_BYTES * 4 + 2) // 3
_MAX_ENCODED_WRAPPED_KEY_BYTES: Final = (_MAX_WRAPPED_KEY_BYTES * 4 + 2) // 3
_KEY_ID_PATTERN: Final = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_ENCRYPTION_KEY_ID_LENGTH - 1}}}",
    flags=re.ASCII,
)
_BASE64URL_PATTERN: Final = re.compile(rb"[A-Za-z0-9_-]+", flags=re.ASCII)
_LOWER_HEX_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_OAEP_LABEL: Final = ENCRYPTION_ALGORITHM.encode("ascii")
_AAD_DOMAIN: Final = b"maru.identity.invitation-delivery-aad.v1"


class InvitationCryptoError(RuntimeError):
    """Base class whose public text never includes cryptographic input."""

    _safe_message = "Invitation payload cryptography failed."

    def __init__(self) -> None:
        """Initialize the InvitationCryptoError instance."""
        super().__init__(self._safe_message)


class InvitationCryptoConfigurationError(InvitationCryptoError):
    """The supplied key identifier or key material is not supported."""

    _safe_message = "Invitation cryptography configuration is invalid."


class InvitationCryptoPayloadError(InvitationCryptoError):
    """A payload or persisted envelope violates the bounded format."""

    _safe_message = "Invitation payload format is invalid."


class InvitationPayloadEncryptionError(InvitationCryptoError):
    """Encryption failed without exposing the payload or provider detail."""

    _safe_message = "Invitation payload encryption failed."


class InvitationPayloadDecryptionError(InvitationCryptoError):
    """Decryption or authenticated-AAD verification failed generically."""

    _safe_message = "Invitation payload decryption failed."


class InvitationDecryptionKeyUnavailableError(InvitationPayloadDecryptionError):
    """No worker-side private key is available for an envelope's key id."""


def _validate_key_id(encryption_key_id: object) -> str:
    if (
        not isinstance(encryption_key_id, str)
        or _KEY_ID_PATTERN.fullmatch(encryption_key_id) is None
    ):
        raise InvitationCryptoConfigurationError
    return encryption_key_id


def _validate_rsa_key_size(key_size: int) -> None:
    if key_size not in _SUPPORTED_RSA_KEY_SIZES:
        raise InvitationCryptoConfigurationError


def _validate_public_key(public_key: object) -> rsa.RSAPublicKey:
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise InvitationCryptoConfigurationError
    _validate_rsa_key_size(public_key.key_size)
    return public_key


def _validate_private_key(private_key: object) -> rsa.RSAPrivateKey:
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise InvitationCryptoConfigurationError
    _validate_rsa_key_size(private_key.key_size)
    return private_key


def _validate_bounded_bytes(
    value: object,
    *,
    minimum: int,
    maximum: int,
) -> bytes:
    if not isinstance(value, bytes) or not minimum <= len(value) <= maximum:
        raise InvitationCryptoPayloadError
    return value


def _base64url_encode(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _base64url_decode(
    value: object,
    *,
    minimum_decoded: int,
    maximum_decoded: int,
    maximum_encoded: int,
) -> bytes:
    encoded = _validate_bounded_bytes(
        value,
        minimum=1,
        maximum=maximum_encoded,
    )
    if _BASE64URL_PATTERN.fullmatch(encoded) is None:
        raise InvitationCryptoPayloadError
    padding_bytes = b"=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(
            encoded + padding_bytes,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError):
        raise InvitationCryptoPayloadError from None
    if (
        not minimum_decoded <= len(decoded) <= maximum_decoded
        or _base64url_encode(decoded) != encoded
    ):
        raise InvitationCryptoPayloadError
    return decoded


def _aad_digest(aad: bytes) -> str:
    return hashlib.sha256(aad).hexdigest()


def _authenticated_aad(*, encryption_key_id: str, aad: bytes) -> bytes:
    return b"\x00".join(
        (
            _AAD_DOMAIN,
            ENCRYPTION_ALGORITHM.encode("ascii"),
            encryption_key_id.encode("ascii"),
            aad,
        )
    )


def _oaep_padding() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=_OAEP_LABEL,
    )


@dataclass(frozen=True, slots=True, repr=False)
class InvitationEncryptionKey:
    """The active public key which a request process may safely hold.

    Attributes
    ----------
    encryption_key_id
        The encryption key identifier within the requested scope.
    public_key
        The stable public key used to authenticate or deduplicate the operation.
    """

    encryption_key_id: str
    public_key: rsa.RSAPublicKey

    def __post_init__(self) -> None:
        """Implement `__post_init__` for InvitationEncryptionKey."""
        _validate_key_id(self.encryption_key_id)
        _validate_public_key(self.public_key)

    @classmethod
    def from_pem(
        cls,
        *,
        encryption_key_id: str,
        public_key_pem: bytes,
    ) -> InvitationEncryptionKey:
        """Return from pem.

        Parameters
        ----------
        encryption_key_id : str
            The encryption key identifier within the requested scope.
        public_key_pem : bytes
            The PEM-encoded public key key material to validate.

        Returns
        -------
        InvitationEncryptionKey
            The resolved InvitationEncryptionKey for from pem.
        """
        return cls(
            encryption_key_id=encryption_key_id,
            public_key=load_invitation_public_key(public_key_pem),
        )

    def __repr__(self) -> str:
        """Return a diagnostic InvitationEncryptionKey representation.

        Returns
        -------
        str
            A diagnostic representation of the value.
        """
        return "InvitationEncryptionKey([redacted])"


@dataclass(frozen=True, slots=True, repr=False)
class EncryptedInvitationPayload:
    """Immutable, separately persistable invitation delivery envelope.

    Attributes
    ----------
    encryption_algorithm
        The encryption algorithm retained in this immutable projection.
    encryption_key_id
        The encryption key identifier within the requested scope.
    encrypted_payload
        The encrypted payload retained in this immutable projection.
    wrapped_data_key
        The stable wrapped data key used to authenticate or deduplicate the
        operation.
    payload_nonce
        The payload nonce retained in this immutable projection.
    payload_aad_digest
        The canonical digest used to verify payload aad.
    """

    encryption_algorithm: str
    encryption_key_id: str
    encrypted_payload: bytes
    wrapped_data_key: bytes
    payload_nonce: bytes
    payload_aad_digest: str

    def __post_init__(self) -> None:
        """Implement `__post_init__` for EncryptedInvitationPayload.

        Raises
        ------
        InvitationCryptoPayloadError
            If the requested operation violates this domain contract.
        """
        if self.encryption_algorithm != ENCRYPTION_ALGORITHM:
            raise InvitationCryptoPayloadError
        _validate_key_id(self.encryption_key_id)
        _base64url_decode(
            self.encrypted_payload,
            minimum_decoded=_AES_GCM_TAG_BYTES + 1,
            maximum_decoded=_MAX_ENCRYPTED_PAYLOAD_BYTES,
            maximum_encoded=_MAX_ENCODED_PAYLOAD_BYTES,
        )
        wrapped_data_key = _base64url_decode(
            self.wrapped_data_key,
            minimum_decoded=_MIN_WRAPPED_KEY_BYTES,
            maximum_decoded=_MAX_WRAPPED_KEY_BYTES,
            maximum_encoded=_MAX_ENCODED_WRAPPED_KEY_BYTES,
        )
        if len(wrapped_data_key) * 8 not in _SUPPORTED_RSA_KEY_SIZES:
            raise InvitationCryptoPayloadError
        _validate_bounded_bytes(
            self.payload_nonce,
            minimum=_AES_GCM_NONCE_BYTES,
            maximum=_AES_GCM_NONCE_BYTES,
        )
        if (
            not isinstance(self.payload_aad_digest, str)
            or _LOWER_HEX_SHA256_PATTERN.fullmatch(self.payload_aad_digest) is None
        ):
            raise InvitationCryptoPayloadError

    def __repr__(self) -> str:
        """Return a diagnostic EncryptedInvitationPayload representation.

        Returns
        -------
        str
            A diagnostic representation of the value.
        """
        return "EncryptedInvitationPayload([redacted])"


class InvitationPrivateKeyring:
    """Worker-owned, bounded lookup for current and rotated private keys."""

    __slots__ = ("_private_keys",)

    def __init__(self, private_keys: Mapping[str, rsa.RSAPrivateKey]) -> None:
        """Initialize the InvitationPrivateKeyring instance.

        Parameters
        ----------
        private_keys : Mapping[str, rsa.RSAPrivateKey]
            The private keys mapping to validate or transform.

        Raises
        ------
        InvitationCryptoConfigurationError
            If the requested operation violates this domain contract.
        """
        if (
            not isinstance(private_keys, Mapping)
            or not 1 <= len(private_keys) <= MAX_PRIVATE_KEYRING_KEYS
        ):
            raise InvitationCryptoConfigurationError
        validated: dict[str, rsa.RSAPrivateKey] = {}
        for encryption_key_id, private_key in private_keys.items():
            validated[_validate_key_id(encryption_key_id)] = _validate_private_key(
                private_key
            )
        self._private_keys = MappingProxyType(validated)

    @classmethod
    def from_pem(
        cls,
        private_key_pems: Mapping[str, bytes],
        *,
        passwords: Mapping[str, bytes | None] | None = None,
    ) -> InvitationPrivateKeyring:
        """Return from pem.

        Parameters
        ----------
        private_key_pems : Mapping[str, bytes]
            The private key pems mapping to validate or transform.
        passwords : Mapping[str, bytes | None] | None, default=None
            The passwords mapping to validate or transform.

        Returns
        -------
        InvitationPrivateKeyring
            The resolved InvitationPrivateKeyring for from pem.

        Raises
        ------
        InvitationCryptoConfigurationError
            If the operation encounters a invitation crypto configuration condition.
        """
        if (
            not isinstance(private_key_pems, Mapping)
            or not 1 <= len(private_key_pems) <= MAX_PRIVATE_KEYRING_KEYS
        ):
            raise InvitationCryptoConfigurationError
        if passwords is None:
            supplied_passwords: Mapping[str, bytes | None] = {}
        elif isinstance(passwords, Mapping):
            supplied_passwords = passwords
        else:
            raise InvitationCryptoConfigurationError
        if not set(supplied_passwords).issubset(private_key_pems):
            raise InvitationCryptoConfigurationError
        loaded = {
            encryption_key_id: load_invitation_private_key(
                private_key_pem,
                password=supplied_passwords.get(encryption_key_id),
            )
            for encryption_key_id, private_key_pem in private_key_pems.items()
        }
        return cls(loaded)

    def _resolve(self, encryption_key_id: str) -> rsa.RSAPrivateKey:
        try:
            return self._private_keys[encryption_key_id]
        except KeyError:
            raise InvitationDecryptionKeyUnavailableError from None

    def contains(self, encryption_key_id: object) -> bool:
        """Return whether one validated rotation key is available.

        Parameters
        ----------
        encryption_key_id : object
            The encryption key identifier within the requested scope.

        Returns
        -------
        bool
            `True` when one validated rotation key is available; otherwise `False`.
        """
        try:
            validated_key_id = _validate_key_id(encryption_key_id)
        except InvitationCryptoConfigurationError:
            return False
        return validated_key_id in self._private_keys

    @property
    def key_ids(self) -> tuple[str, ...]:
        """Expose only bounded identifiers for worker-side coverage checks.

        Returns
        -------
        tuple[str, ...]
            The matching key ids records in deterministic order.
        """
        return tuple(self._private_keys)

    def matches(self, encryption_key: object) -> bool:
        """Confirm that the active public key has its private counterpart.

        Parameters
        ----------
        encryption_key : object
            The stable encryption key used to authenticate or deduplicate the
            operation.

        Returns
        -------
        bool
            `True` when Confirm that the active public key has its private
            counterpart; otherwise `False`.
        """
        if not isinstance(encryption_key, InvitationEncryptionKey):
            return False
        try:
            private_key = self._private_keys[encryption_key.encryption_key_id]
        except KeyError:
            return False
        return (
            private_key.public_key().public_numbers()
            == encryption_key.public_key.public_numbers()
        )

    def __repr__(self) -> str:
        """Return a diagnostic InvitationPrivateKeyring representation.

        Returns
        -------
        str
            A diagnostic representation of the value.
        """
        return f"InvitationPrivateKeyring(key_count={len(self._private_keys)})"


def load_invitation_public_key(public_key_pem: bytes) -> rsa.RSAPublicKey:
    """Load one bounded RSA public key without accepting private-key PEM.

    Parameters
    ----------
    public_key_pem : bytes
        The PEM-encoded public key key material to validate.

    Returns
    -------
    rsa.RSAPublicKey
        The resolved RSAPublicKey for the requested scope.

    Raises
    ------
    InvitationCryptoConfigurationError
        If the operation encounters a invitation crypto configuration condition.
    """
    pem = _validate_key_material(public_key_pem)
    try:
        public_key = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise InvitationCryptoConfigurationError from None
    return _validate_public_key(public_key)


def load_invitation_private_key(
    private_key_pem: bytes,
    *,
    password: bytes | None = None,
) -> rsa.RSAPrivateKey:
    """Explicitly load one worker-side RSA private key.

    Parameters
    ----------
    private_key_pem : bytes
        The PEM-encoded private key key material to validate.
    password : bytes | None, default=None
        The plaintext secret to verify without logging or retaining it.

    Returns
    -------
    rsa.RSAPrivateKey
        The resolved RSAPrivateKey for the requested scope.

    Raises
    ------
    InvitationCryptoConfigurationError
        If the operation encounters a invitation crypto configuration condition.
    """
    pem = _validate_key_material(private_key_pem)
    if password is not None and (
        not isinstance(password, bytes)
        or not 1 <= len(password) <= MAX_PRIVATE_KEY_PASSWORD_BYTES
    ):
        raise InvitationCryptoConfigurationError
    try:
        private_key = serialization.load_pem_private_key(pem, password=password)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise InvitationCryptoConfigurationError from None
    return _validate_private_key(private_key)


def _validate_key_material(key_material: object) -> bytes:
    if (
        not isinstance(key_material, bytes)
        or not 1 <= len(key_material) <= MAX_PEM_BYTES
    ):
        raise InvitationCryptoConfigurationError
    return key_material


def encrypt_invitation_payload(
    *,
    payload: bytes,
    aad: bytes,
    active_key: InvitationEncryptionKey,
) -> EncryptedInvitationPayload:
    """Encrypt a bounded payload using a public-key-only request adapter.

    Parameters
    ----------
    payload : bytes
        The untrusted payload to validate before domain use.
    aad : bytes
        The aad evaluated while encrypt invitation payload.
    active_key : InvitationEncryptionKey
        The stable active key used to authenticate or deduplicate the operation.

    Returns
    -------
    EncryptedInvitationPayload
        The resolved EncryptedInvitationPayload for encrypt invitation payload.

    Raises
    ------
    InvitationCryptoConfigurationError
        If the operation encounters a invitation crypto configuration condition.
    InvitationPayloadEncryptionError
        If the operation encounters a invitation payload encryption condition.
    """
    if not isinstance(active_key, InvitationEncryptionKey):
        raise InvitationCryptoConfigurationError
    plaintext = _validate_bounded_bytes(
        payload,
        minimum=1,
        maximum=MAX_INVITATION_PAYLOAD_BYTES,
    )
    caller_aad = _validate_bounded_bytes(
        aad,
        minimum=1,
        maximum=MAX_INVITATION_AAD_BYTES,
    )
    try:
        data_key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(_AES_GCM_NONCE_BYTES)
        encrypted_payload = AESGCM(data_key).encrypt(
            nonce,
            plaintext,
            _authenticated_aad(
                encryption_key_id=active_key.encryption_key_id,
                aad=caller_aad,
            ),
        )
        wrapped_data_key = active_key.public_key.encrypt(data_key, _oaep_padding())
    except (OSError, OverflowError, TypeError, ValueError, UnsupportedAlgorithm):
        raise InvitationPayloadEncryptionError from None
    return EncryptedInvitationPayload(
        encryption_algorithm=ENCRYPTION_ALGORITHM,
        encryption_key_id=active_key.encryption_key_id,
        encrypted_payload=_base64url_encode(encrypted_payload),
        wrapped_data_key=_base64url_encode(wrapped_data_key),
        payload_nonce=nonce,
        payload_aad_digest=_aad_digest(caller_aad),
    )


def decrypt_invitation_payload(
    *,
    envelope: EncryptedInvitationPayload,
    expected_aad: bytes,
    private_keyring: InvitationPrivateKeyring,
) -> bytes:
    """Decrypt in a worker after authenticating the caller-supplied AAD.

    Parameters
    ----------
    envelope : EncryptedInvitationPayload
        The envelope evaluated while decrypt invitation payload.
    expected_aad : bytes
        The expected aad evaluated while decrypt invitation payload.
    private_keyring : InvitationPrivateKeyring
        The configured private signing keys indexed by key identifier.

    Returns
    -------
    bytes
        The canonical byte representation for decrypt invitation payload.

    Raises
    ------
    InvitationPayloadDecryptionError
        If the operation encounters a invitation payload decryption condition.
    """
    if not isinstance(envelope, EncryptedInvitationPayload) or not isinstance(
        private_keyring, InvitationPrivateKeyring
    ):
        raise InvitationPayloadDecryptionError
    try:
        caller_aad = _validate_bounded_bytes(
            expected_aad,
            minimum=1,
            maximum=MAX_INVITATION_AAD_BYTES,
        )
        envelope.__post_init__()
    except (InvitationCryptoConfigurationError, InvitationCryptoPayloadError):
        raise InvitationPayloadDecryptionError from None
    if not hmac.compare_digest(
        envelope.payload_aad_digest,
        _aad_digest(caller_aad),
    ):
        raise InvitationPayloadDecryptionError

    private_key = private_keyring._resolve(envelope.encryption_key_id)
    try:
        wrapped_data_key = _base64url_decode(
            envelope.wrapped_data_key,
            minimum_decoded=_MIN_WRAPPED_KEY_BYTES,
            maximum_decoded=_MAX_WRAPPED_KEY_BYTES,
            maximum_encoded=_MAX_ENCODED_WRAPPED_KEY_BYTES,
        )
        encrypted_payload = _base64url_decode(
            envelope.encrypted_payload,
            minimum_decoded=_AES_GCM_TAG_BYTES + 1,
            maximum_decoded=_MAX_ENCRYPTED_PAYLOAD_BYTES,
            maximum_encoded=_MAX_ENCODED_PAYLOAD_BYTES,
        )
        _validate_bounded_bytes(
            wrapped_data_key,
            minimum=private_key.key_size // 8,
            maximum=private_key.key_size // 8,
        )
        data_key = _validate_bounded_bytes(
            private_key.decrypt(wrapped_data_key, _oaep_padding()),
            minimum=_AES_KEY_BYTES,
            maximum=_AES_KEY_BYTES,
        )
        plaintext = AESGCM(data_key).decrypt(
            envelope.payload_nonce,
            encrypted_payload,
            _authenticated_aad(
                encryption_key_id=envelope.encryption_key_id,
                aad=caller_aad,
            ),
        )
        return _validate_bounded_bytes(
            plaintext,
            minimum=1,
            maximum=MAX_INVITATION_PAYLOAD_BYTES,
        )
    except (
        InvalidTag,
        InvitationCryptoPayloadError,
        OverflowError,
        TypeError,
        ValueError,
        UnsupportedAlgorithm,
    ):
        raise InvitationPayloadDecryptionError from None


__all__ = [
    "ENCRYPTION_ALGORITHM",
    "MAX_ENCRYPTION_KEY_ID_LENGTH",
    "MAX_INVITATION_AAD_BYTES",
    "MAX_INVITATION_PAYLOAD_BYTES",
    "EncryptedInvitationPayload",
    "InvitationCryptoConfigurationError",
    "InvitationCryptoError",
    "InvitationCryptoPayloadError",
    "InvitationDecryptionKeyUnavailableError",
    "InvitationEncryptionKey",
    "InvitationPayloadDecryptionError",
    "InvitationPayloadEncryptionError",
    "InvitationPrivateKeyring",
    "decrypt_invitation_payload",
    "encrypt_invitation_payload",
    "load_invitation_private_key",
    "load_invitation_public_key",
]
