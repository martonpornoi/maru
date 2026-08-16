import base64
import hashlib
import re
from dataclasses import FrozenInstanceError, replace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from maru.identity.invitation_crypto import (
    ENCRYPTION_ALGORITHM,
    MAX_ENCRYPTION_KEY_ID_LENGTH,
    MAX_INVITATION_AAD_BYTES,
    MAX_INVITATION_PAYLOAD_BYTES,
    EncryptedInvitationPayload,
    InvitationCryptoConfigurationError,
    InvitationCryptoPayloadError,
    InvitationDecryptionKeyUnavailableError,
    InvitationEncryptionKey,
    InvitationPayloadDecryptionError,
    InvitationPrivateKeyring,
    decrypt_invitation_payload,
    encrypt_invitation_payload,
    load_invitation_private_key,
    load_invitation_public_key,
)

_PAYLOAD = b"synthetic-raw-invitation-token"
_AAD = b"invitation:00000000-0000-4000-8000-000000000001:version:1"
_BASE64URL = re.compile(rb"[A-Za-z0-9_-]+", flags=re.ASCII)


@pytest.fixture(scope="module")
def rsa_private_keys() -> tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]:
    return (
        rsa.generate_private_key(public_exponent=65_537, key_size=2_048),
        rsa.generate_private_key(public_exponent=65_537, key_size=2_048),
    )


def _active_key(
    encryption_key_id: str,
    private_key: rsa.RSAPrivateKey,
) -> InvitationEncryptionKey:
    return InvitationEncryptionKey(
        encryption_key_id=encryption_key_id,
        public_key=private_key.public_key(),
    )


def _envelope(
    private_key: rsa.RSAPrivateKey,
    *,
    encryption_key_id: str = "invitation-key-2026-08",
    payload: bytes = _PAYLOAD,
    aad: bytes = _AAD,
) -> EncryptedInvitationPayload:
    return encrypt_invitation_payload(
        payload=payload,
        aad=aad,
        active_key=_active_key(encryption_key_id, private_key),
    )


def _decode_base64url(value: bytes) -> bytes:
    return base64.urlsafe_b64decode(value + b"=" * (-len(value) % 4))


def _tamper_base64url(value: bytes) -> bytes:
    decoded = bytearray(_decode_base64url(value))
    decoded[-1] ^= 1
    return base64.urlsafe_b64encode(bytes(decoded)).rstrip(b"=")


