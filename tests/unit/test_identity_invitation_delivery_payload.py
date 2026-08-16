from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from maru.identity.invitation_delivery_payload import (
    InvitationDeliveryPayloadError,
    decode_invitation_delivery_payload,
    encode_invitation_delivery_payload,
    invitation_delivery_aad,
)

TOKEN = "A" * 43
INVITATION_ID = UUID("10000000-0000-4000-8000-000000000001")
CHALLENGE_ID = UUID("20000000-0000-4000-8000-000000000002")


def test_payload_round_trip_is_canonical_and_repr_is_redacted() -> None:
    encoded = encode_invitation_delivery_payload(raw_token=TOKEN)
    assert encoded == b'{"token":"' + TOKEN.encode() + b'","version":1}'
    decoded = decode_invitation_delivery_payload(encoded)
    assert decoded.raw_token == TOKEN
    assert TOKEN not in repr(decoded)


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"not-json",
        b"[]",
        b'{"token":"short","version":1}',
        b'{"extra":1,"token":"' + TOKEN.encode() + b'","version":1}',
        b'{"token":"' + TOKEN.encode() + b'","version":true}',
        b'{"token":"' + TOKEN.encode() + b'","version":2}',
    ],
)
def test_payload_decode_rejects_noncanonical_shape_without_echo(value: bytes) -> None:
    with pytest.raises(InvitationDeliveryPayloadError) as captured:
        decode_invitation_delivery_payload(value)
    assert TOKEN not in str(captured.value)


def test_aad_is_deterministic_casefolded_and_contains_no_contact() -> None:
    first = invitation_delivery_aad(
        invitation_id=INVITATION_ID,
        challenge_id=CHALLENGE_ID,
        invitation_version=1,
        email="Person@Example.Invalid",
    )
    second = invitation_delivery_aad(
        invitation_id=INVITATION_ID,
        challenge_id=CHALLENGE_ID,
        invitation_version=1,
        email="person@example.invalid",
    )
    assert first == second
    assert b"person@example.invalid" not in first
    assert hashlib.sha256(b"person@example.invalid").hexdigest().encode() in first


@pytest.mark.parametrize(
    ("version", "email"),
    [(0, "person@example.invalid"), (True, "person@example.invalid"), (1, "")],
)
def test_aad_rejects_invalid_control_values(version: object, email: str) -> None:
    with pytest.raises(InvitationDeliveryPayloadError):
        invitation_delivery_aad(
            invitation_id=INVITATION_ID,
            challenge_id=CHALLENGE_ID,
            invitation_version=version,  # type: ignore[arg-type]
            email=email,
        )
