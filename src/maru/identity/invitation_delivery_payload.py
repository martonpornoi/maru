"""Strict plaintext contract used only inside invitation delivery envelopes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from maru.identity.managers import AccountManager

INVITATION_DELIVERY_PAYLOAD_VERSION: Final = 1
INVITATION_TOKEN_LENGTH: Final = 43
MAX_ENCODED_INVITATION_DELIVERY_PAYLOAD_BYTES: Final = 512
_TOKEN_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{43}", flags=re.ASCII)
_AAD_DOMAIN: Final = "maru.identity.account-invitation-delivery.v1"


class InvitationDeliveryPayloadError(ValueError):
    """Generic error that never includes token, email, or decoded payload."""

    def __init__(self) -> None:
        """Initialize the InvitationDeliveryPayloadError instance."""
        super().__init__("The invitation delivery payload is invalid.")


@dataclass(frozen=True, slots=True, repr=False)
class InvitationDeliveryPayload:
    """Describe invitation delivery payload.

    Attributes
    ----------
    raw_token
        The opaque raw token supplied by the caller.
    """

    raw_token: str

    def __post_init__(self) -> None:
        """Implement `__post_init__` for InvitationDeliveryPayload.

        Raises
        ------
        InvitationDeliveryPayloadError
            If the requested operation violates this domain contract.
        """
        if (
            not isinstance(self.raw_token, str)
            or _TOKEN_PATTERN.fullmatch(self.raw_token) is None
        ):
            raise InvitationDeliveryPayloadError

    def __repr__(self) -> str:
        """Return a diagnostic InvitationDeliveryPayload representation.

        Returns
        -------
        str
            A diagnostic representation of the value.
        """
        return "InvitationDeliveryPayload([redacted])"


def _canonical_uuid(value: UUID) -> str:
    if not isinstance(value, UUID):
        raise InvitationDeliveryPayloadError
    return str(value)


def invitation_delivery_aad(
    *,
    invitation_id: UUID,
    challenge_id: UUID,
    invitation_version: int,
    email: str,
) -> bytes:
    """Bind ciphertext to exact lineage and the normalized delivery contact.

    Parameters
    ----------
    invitation_id : UUID
        The invitation identifier within the requested scope.
    challenge_id : UUID
        The challenge identifier within the requested scope.
    invitation_version : int
        The expected invitation version used to reject stale updates.
    email : str
        The normalized email address used for delivery or identity matching.

    Returns
    -------
    bytes
        The canonical byte representation for invitation delivery aad.

    Raises
    ------
    InvitationDeliveryPayloadError
        If the operation encounters a invitation delivery payload condition.
    """
    if type(invitation_version) is not int or invitation_version < 1:
        raise InvitationDeliveryPayloadError
    if not isinstance(email, str) or not email:
        raise InvitationDeliveryPayloadError
    normalized_email = AccountManager.normalize_login_email(email)
    if not normalized_email:
        raise InvitationDeliveryPayloadError
    email_digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    return "\n".join(
        (
            _AAD_DOMAIN,
            _canonical_uuid(invitation_id),
            _canonical_uuid(challenge_id),
            str(invitation_version),
            email_digest,
        )
    ).encode("ascii")


def encode_invitation_delivery_payload(*, raw_token: str) -> bytes:
    """Encode invitation delivery payload.

    Parameters
    ----------
    raw_token : str
        The untrusted token supplied by the caller.

    Returns
    -------
    bytes
        The encoded invitation delivery payload.
    """
    payload = InvitationDeliveryPayload(raw_token=raw_token)
    return json.dumps(
        {
            "token": payload.raw_token,
            "version": INVITATION_DELIVERY_PAYLOAD_VERSION,
        },
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def decode_invitation_delivery_payload(value: bytes) -> InvitationDeliveryPayload:
    """Decode invitation delivery payload.

    Parameters
    ----------
    value : bytes
        The untrusted value to normalize against the documented contract.

    Returns
    -------
    InvitationDeliveryPayload
        The invitation delivery payload.

    Raises
    ------
    InvitationDeliveryPayloadError
        If the operation encounters a invitation delivery payload condition.
    """
    if not isinstance(value, bytes) or not (
        1 <= len(value) <= MAX_ENCODED_INVITATION_DELIVERY_PAYLOAD_BYTES
    ):
        raise InvitationDeliveryPayloadError
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, TypeError, ValueError):
        raise InvitationDeliveryPayloadError from None
    if (
        not isinstance(decoded, dict)
        or set(decoded) != {"token", "version"}
        or type(decoded.get("version")) is not int
        or decoded.get("version") != INVITATION_DELIVERY_PAYLOAD_VERSION
    ):
        raise InvitationDeliveryPayloadError
    try:
        return InvitationDeliveryPayload(raw_token=decoded["token"])
    except (KeyError, TypeError, InvitationDeliveryPayloadError):
        raise InvitationDeliveryPayloadError from None


__all__ = [
    "INVITATION_DELIVERY_PAYLOAD_VERSION",
    "INVITATION_TOKEN_LENGTH",
    "MAX_ENCODED_INVITATION_DELIVERY_PAYLOAD_BYTES",
    "InvitationDeliveryPayload",
    "InvitationDeliveryPayloadError",
    "decode_invitation_delivery_payload",
    "encode_invitation_delivery_payload",
    "invitation_delivery_aad",
]
