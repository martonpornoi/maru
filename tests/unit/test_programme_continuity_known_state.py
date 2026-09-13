"""Expired and purpose-changing signed evidence cannot reset local release history."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maru.scheduling import continuity_known_state as state
from maru.scheduling import continuity_protocol as protocol

NOW = datetime(2030, 8, 2, 12, tzinfo=UTC)


@pytest.fixture
def fixture():
    key = Ed25519PrivateKey.generate()
    scope = protocol.ContinuityScope(
        UUID(int=1), UUID(int=2), "exact_person", UUID(int=3), "personal"
    )
    trust = protocol.ContinuityTrustKey(
        scope.organization_id,
        scope.edition_id,
        "test-key",
        key.public_key().public_bytes_raw(),
        NOW - timedelta(days=1),
        NOW + timedelta(days=2),
    )
    manifest = protocol.ContinuityManifest(
        scope,
        trust.key_id,
        NOW,
        NOW,
        NOW + timedelta(hours=1),
        "Europe/Budapest",
        "available",
        5,
        UUID(int=4),
        hashlib.sha256(b"synthetic").hexdigest(),
    )
    return key, trust, manifest


def sign(key, manifest):
    return protocol.sign_continuity_package(b"synthetic", manifest, key=key)


def advance(fixture, *, manifest=None, known=None, initialize=False, now=None):
    key, trust, original = fixture
    manifest = manifest or original
    return state.verify_continuity_with_known_state(
        sign(key, manifest),
        expected_scope=manifest.scope,
        trust=(trust,),
        now=now or manifest.issued_at,
        known_state=known,
        initialize=initialize,
    )


def later(manifest, *, minutes=1, **changes):
    delta = timedelta(minutes=minutes)
    return replace(
        manifest,
        observed_at=manifest.observed_at + delta,
        issued_at=manifest.issued_at + delta,
        expires_at=manifest.expires_at + delta,
        **changes,
    )


def test_initialization_is_explicit_and_replay_retains_identical_metadata(fixture):
    with pytest.raises(protocol.ContinuityInvalidError):
        advance(fixture)
    verified, known = advance(fixture, initialize=True)
    assert verified.payload == b"synthetic"
    assert b'"payload"' not in known
    assert advance(fixture, known=known)[1] == known
    with pytest.raises(protocol.ContinuityInvalidError):
        advance(fixture, known=known, initialize=True)


@pytest.mark.parametrize("release_state", ["withdrawn", "invalidated"])
def test_newer_suppression_cannot_be_replaced_with_still_unexpired_old_pack(
    fixture, release_state
):
    _key, _trust, manifest = fixture
    _, known = advance(fixture, initialize=True)
    newer = later(
        manifest,
        release_state=release_state,
        pointer_version=6,
        release_id=None if release_state == "withdrawn" else manifest.release_id,
    )
    current, known = advance(fixture, manifest=newer, known=known)
    assert current.manifest.release_state == release_state
    with pytest.raises(protocol.ContinuitySupersededError):
        advance(fixture, known=known, now=newer.issued_at)


def test_expired_known_overlay_still_refuses_later_observed_lower_pointer(fixture):
    _key, _trust, manifest = fixture
    _, known = advance(fixture, initialize=True)
    expired_overlay = later(
        manifest, pointer_version=7, release_state="withdrawn", release_id=None
    )
    _, known = advance(fixture, manifest=expired_overlay, known=known)
    rollback = later(manifest, minutes=120, pointer_version=6)
    with pytest.raises(protocol.ContinuitySupersededError):
        advance(fixture, manifest=rollback, known=known)
    recovered = replace(rollback, pointer_version=8)
    assert (
        advance(fixture, manifest=recovered, known=known)[0].manifest.pointer_version
        == 8
    )


def test_lost_host_purpose_does_not_erase_release_high_water(fixture):
    _key, _trust, manifest = fixture
    _, known = advance(fixture, initialize=True)
    no_host = later(
        manifest, release_state="unobserved", pointer_version=None, release_id=None
    )
    current, known = advance(fixture, manifest=no_host, known=known)
    assert current.manifest.release_state == "unobserved"
    assert json.loads(known)["release_high_water"]["manifest"]["pointer_version"] == 5
    with pytest.raises(protocol.ContinuitySupersededError):
        advance(
            fixture, manifest=later(manifest, minutes=2, pointer_version=4), known=known
        )
    assert advance(
        fixture, manifest=later(manifest, minutes=2, pointer_version=6), known=known
    )


def test_later_issue_time_cannot_order_changed_facts_at_same_source_instant(fixture):
    _key, _trust, manifest = fixture
    _, known = advance(fixture, initialize=True)
    changed = replace(manifest, issued_at=NOW + timedelta(seconds=1), pointer_version=6)
    with pytest.raises(protocol.ContinuityInvalidError):
        advance(fixture, manifest=changed, known=known)


@pytest.mark.parametrize(
    "value",
    [b"", b"null", b"{}", b'{"contract":1,"contract":1}', b"[" * 1100 + b"]" * 1100],
)
def test_corrupt_known_history_is_never_implicitly_reset(fixture, value):
    with pytest.raises(protocol.ContinuityInvalidError):
        advance(fixture, known=value)


def test_foreign_and_forged_known_evidence_is_rejected(fixture):
    _key, _trust, manifest = fixture
    _, known = advance(fixture, initialize=True)
    for field, value in [("pointer_version", 999), ("release_state", "withdrawn")]:
        data = json.loads(known)
        data["latest"]["manifest"][field] = value
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(protocol.ContinuityInvalidError):
            advance(fixture, known=encoded)
    foreign = replace(manifest, scope=replace(manifest.scope, actor_id=UUID(int=99)))
    _, foreign_known = advance(fixture, manifest=foreign, initialize=True)
    with pytest.raises(protocol.ContinuityInvalidError):
        advance(fixture, manifest=later(manifest), known=foreign_known)


def test_known_withdrawal_applies_across_operator_layer_selections(fixture):
    key, trust, manifest = fixture
    scope = protocol.ContinuityScope(
        manifest.scope.organization_id,
        manifest.scope.edition_id,
        "private_operator",
        manifest.scope.actor_id,
        "room",
        UUID(int=7),
        ("technical",),
    )
    manifest = replace(manifest, scope=scope)
    fixture = key, trust, manifest
    _, old_known = advance(fixture, initialize=True)
    narrower = later(
        manifest,
        scope=replace(scope, layers=()),
        release_state="withdrawn",
        pointer_version=6,
        release_id=None,
    )
    _, known = advance(fixture, manifest=narrower, known=old_known)
    with pytest.raises(protocol.ContinuitySupersededError):
        advance(fixture, known=known, now=narrower.issued_at)
