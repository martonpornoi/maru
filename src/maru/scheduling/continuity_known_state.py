"""Verify read-only continuity against protected local signed source history."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

from .continuity_protocol import (
    MAX_CONTINUITY_CHECKPOINT_BYTES,
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityScope,
    ContinuitySupersededError,
    ContinuityTrustKey,
    VerifiedContinuityPackage,
    _base64,
    _canonical,
    _date,
    _decode_manifest,
    _json,
    _scope_document,
    _trusted_signature,
    _utc,
    verify_continuity_package,
)

if TYPE_CHECKING:
    from datetime import datetime

CONTINUITY_KNOWN_STATE_CONTRACT = "scheduling.programme-continuity-known-state@1"
_MAX_KNOWN_STATE_BYTES = 2 * MAX_CONTINUITY_CHECKPOINT_BYTES + 1024
_SIGNATURE_BYTES = 64


def _checkpoint(
    value: object,
    *,
    expected_scope: ContinuityScope,
    trust: tuple[ContinuityTrustKey, ...],
) -> ContinuityManifest:
    data = _json(
        _canonical(value),
        frozenset({"manifest", "signature"}),
        maximum=MAX_CONTINUITY_CHECKPOINT_BYTES,
    )
    manifest = _decode_manifest(data["manifest"])
    # Known source changes apply across optional layer selections in the same purpose.
    if replace(manifest.scope, layers=()) != replace(expected_scope, layers=()):
        raise ContinuityInvalidError
    _trusted_signature(
        manifest, _base64(data["signature"], maximum=_SIGNATURE_BYTES), trust
    )
    return manifest


def _known(
    data: bytes,
    *,
    expected_scope: ContinuityScope,
    trust: tuple[ContinuityTrustKey, ...],
) -> tuple[dict[str, object], ContinuityManifest, ContinuityManifest | None]:
    document = _json(
        data,
        frozenset({"contract", "latest", "release_high_water", "last_verified_at"}),
        maximum=_MAX_KNOWN_STATE_BYTES,
    )
    if document["contract"] != CONTINUITY_KNOWN_STATE_CONTRACT:
        raise ContinuityInvalidError
    latest = _checkpoint(document["latest"], expected_scope=expected_scope, trust=trust)
    if (
        not _utc(latest.issued_at)
        <= _date(document["last_verified_at"])
        < _utc(latest.expires_at)
    ):
        raise ContinuityInvalidError
    high_water = (
        _checkpoint(
            document["release_high_water"], expected_scope=expected_scope, trust=trust
        )
        if document["release_high_water"] is not None
        else None
    )
    if high_water is None:
        if latest.pointer_version is not None:
            raise ContinuityInvalidError
    elif (
        high_water.pointer_version is None
        or _utc(high_water.observed_at) > _utc(latest.observed_at)
        or _utc(high_water.issued_at) > _utc(latest.issued_at)
        or (
            latest.pointer_version is not None
            and latest.pointer_version != high_water.pointer_version
        )
    ):
        raise ContinuityInvalidError
    return document, latest, high_water


def _not_older(
    current: ContinuityManifest,
    latest: ContinuityManifest,
    high_water: ContinuityManifest | None,
) -> None:
    observed, issued = _utc(current.observed_at), _utc(current.issued_at)
    old_observed, old_issued = _utc(latest.observed_at), _utc(latest.issued_at)
    if observed < old_observed or issued < old_issued:
        raise ContinuitySupersededError
    if observed == old_observed and current != latest:
        # No changed content, scope ceiling, key or expiry is silently ordered at one
        # source instant. A fresh source observation is required to resolve that tie.
        raise ContinuityInvalidError
    if (
        high_water is not None
        and high_water.pointer_version is not None
        and current.pointer_version is not None
        and current.pointer_version < high_water.pointer_version
    ):
        raise ContinuitySupersededError


def verify_continuity_with_known_state(
    package: bytes,
    *,
    expected_scope: ContinuityScope,
    trust: tuple[ContinuityTrustKey, ...],
    now: datetime,
    known_state: bytes | None,
    initialize: bool = False,
) -> tuple[VerifiedContinuityPackage, bytes]:
    """Reject old signed content and return the next protected local checkpoint.

    Parameters
    ----------
    package : bytes
        Untrusted snapshot, always fully verified before its content is returned.
    expected_scope : ContinuityScope
        Independently provisioned tenant, edition, purpose, person and field ceiling.
    trust : tuple[ContinuityTrustKey, ...]
        Trusted verification policy, not keys supplied by either input file.
    now : datetime
        Aware local verification clock, not proof of unseen online changes.
    known_state : bytes | None
        Protected signed metadata and local last-verification time, never payload.
        Preserve it across restarts; missing history is never silently reset.
    initialize : bool, default=False
        Explicit pre-outage initialization from a freshly obtained verified package.
        Not permission to reset missing, corrupt or rollback-suspected history.

    Returns
    -------
    tuple[VerifiedContinuityPackage, bytes]
        Authenticated current-to-known bytes and the next canonical history record.
        Persist the record safely before rendering the separately validated payload.

    Raises
    ------
    ContinuityInvalidError
        If trust, encoding, scope, expiry, known evidence or equal-time facts conflict.

    Notes
    -----
    ContinuitySupersededError propagates when a candidate predates known source
    time or release-pointer history. No payload is returned in that state.
    This operation has no filesystem, database or network side effects. It cannot
    detect an attacker restoring the whole protected filesystem or an unseen key
    revocation. Trusted custody and deliberate initialization remain prerequisites.
    Expired historical checkpoints retain their suppression force; expiry never
    licenses an older pack. A lost host purpose cannot erase a previously observed
    release-pointer high-water mark while retained own work remains independent.
    """
    _scope_document(expected_scope)
    if type(initialize) is not bool or (initialize and known_state is not None):
        raise ContinuityInvalidError
    verified = verify_continuity_package(
        package, expected_scope=expected_scope, trust=trust, now=now
    )
    checkpoint = json.loads(verified.checkpoint)
    if known_state is None:
        if not initialize:
            raise ContinuityInvalidError
        high_checkpoint = (
            checkpoint if verified.manifest.pointer_version is not None else None
        )
    else:
        document, latest, high_water = _known(
            known_state, expected_scope=expected_scope, trust=trust
        )
        if _utc(now) < _date(document["last_verified_at"]):
            raise ContinuityInvalidError
        _not_older(verified.manifest, latest, high_water)
        high_checkpoint = (
            checkpoint
            if verified.manifest.pointer_version is not None
            else document["release_high_water"]
        )
    result = _canonical(
        {
            "contract": CONTINUITY_KNOWN_STATE_CONTRACT,
            "latest": checkpoint,
            "release_high_water": high_checkpoint,
            "last_verified_at": _utc(now).isoformat(),
        }
    )
    if len(result) > _MAX_KNOWN_STATE_BYTES:
        raise ContinuityInvalidError
    return verified, result