def test_envelope_round_trip_is_randomized_bounded_and_redacted(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    active_key = _active_key("invitation-key-2026-08", private_key)
    first = encrypt_invitation_payload(
        payload=_PAYLOAD,
        aad=_AAD,
        active_key=active_key,
    )
    second = encrypt_invitation_payload(
        payload=_PAYLOAD,
        aad=_AAD,
        active_key=active_key,
    )

    assert first.encryption_algorithm == ENCRYPTION_ALGORITHM
    assert first.encryption_key_id == "invitation-key-2026-08"
    assert first.encrypted_payload != second.encrypted_payload
    assert first.wrapped_data_key != second.wrapped_data_key
    assert first.payload_nonce != second.payload_nonce
    assert len(first.payload_nonce) == 12
    assert first.payload_aad_digest == hashlib.sha256(_AAD).hexdigest()
    assert _BASE64URL.fullmatch(first.encrypted_payload)
    assert _BASE64URL.fullmatch(first.wrapped_data_key)
    assert b"=" not in first.encrypted_payload
    assert b"=" not in first.wrapped_data_key
    assert _PAYLOAD not in first.encrypted_payload
    assert _PAYLOAD.decode() not in repr(first)
    assert first.encrypted_payload.decode() not in repr(first)
    assert first.encryption_key_id not in repr(active_key)

    keyring = InvitationPrivateKeyring({first.encryption_key_id: private_key})
    assert (
        decrypt_invitation_payload(
            envelope=first,
            expected_aad=_AAD,
            private_keyring=keyring,
        )
        == _PAYLOAD
    )
    with pytest.raises(FrozenInstanceError):
        first.payload_nonce = b"changed"  # type: ignore[misc]


def test_data_key_is_wrapped_with_rsa_oaep_sha256(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    envelope = _envelope(private_key)

    data_key = private_key.decrypt(
        _decode_base64url(envelope.wrapped_data_key),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=ENCRYPTION_ALGORITHM.encode("ascii"),
        ),
    )

    assert len(data_key) == 32


def test_private_keyring_resolves_rotated_key_without_exposing_key_ids(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    old_private_key, new_private_key = rsa_private_keys
    old_envelope = _envelope(old_private_key, encryption_key_id="old-key")
    new_envelope = _envelope(new_private_key, encryption_key_id="new-key")
    source = {"old-key": old_private_key, "new-key": new_private_key}
    keyring = InvitationPrivateKeyring(source)
    source.clear()

    assert (
        decrypt_invitation_payload(
            envelope=old_envelope,
            expected_aad=_AAD,
            private_keyring=keyring,
        )
        == _PAYLOAD
    )
    assert (
        decrypt_invitation_payload(
            envelope=new_envelope,
            expected_aad=_AAD,
            private_keyring=keyring,
        )
        == _PAYLOAD
    )
    assert "old-key" not in repr(keyring)
    assert "new-key" not in repr(keyring)

    with pytest.raises(InvitationDecryptionKeyUnavailableError) as captured:
        decrypt_invitation_payload(
            envelope=old_envelope,
            expected_aad=_AAD,
            private_keyring=InvitationPrivateKeyring({"new-key": new_private_key}),
        )
    assert str(captured.value) == "Invitation payload decryption failed."
    assert "old-key" not in repr(captured.value)


@pytest.mark.parametrize(
    "changed_envelope",
    [
        lambda value: replace(
            value,
            encrypted_payload=_tamper_base64url(value.encrypted_payload),
        ),
        lambda value: replace(
            value,
            wrapped_data_key=_tamper_base64url(value.wrapped_data_key),
        ),
        lambda value: replace(
            value,
            payload_nonce=bytes([value.payload_nonce[0] ^ 1]) + value.payload_nonce[1:],
        ),
        lambda value: replace(value, payload_aad_digest="0" * 64),
        lambda value: replace(value, encryption_key_id="valid-key-alias"),
    ],
)
def test_tampering_fails_with_one_generic_typed_error(
    changed_envelope,
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    envelope = changed_envelope(_envelope(private_key))

    with pytest.raises(InvitationPayloadDecryptionError) as captured:
        decrypt_invitation_payload(
            envelope=envelope,
            expected_aad=_AAD,
            private_keyring=InvitationPrivateKeyring(
                {envelope.encryption_key_id: private_key}
            ),
        )
    assert str(captured.value) == "Invitation payload decryption failed."
    assert _PAYLOAD.decode() not in repr(captured.value)
    assert _AAD.decode() not in repr(captured.value)


def test_expected_aad_is_required_bounded_and_authenticated(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    envelope = _envelope(private_key)
    keyring = InvitationPrivateKeyring({envelope.encryption_key_id: private_key})

    for wrong_aad in (b"", b"different-aad", b"x" * (MAX_INVITATION_AAD_BYTES + 1)):
        with pytest.raises(InvitationPayloadDecryptionError) as captured:
            decrypt_invitation_payload(
                envelope=envelope,
                expected_aad=wrong_aad,
                private_keyring=keyring,
            )
        assert str(captured.value) == "Invitation payload decryption failed."
        if wrong_aad:
            assert wrong_aad.decode() not in repr(captured.value)


def test_payload_and_aad_encryption_bounds_are_strict(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    active_key = _active_key("bounded-key", private_key)

    for payload in (b"", b"x" * (MAX_INVITATION_PAYLOAD_BYTES + 1)):
        with pytest.raises(InvitationCryptoPayloadError):
            encrypt_invitation_payload(payload=payload, aad=_AAD, active_key=active_key)
    for aad in (b"", b"x" * (MAX_INVITATION_AAD_BYTES + 1)):
        with pytest.raises(InvitationCryptoPayloadError):
            encrypt_invitation_payload(
                payload=_PAYLOAD,
                aad=aad,
                active_key=active_key,
            )

    maximum_payload = b"x" * MAX_INVITATION_PAYLOAD_BYTES
    maximum_aad = b"a" * MAX_INVITATION_AAD_BYTES
    envelope = encrypt_invitation_payload(
        payload=maximum_payload,
        aad=maximum_aad,
        active_key=active_key,
    )
    assert (
        decrypt_invitation_payload(
            envelope=envelope,
            expected_aad=maximum_aad,
            private_keyring=InvitationPrivateKeyring({"bounded-key": private_key}),
        )
        == maximum_payload
    )


@pytest.mark.parametrize(
    "encryption_key_id",
    [
        "",
        " leading-space",
        "contains/slash",
        "non-ascii-é",
        "x" * (MAX_ENCRYPTION_KEY_ID_LENGTH + 1),
    ],
)
def test_encryption_key_id_is_strict_and_errors_are_value_free(
    encryption_key_id: str,
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys

    with pytest.raises(InvitationCryptoConfigurationError) as captured:
        _active_key(encryption_key_id, private_key)
    if encryption_key_id:
        assert encryption_key_id not in repr(captured.value)


def test_unsupported_key_size_and_unbounded_keyrings_fail_closed() -> None:
    undersized_key = rsa.generate_private_key(
        public_exponent=65_537,
        key_size=1_024,  # noqa: S505 - deliberately rejected boundary fixture.
    )

    with pytest.raises(InvitationCryptoConfigurationError):
        _active_key("undersized-key", undersized_key)
    with pytest.raises(InvitationCryptoConfigurationError):
        InvitationPrivateKeyring({})
    with pytest.raises(InvitationCryptoConfigurationError):
        InvitationPrivateKeyring(
            {f"key-{index}": undersized_key for index in range(33)}
        )


def test_pem_loaders_keep_private_loading_worker_explicit(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    password = b"synthetic-private-key-password"
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )

    active_key = InvitationEncryptionKey.from_pem(
        encryption_key_id="pem-key",
        public_key_pem=public_pem,
    )
    worker_keyring = InvitationPrivateKeyring.from_pem(
        {"pem-key": private_pem},
        passwords={"pem-key": password},
    )
    envelope = encrypt_invitation_payload(
        payload=_PAYLOAD,
        aad=_AAD,
        active_key=active_key,
    )
    assert (
        decrypt_invitation_payload(
            envelope=envelope,
            expected_aad=_AAD,
            private_keyring=worker_keyring,
        )
        == _PAYLOAD
    )

    assert isinstance(load_invitation_public_key(public_pem), rsa.RSAPublicKey)
    assert isinstance(
        load_invitation_private_key(private_pem, password=password),
        rsa.RSAPrivateKey,
    )
    with pytest.raises(InvitationCryptoConfigurationError):
        load_invitation_public_key(private_pem)
    with pytest.raises(InvitationCryptoConfigurationError):
        load_invitation_private_key(public_pem)
    with pytest.raises(InvitationCryptoConfigurationError) as captured:
        load_invitation_private_key(private_pem, password=b"wrong-password")
    assert password.decode() not in repr(captured.value)


def test_persisted_envelope_fields_reject_noncanonical_values(
    rsa_private_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_private_keys
    envelope = _envelope(private_key)

    invalid_updates = (
        {"encryption_algorithm": "rsa-v0"},
        {"encrypted_payload": envelope.encrypted_payload + b"="},
        {"wrapped_data_key": b"not-a-wrapped-key"},
        {"payload_nonce": b"too-short"},
        {"payload_aad_digest": envelope.payload_aad_digest.upper()},
    )
    for update in invalid_updates:
        with pytest.raises(InvitationCryptoPayloadError):
            replace(envelope, **update)
