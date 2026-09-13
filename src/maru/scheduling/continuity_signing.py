"""Dedicated, tenant-bound continuity signing without Django's application secret."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .continuity_payload import encode_continuity_payload
from .continuity_protocol import (
    MAX_CONTINUITY_AGE,
    MAX_CONTINUITY_TRUST_KEYS,
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityTrustKey,
    _base64,
    _date,
    _json,
    _utc,
    _uuid,
    sign_continuity_package,
    verify_continuity_package,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from .continuity_payload import ContinuityProjection

SIGNING_POLICY_ENVIRONMENT = "MARU_PROGRAMME_CONTINUITY_SIGNING_KEYS_JSON"
SIGNING_POLICY_CONTRACT = "scheduling.programme-continuity-signing-policy@1"
MAX_SIGNING_POLICY_BYTES = 32768
DEFAULT_CONTINUITY_LIFETIME_SECONDS = 3600
_PRIVATE_KEY_BYTES = 32


class ContinuitySigningUnavailableError(ValueError):
    """Disable pack issuance without exposing configuration or disabling live reads."""

    def __init__(self) -> None:
        """Initialize a stable secret-free configuration failure."""
        super().__init__("Signed continuity export is not configured for this scope.")


@dataclass(frozen=True, slots=True)
class ContinuitySigningKey:
    """An independent dedicated key, deliberately omitted from object representations.

    Attributes
    ----------
    trust
        Tenant/edition, identifier, public key and approved key validity interval.
    private_key
        Dedicated Ed25519 private key; never serialize, log or return to the browser.
    """

    trust: ContinuityTrustKey
    private_key: Ed25519PrivateKey = field(repr=False)


@dataclass(frozen=True, slots=True)
class ContinuitySigningPolicy:
    """Bounded process configuration, not a request-supplied authorization policy.

    Attributes
    ----------
    keys
        Dedicated scoped keys; exactly one may be active for an issuance purpose.
    lifetime_seconds
        Lifetime measured from source observation, default one hour, maximum four.
    """

    keys: tuple[ContinuitySigningKey, ...] = field(repr=False)
    lifetime_seconds: int = DEFAULT_CONTINUITY_LIFETIME_SECONDS


def _policy_key(value: object) -> ContinuitySigningKey:
    if type(value) is not dict or value.keys() != {
        "organization_id",
        "edition_id",
        "key_id",
        "private_key_b64",
        "not_before",
        "not_after",
    }:
        raise ContinuityInvalidError
    organization_id = _uuid(value["organization_id"])
    edition_id = _uuid(value["edition_id"])
    if (
        organization_id is None
        or edition_id is None
        or type(value["key_id"]) is not str
    ):
        raise ContinuityInvalidError
    key = Ed25519PrivateKey.from_private_bytes(
        _base64(value["private_key_b64"], maximum=_PRIVATE_KEY_BYTES)
    )
    return ContinuitySigningKey(
        ContinuityTrustKey(
            organization_id,
            edition_id,
            value["key_id"],
            key.public_key().public_bytes_raw(),
            _date(value["not_before"]),
            _date(value["not_after"]),
        ),
        key,
    )


def load_continuity_signing_policy(
    environment: Mapping[str, str] | None = None,
) -> ContinuitySigningPolicy:
    """Load bounded dedicated signing keys without copying secrets into Django settings.

    Parameters
    ----------
    environment : Mapping[str, str] | None, default=None
        Isolated configuration for tests, or the managed request-process environment.

    Returns
    -------
    ContinuitySigningPolicy
        Scoped dedicated keys from closed canonical JSON; no implicit default key.

    Raises
    ------
    ContinuitySigningUnavailableError
        If configuration is missing, malformed, over-bound or unsupported.

    Notes
    -----
    Never log the raw environment or exception locals. Issuance additionally checks
    exact scope, key uniqueness, key validity and lifetime before signing anything.
    """
    source = os.environ if environment is None else environment
    try:
        raw = source.get(SIGNING_POLICY_ENVIRONMENT, "")
        if type(raw) is not str or len(raw) > MAX_SIGNING_POLICY_BYTES:
            raise ContinuitySigningUnavailableError
        data = _json(
            raw.encode("utf-8"),
            frozenset({"contract", "keys", "lifetime_seconds"}),
            maximum=MAX_SIGNING_POLICY_BYTES,
        )
        keys, lifetime = data["keys"], data["lifetime_seconds"]
        if (
            data["contract"] != SIGNING_POLICY_CONTRACT
            or type(keys) is not list
            or not 1 <= len(keys) <= MAX_CONTINUITY_TRUST_KEYS
            or not isinstance(lifetime, int)
            or isinstance(lifetime, bool)
            or not 1 <= lifetime <= MAX_CONTINUITY_AGE.total_seconds()
        ):
            raise ContinuitySigningUnavailableError
        return ContinuitySigningPolicy(
            tuple(_policy_key(value) for value in keys), lifetime
        )
    except (ValueError, TypeError, OverflowError, UnsupportedAlgorithm):
        raise ContinuitySigningUnavailableError from None


def sign_continuity_projection(
    projection: ContinuityProjection,
    *,
    policy: ContinuitySigningPolicy,
    issued_at: datetime,
) -> bytes:
    """Sign a freshly authorized projection at its exact dedicated key/expiry ceiling.

    Parameters
    ----------
    projection : ContinuityProjection
        Fresh result of load_continuity_projection, never request-supplied source data.
    policy : ContinuitySigningPolicy
        Independently provisioned server policy, never a key supplied in the request.
    issued_at : datetime
        Aware current server instant, within five minutes of the source observation.

    Returns
    -------
    bytes
        Deterministic signed pack with no keys or bearer grant embedded.

    Raises
    ------
    ContinuitySigningUnavailableError
        If configuration, source age, scope, active key or validity fails closed.

    Notes
    -----
    This low-level signer grants no access. HTTP callers must obtain the projection
    through the admitted owner query and must not deserialize a client projection.
    """
    try:
        payload = encode_continuity_payload(projection)
        now = _utc(issued_at)
        if (
            type(policy) is not ContinuitySigningPolicy
            or type(policy.keys) is not tuple
            or not 1 <= len(policy.keys) <= MAX_CONTINUITY_TRUST_KEYS
            or type(policy.lifetime_seconds) is not int
            or not 1 <= policy.lifetime_seconds <= MAX_CONTINUITY_AGE.total_seconds()
            or any(
                type(key) is not ContinuitySigningKey
                or type(key.trust) is not ContinuityTrustKey
                or not isinstance(key.private_key, Ed25519PrivateKey)
                for key in policy.keys
            )
        ):
            raise ContinuitySigningUnavailableError
        selected = tuple(
            key
            for key in policy.keys
            if key.trust.organization_id == projection.scope.organization_id
            and key.trust.edition_id == projection.scope.edition_id
            and _utc(key.trust.not_before) <= now < _utc(key.trust.not_after)
        )
        if len(selected) != 1:
            raise ContinuitySigningUnavailableError
        key = selected[0]
        manifest = ContinuityManifest(
            projection.scope,
            key.trust.key_id,
            projection.observed_at,
            now,
            _utc(projection.observed_at) + timedelta(seconds=policy.lifetime_seconds),
            projection.zone_name,
            projection.release_state,
            projection.pointer_version,
            projection.release_id,
            hashlib.sha256(payload).hexdigest(),
        )
        package = sign_continuity_package(payload, manifest, key=key.private_key)
        verify_continuity_package(
            package,
            expected_scope=projection.scope,
            trust=tuple(key.trust for key in policy.keys),
            now=now,
        )
    except (ValueError, TypeError, OverflowError, UnsupportedAlgorithm):
        raise ContinuitySigningUnavailableError from None
    else:
        return package
