"""Real database-free signatures prove integrity, never owner authority."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maru.scheduling import continuity_protocol as protocol

NOW = datetime(2030, 8, 2, 12, tzinfo=UTC)
PAYLOAD = b'{"fixture":"synthetic"}'


@pytest.fixture
def fixture():
    key = Ed25519PrivateKey.generate()
    scope = protocol.ContinuityScope(UUID(int=1), UUID(int=2), "public")
    manifest = protocol.ContinuityManifest(
        scope,
        "synthetic-key-1",
        NOW,
        NOW,
        NOW + timedelta(hours=1),
        "Europe/Budapest",
        "available",
        1,
        UUID(int=3),
        hashlib.sha256(PAYLOAD).hexdigest(),
    )
    trust = protocol.ContinuityTrustKey(
        scope.organization_id,
        scope.edition_id,
        manifest.key_id,
        key.public_key().public_bytes_raw(),
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
    )
    return key, manifest, trust


def encoded(document):
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def verified(package, manifest, trust, *, now=NOW):
    return protocol.verify_continuity_package(
        package, expected_scope=manifest.scope, trust=(trust,), now=now
    )


def test_real_signature_round_trip_is_deterministic_and_contains_no_key(fixture):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    assert package == protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    result = verified(package, manifest, trust)
    assert result.manifest == manifest
    assert result.payload == PAYLOAD
    assert json.loads(result.checkpoint).keys() == {"manifest", "signature"}
    assert json.loads(package).keys() == {"manifest", "payload", "signature"}
    assert b"public_key" not in package
    assert b"private_key" not in package


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", UUID(int=9)),
        ("edition_id", UUID(int=9)),
        ("audience", "exact_person"),
        ("actor_id", UUID(int=9)),
        ("kind", "room"),
        ("target_id", UUID(int=9)),
        ("layers", ("technical",)),
    ],
)
def test_expected_scope_is_not_taken_from_signed_file(fixture, field, value):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(
            package,
            replace(manifest, scope=replace(manifest.scope, **{field: value})),
            trust,
        )


@pytest.mark.parametrize(
    "scope",
    [
        protocol.ContinuityScope(
            UUID(int=1), UUID(int=2), "exact_person", UUID(int=7), "personal"
        ),
        protocol.ContinuityScope(
            UUID(int=1),
            UUID(int=2),
            "private_operator",
            UUID(int=7),
            "room",
            UUID(int=8),
            ("media", "technical"),
        ),
        protocol.ContinuityScope(
            UUID(int=1),
            UUID(int=2),
            "private_operator",
            UUID(int=7),
            "department",
            UUID(int=8),
        ),
        protocol.ContinuityScope(
            UUID(int=1),
            UUID(int=2),
            "private_operator",
            UUID(int=7),
            "edition",
            UUID(int=2),
            ("staffing",),
        ),
    ],
)
def test_private_scope_roundtrip_and_wrong_actual_person_denial(fixture, scope):
    key, manifest, trust = fixture
    manifest = replace(manifest, scope=scope)
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    assert verified(package, manifest, trust).manifest.scope == scope
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(
            package,
            replace(manifest, scope=replace(scope, actor_id=UUID(int=99))),
            trust,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key_id", "unknown"),
        ("public_key", bytes(32)),
        ("organization_id", UUID(int=9)),
        ("edition_id", UUID(int=9)),
        ("not_before", NOW + timedelta(seconds=1)),
        ("not_after", NOW + timedelta(minutes=59)),
    ],
)
def test_key_identity_scope_and_lifetime_are_independently_trusted(
    fixture, field, value
):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package, manifest, replace(trust, **{field: value}))


@pytest.mark.parametrize("delta", [-1, 3600, 3601])
def test_future_clock_and_expiry_have_no_implicit_grace(fixture, delta):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package, manifest, trust, now=NOW + timedelta(seconds=delta))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issued_at", NOW + timedelta(minutes=6)),
        ("observed_at", NOW + timedelta(seconds=1)),
        ("expires_at", NOW + timedelta(hours=4, seconds=1)),
        ("expires_at", NOW),
        ("observed_at", NOW.replace(tzinfo=None)),
        ("zone_name", "../UTC"),
        ("zone_name", "invented/timezone"),
        ("pointer_version", True),
        ("pointer_version", -1),
        ("pointer_version", 2**63),
        ("release_id", None),
        ("release_id", UUID(int=0)),
        ("release_state", "live"),
        ("release_state", "unobserved"),
        ("payload_sha256", "a" * 63),
        ("payload_sha256", "A" * 64),
        ("payload_sha256", "a" * 64),
        ("key_id", "https://example.invalid/key"),
    ],
)
def test_malformed_manifest_cannot_be_signed(fixture, field, value):
    key, manifest, _trust = fixture
    with pytest.raises(protocol.ContinuityInvalidError):
        protocol.sign_continuity_package(
            PAYLOAD, replace(manifest, **{field: value}), key=key
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(public_key="attacker-supplied"),
        lambda data: data.update(signature=base64.b64encode(bytes(64)).decode()),
        lambda data: data.update(payload=base64.b64encode(b"substituted").decode()),
        lambda data: data["manifest"].update(expires_at="2030-08-03T12:00:00+00:00"),
        lambda data: data["manifest"].update(unknown=True),
        lambda data: data["manifest"]["scope"].update(kind=[]),
        lambda data: data["manifest"]["scope"].update(layers=[[]]),
        lambda data: data["manifest"].update(issued_at=float("nan")),
        lambda data: data.update(signature="*not-base64*"),
    ],
)
def test_untrusted_changes_fail_before_returning_payload(fixture, change):
    key, manifest, trust = fixture
    data = json.loads(protocol.sign_continuity_package(PAYLOAD, manifest, key=key))
    change(data)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(encoded(data), manifest, trust)


@pytest.mark.parametrize(
    "package",
    [
        b"",
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"manifest":{},"manifest":{}}',
        b"[" * 1100 + b"]" * 1100,
    ],
)
def test_bad_json_is_a_safe_domain_error(fixture, package):
    _key, manifest, trust = fixture
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package, manifest, trust)


def test_noncanonical_encoding_and_ambiguous_trust_fail(fixture):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package + b"\n", manifest, trust)
    for keys in ((), (trust, trust), (trust,) * 9):
        with pytest.raises(protocol.ContinuityInvalidError):
            protocol.verify_continuity_package(
                package, expected_scope=manifest.scope, trust=keys, now=NOW
            )


def test_payload_and_package_limits_are_enforced_before_return(fixture, monkeypatch):
    key, manifest, trust = fixture
    package = protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    monkeypatch.setattr(protocol, "MAX_CONTINUITY_PAYLOAD_BYTES", len(PAYLOAD) - 1)
    with pytest.raises(protocol.ContinuityInvalidError):
        protocol.sign_continuity_package(PAYLOAD, manifest, key=key)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package, manifest, trust)
    monkeypatch.setattr(protocol, "MAX_CONTINUITY_PACKAGE_BYTES", len(package) - 1)
    with pytest.raises(protocol.ContinuityInvalidError):
        verified(package, manifest, trust)
