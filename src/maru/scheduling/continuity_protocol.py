"""Read-only Programme signatures, never authorization or freshness grants."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

CONTINUITY_CONTRACT = "scheduling.programme-continuity@1"
MAX_CONTINUITY_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_CONTINUITY_PACKAGE_BYTES = 12 * 1024 * 1024
MAX_CONTINUITY_AGE = timedelta(hours=4)
MAX_CONTINUITY_TRUST_KEYS = 8
MAX_CONTINUITY_CHECKPOINT_BYTES = 4096
_MAX_DATE_TEXT = 40
_MAX_ZONE_TEXT = 100
_ED25519_PUBLIC_BYTES = 32
_ED25519_SIGNATURE_BYTES = 64
_SIGNATURE_DOMAIN = b"Maru Programme read-only continuity v1\x00"
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LAYERS = frozenset({"technical", "accessibility", "media", "staffing"})
_STATES = frozenset(
    {"available", "absent", "withdrawn", "invalidated", "unobserved", "unadopted"}
)


class ContinuityInvalidError(ValueError):
    """Reject an unverifiable, malformed, expired or foreign continuity package."""


class ContinuitySupersededError(ContinuityInvalidError):
    """Refuse ordinary content older than independently verified known evidence."""


@dataclass(frozen=True, slots=True)
class ContinuityScope:
    """Expected disclosure context provisioned independently from an offline file.

    Attributes
    ----------
    organization_id, edition_id
        Exact tenant and edition; neither is discovered from a trusted-looking file.
    audience
        Public, exact_person or private_operator, matching its owning projection.
    actor_id
        Actual person for private packs; never a public visitor or a substituted user.
    kind, target_id
        Public/personal or exact room/department/edition operator purpose.
    layers
        Canonically sorted requested operator fields; not permission to read them.
    """

    organization_id: UUID
    edition_id: UUID
    audience: str
    actor_id: UUID | None = None
    kind: str = "public"
    target_id: UUID | None = None
    layers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContinuityManifest:
    """Signed source observation and payload binding, not a current capability lease.

    Attributes
    ----------
    scope
        Exact independently authorized source audience and field ceiling.
    key_id
        Dedicated issuing key identifier, resolved only in separately trusted policy.
    observed_at, issued_at, expires_at
        UTC source observation, issuance and hard end of permitted snapshot display.
    zone_name
        Events-owned IANA zone for unambiguous local presentation.
    release_state, pointer_version, release_id
        Observed release state; unobserved/unadopted never claims release absence.
    payload_sha256
        Digest of the exact bounded owner-validated payload bytes.
    """

    scope: ContinuityScope
    key_id: str
    observed_at: datetime
    issued_at: datetime
    expires_at: datetime
    zone_name: str
    release_state: str
    pointer_version: int | None
    release_id: UUID | None
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class ContinuityTrustKey:
    """Offline trust input obtained independently from the snapshot and its issuer ID.

    Attributes
    ----------
    organization_id, edition_id
        Expected scope for which an operator deliberately trusts this public key.
    key_id, public_key
        Immutable local identifier and raw 32-byte Ed25519 verification key.
    not_before, not_after
        Key policy interval. Retained historical signatures can outlive issuance use.
    """

    organization_id: UUID
    edition_id: UUID
    key_id: str
    public_key: bytes
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True, slots=True)
class VerifiedContinuityPackage:
    """Verified byte integrity and scope; the payload still needs its domain decoder.

    Attributes
    ----------
    manifest
        Validated signed observation, never proof of current live authority.
    payload
        Exact authenticated bytes; not executable HTML or an arbitrary object graph.
    checkpoint
        Signed manifest and signature only, suitable for protected known-state storage.
    """

    manifest: ContinuityManifest
    payload: bytes
    checkpoint: bytes


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ContinuityInvalidError
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as error:
        raise ContinuityInvalidError from error


def _uuid(value: object, *, optional: bool = False) -> UUID | None:
    if optional and value is None:
        return None
    if type(value) is not str:
        raise ContinuityInvalidError
    try:
        result = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ContinuityInvalidError from error
    if str(result) != value or result.int == 0:
        raise ContinuityInvalidError
    return result


def _date(value: object) -> datetime:
    if type(value) is not str or len(value) > _MAX_DATE_TEXT:
        raise ContinuityInvalidError
    try:
        result = _utc(datetime.fromisoformat(value))
    except ValueError as error:
        raise ContinuityInvalidError from error
    if result.isoformat() != value:
        raise ContinuityInvalidError
    return result


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ContinuityInvalidError from error


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContinuityInvalidError
        result[key] = value
    return result


def _json(data: bytes, fields: frozenset[str], *, maximum: int) -> dict[str, object]:
    if type(data) is not bytes or not 0 < len(data) <= maximum:
        raise ContinuityInvalidError
    try:
        result = json.loads(data, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ContinuityInvalidError from error
    if type(result) is not dict or result.keys() != fields:
        raise ContinuityInvalidError
    # Only the closed canonical wire encoding is accepted, including finite numbers.
    if _canonical(result) != data:
        raise ContinuityInvalidError
    return result


def _scope_document(scope: ContinuityScope) -> dict[str, object]:
    if type(scope) is not ContinuityScope:
        raise ContinuityInvalidError
    if type(scope.audience) is not str or type(scope.kind) is not str:
        raise ContinuityInvalidError
    for value in (scope.organization_id, scope.edition_id):
        if type(value) is not UUID or value.int == 0:
            raise ContinuityInvalidError
    if (
        type(scope.layers) is not tuple
        or len(scope.layers) > len(_LAYERS)
        or any(type(value) is not str for value in scope.layers)
        or tuple(sorted(set(scope.layers))) != scope.layers
        or not set(scope.layers) <= _LAYERS
    ):
        raise ContinuityInvalidError
    if scope.audience == "public":
        valid = (
            scope.kind == "public"
            and scope.actor_id is None
            and scope.target_id is None
        )
    elif scope.audience == "exact_person":
        valid = (
            scope.kind == "personal"
            and type(scope.actor_id) is UUID
            and scope.target_id is None
        )
    elif scope.audience == "private_operator":
        valid = (
            scope.kind in {"room", "department", "edition"}
            and type(scope.actor_id) is UUID
            and type(scope.target_id) is UUID
            and (scope.kind != "edition" or scope.target_id == scope.edition_id)
        )
    else:
        valid = False
    if (
        not valid
        or (scope.audience != "private_operator" and scope.layers)
        or any(
            value is not None and value.int == 0
            for value in (scope.actor_id, scope.target_id)
        )
    ):
        raise ContinuityInvalidError
    return {
        "organization_id": str(scope.organization_id),
        "edition_id": str(scope.edition_id),
        "audience": scope.audience,
        "actor_id": str(scope.actor_id) if scope.actor_id else None,
        "kind": scope.kind,
        "target_id": str(scope.target_id) if scope.target_id else None,
        "layers": list(scope.layers),
    }


def _validate_release_state(
    *, audience: str, state: str, pointer: int | None, release: UUID | None
) -> None:
    if type(state) is not str or state not in _STATES:
        raise ContinuityInvalidError
    if state in {"unobserved", "unadopted"}:
        valid = audience == "exact_person" and pointer is None and release is None
    else:
        valid = type(pointer) is int and 0 <= pointer <= 2**63 - 1
        if state == "absent":
            valid = valid and pointer == 0 and release is None
        elif state == "withdrawn":
            valid = valid and pointer is not None and pointer > 0 and release is None
        else:
            valid = (
                valid
                and pointer is not None
                and pointer > 0
                and type(release) is UUID
                and release.int != 0
            )
    if not valid:
        raise ContinuityInvalidError


def _manifest_document(manifest: ContinuityManifest) -> dict[str, object]:
    if type(manifest) is not ContinuityManifest:
        raise ContinuityInvalidError
    scope = _scope_document(manifest.scope)
    observed, issued, expires = (
        _utc(value)
        for value in (manifest.observed_at, manifest.issued_at, manifest.expires_at)
    )
    try:
        if not observed <= issued < expires <= observed + MAX_CONTINUITY_AGE:
            raise ContinuityInvalidError
    except OverflowError as error:
        raise ContinuityInvalidError from error
    if issued - observed > timedelta(minutes=5):
        raise ContinuityInvalidError
    if type(manifest.key_id) is not str or _KEY_ID.fullmatch(manifest.key_id) is None:
        raise ContinuityInvalidError
    if (
        type(manifest.payload_sha256) is not str
        or _DIGEST.fullmatch(manifest.payload_sha256) is None
    ):
        raise ContinuityInvalidError
    if (
        type(manifest.zone_name) is not str
        or not 1 <= len(manifest.zone_name) <= _MAX_ZONE_TEXT
    ):
        raise ContinuityInvalidError
    try:
        ZoneInfo(manifest.zone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ContinuityInvalidError from error
    _validate_release_state(
        audience=manifest.scope.audience,
        state=manifest.release_state,
        pointer=manifest.pointer_version,
        release=manifest.release_id,
    )
    return {
        "contract": CONTINUITY_CONTRACT,
        "scope": scope,
        "key_id": manifest.key_id,
        "observed_at": observed.isoformat(),
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
        "zone_name": manifest.zone_name,
        "release_state": manifest.release_state,
        "pointer_version": manifest.pointer_version,
        "release_id": str(manifest.release_id) if manifest.release_id else None,
        "payload_sha256": manifest.payload_sha256,
    }


def _decode_manifest(value: object) -> ContinuityManifest:
    if (
        type(value) is not dict
        or value.keys()
        != {
            "contract",
            "scope",
            "key_id",
            "observed_at",
            "issued_at",
            "expires_at",
            "zone_name",
            "release_state",
            "pointer_version",
            "release_id",
            "payload_sha256",
        }
        or value["contract"] != CONTINUITY_CONTRACT
    ):
        raise ContinuityInvalidError
    scope = value["scope"]
    if (
        type(scope) is not dict
        or scope.keys()
        != {
            "organization_id",
            "edition_id",
            "audience",
            "actor_id",
            "kind",
            "target_id",
            "layers",
        }
        or type(scope["layers"]) is not list
    ):
        raise ContinuityInvalidError
    organization_id = _uuid(scope["organization_id"])
    edition_id = _uuid(scope["edition_id"])
    if organization_id is None or edition_id is None:
        raise ContinuityInvalidError
    result = ContinuityManifest(
        ContinuityScope(
            organization_id,
            edition_id,
            scope["audience"],
            _uuid(scope["actor_id"], optional=True),
            scope["kind"],
            _uuid(scope["target_id"], optional=True),
            tuple(scope["layers"]),
        ),
        value["key_id"],
        _date(value["observed_at"]),
        _date(value["issued_at"]),
        _date(value["expires_at"]),
        value["zone_name"],
        value["release_state"],
        value["pointer_version"],
        _uuid(value["release_id"], optional=True),
        value["payload_sha256"],
    )
    if _manifest_document(result) != value:
        raise ContinuityInvalidError
    return result


def _base64(value: object, *, maximum: int) -> bytes:
    if type(value) is not str or len(value) > 4 * ((maximum + 2) // 3):
        raise ContinuityInvalidError
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ContinuityInvalidError from error
    if len(decoded) > maximum or base64.b64encode(decoded).decode("ascii") != value:
        raise ContinuityInvalidError
    return decoded


def _trusted_signature(
    manifest: ContinuityManifest,
    signature: bytes,
    trust: tuple[ContinuityTrustKey, ...],
) -> None:
    if type(trust) is not tuple or not 1 <= len(trust) <= MAX_CONTINUITY_TRUST_KEYS:
        raise ContinuityInvalidError
    matches = []
    seen = set()
    for key in trust:
        if type(key) is not ContinuityTrustKey:
            raise ContinuityInvalidError
        if (
            type(key.organization_id) is not UUID
            or key.organization_id.int == 0
            or type(key.edition_id) is not UUID
            or key.edition_id.int == 0
            or type(key.key_id) is not str
            or _KEY_ID.fullmatch(key.key_id) is None
            or type(key.public_key) is not bytes
            or len(key.public_key) != _ED25519_PUBLIC_BYTES
            or not _utc(key.not_before) < _utc(key.not_after)
        ):
            raise ContinuityInvalidError
        identity = (key.organization_id, key.edition_id, key.key_id)
        if identity in seen:
            raise ContinuityInvalidError
        seen.add(identity)
        if identity == (
            manifest.scope.organization_id,
            manifest.scope.edition_id,
            manifest.key_id,
        ):
            matches.append(key)
    if len(matches) != 1 or len(signature) != _ED25519_SIGNATURE_BYTES:
        raise ContinuityInvalidError
    key = matches[0]
    if (
        type(key.public_key) is not bytes
        or len(key.public_key) != _ED25519_PUBLIC_BYTES
        or not _utc(key.not_before) <= _utc(manifest.issued_at) < _utc(key.not_after)
        or _utc(manifest.expires_at) > _utc(key.not_after)
    ):
        raise ContinuityInvalidError
    try:
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(
            signature, _SIGNATURE_DOMAIN + _canonical(_manifest_document(manifest))
        )
    except (ValueError, InvalidSignature, UnsupportedAlgorithm) as error:
        raise ContinuityInvalidError from error


def sign_continuity_package(
    payload: bytes, manifest: ContinuityManifest, *, key: Ed25519PrivateKey
) -> bytes:
    """Sign owner-validated bytes without granting disclosure authority.

    Parameters
    ----------
    payload : bytes
        Bounded domain-validated data, not executable markup or untrusted input.
    manifest : ContinuityManifest
        Exact source, scope, expiry and matching payload digest.
    key : Ed25519PrivateKey
        Separately provisioned dedicated signing key; never returned or persisted here.

    Returns
    -------
    bytes
        Deterministic canonical package with no bundled verification key.

    Raises
    ------
    ContinuityInvalidError
        If the manifest, bound or exact payload digest is invalid.

    Notes
    -----
    This cryptographic primitive is not a serving entrypoint. Issuance must first
    obtain a fresh independently authorized owner projection and required audit.
    """
    document = _manifest_document(manifest)
    if (
        type(payload) is not bytes
        or not 0 < len(payload) <= MAX_CONTINUITY_PAYLOAD_BYTES
        or hashlib.sha256(payload).hexdigest() != manifest.payload_sha256
        or not isinstance(key, Ed25519PrivateKey)
    ):
        raise ContinuityInvalidError
    try:
        signature = key.sign(_SIGNATURE_DOMAIN + _canonical(document))
    except (ValueError, UnsupportedAlgorithm) as error:
        raise ContinuityInvalidError from error
    return _canonical(
        {
            "manifest": document,
            "payload": base64.b64encode(payload).decode("ascii"),
            "signature": base64.b64encode(signature).decode("ascii"),
        }
    )


def verify_continuity_package(
    package: bytes,
    *,
    expected_scope: ContinuityScope,
    trust: tuple[ContinuityTrustKey, ...],
    now: datetime,
) -> VerifiedContinuityPackage:
    """Verify integrity, expected scope and expiry without database or network access.

    Parameters
    ----------
    package : bytes
        Bounded canonical package; supplied keys and extra fields are rejected.
    expected_scope : ContinuityScope
        Independently provisioned context, not copied from the file being checked.
    trust : tuple[ContinuityTrustKey, ...]
        At most eight independently trusted verification keys with exact scope policy.
    now : datetime
        Aware verifier clock, unable to prove unseen revocation or clock compromise.

    Returns
    -------
    VerifiedContinuityPackage
        Authenticated bytes and signed checkpoint, still needing domain decoding and
        known-state comparison before normal on-site rendering.

    Raises
    ------
    ContinuityInvalidError
        If encoding, signature, scope, key, clock, expiry or payload integrity fails.
    """
    _scope_document(expected_scope)
    document = _json(
        package,
        frozenset({"manifest", "payload", "signature"}),
        maximum=MAX_CONTINUITY_PACKAGE_BYTES,
    )
    manifest = _decode_manifest(document["manifest"])
    if manifest.scope != expected_scope:
        raise ContinuityInvalidError
    signature = _base64(document["signature"], maximum=_ED25519_SIGNATURE_BYTES)
    _trusted_signature(manifest, signature, trust)
    if not _utc(manifest.issued_at) <= _utc(now) < _utc(manifest.expires_at):
        raise ContinuityInvalidError
    payload = _base64(document["payload"], maximum=MAX_CONTINUITY_PAYLOAD_BYTES)
    if not payload or hashlib.sha256(payload).hexdigest() != manifest.payload_sha256:
        raise ContinuityInvalidError
    checkpoint = _canonical(
        {"manifest": document["manifest"], "signature": document["signature"]}
    )
    return VerifiedContinuityPackage(manifest, payload, checkpoint)
