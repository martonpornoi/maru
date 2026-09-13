"""Ephemeral signing keys exercise scoped issuance without PostgreSQL."""

import base64
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maru.scheduling import continuity_signing as signing
from maru.scheduling.continuity_payload import (
    ContinuityProjection,
    decode_continuity_payload,
)
from maru.scheduling.continuity_protocol import (
    ContinuityScope,
    ContinuityTrustKey,
    verify_continuity_package,
)

NOW = datetime(2030, 8, 2, 12, tzinfo=UTC)


@pytest.fixture
def fixture():
    projection = ContinuityProjection(
        ContinuityScope(UUID(int=1), UUID(int=2), "public"),
        "scheduling.public-timetable@1",
        "a" * 64,
        NOW,
        "Europe/Budapest",
        "available",
        1,
        UUID(int=3),
        NOW - timedelta(minutes=1),
        "not_applicable",
        "not_applicable",
        (),
    )
    key = Ed25519PrivateKey.generate()
    trust = ContinuityTrustKey(
        UUID(int=1),
        UUID(int=2),
        "ephemeral-test",
        key.public_key().public_bytes_raw(),
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
    )
    return projection, signing.ContinuitySigningPolicy(
        (signing.ContinuitySigningKey(trust, key),)
    )


def config(policy):
    key = policy.keys[0]
    return {
        "contract": signing.SIGNING_POLICY_CONTRACT,
        "lifetime_seconds": policy.lifetime_seconds,
        "keys": [
            {
                "organization_id": str(key.trust.organization_id),
                "edition_id": str(key.trust.edition_id),
                "key_id": key.trust.key_id,
                "private_key_b64": base64.b64encode(
                    key.private_key.private_bytes_raw()
                ).decode(),
                "not_before": key.trust.not_before.isoformat(),
                "not_after": key.trust.not_after.isoformat(),
            }
        ],
    }


def environment(document):
    return {
        signing.SIGNING_POLICY_ENVIRONMENT: json.dumps(
            document, sort_keys=True, separators=(",", ":")
        )
    }


def test_real_dedicated_key_signs_default_one_hour_and_roundtrips(fixture):
    projection, policy = fixture
    loaded = signing.load_continuity_signing_policy(environment(config(policy)))
    package = signing.sign_continuity_projection(
        projection, policy=loaded, issued_at=NOW
    )
    assert package == signing.sign_continuity_projection(
        projection, policy=policy, issued_at=NOW
    )
    verified = verify_continuity_package(
        package, expected_scope=projection.scope, trust=(policy.keys[0].trust,), now=NOW
    )
    assert verified.manifest.expires_at == NOW + timedelta(hours=1)
    assert (
        decode_continuity_payload(verified.payload, manifest=verified.manifest)
        == projection
    )
    assert b"private_key" not in package
    assert "private_key" not in repr(policy.keys[0])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", UUID(int=9)),
        ("edition_id", UUID(int=9)),
        ("not_before", NOW + timedelta(seconds=1)),
        ("not_after", NOW),
        ("not_after", NOW + timedelta(minutes=59)),
        ("key_id", "invalid key id"),
        ("public_key", b"x" * 32),
    ],
)
def test_scope_key_or_validity_failure_never_mints_a_pack(fixture, field, value):
    projection, policy = fixture
    key = replace(policy.keys[0], trust=replace(policy.keys[0].trust, **{field: value}))
    with pytest.raises(signing.ContinuitySigningUnavailableError):
        signing.sign_continuity_projection(
            projection, policy=replace(policy, keys=(key,)), issued_at=NOW
        )


@pytest.mark.parametrize("lifetime", [True, 0, -1, 14401, "3600", None])
def test_invalid_expiry_policy_is_not_silently_defaulted(fixture, lifetime):
    projection, policy = fixture
    with pytest.raises(signing.ContinuitySigningUnavailableError):
        signing.sign_continuity_projection(
            projection, policy=replace(policy, lifetime_seconds=lifetime), issued_at=NOW
        )


def test_source_age_and_ambiguous_active_keys_fail_closed(fixture):
    projection, policy = fixture
    with pytest.raises(signing.ContinuitySigningUnavailableError):
        signing.sign_continuity_projection(
            projection, policy=policy, issued_at=NOW + timedelta(minutes=5, seconds=1)
        )
    with pytest.raises(signing.ContinuitySigningUnavailableError):
        signing.sign_continuity_projection(
            projection, policy=replace(policy, keys=policy.keys * 2), issued_at=NOW
        )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "{}",
        "[]",
        '{"contract":1,"contract":2}',
        "invalid",
        pytest.param("x" * 32769, id="overbound"),
    ],
)
def test_missing_malformed_and_overbound_configuration_is_secret_free(raw):
    with pytest.raises(signing.ContinuitySigningUnavailableError) as raised:
        signing.load_continuity_signing_policy(
            {signing.SIGNING_POLICY_ENVIRONMENT: raw}
        )
    assert (
        str(raised.value)
        == "Signed continuity export is not configured for this scope."
    )
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "mutation", ["contract", "lifetime", "extra", "key", "empty", "unknown_key"]
)
def test_closed_configuration_rejects_invalid_fields(fixture, mutation):
    _projection, policy = fixture
    document = config(policy)
    if mutation == "contract":
        document["contract"] = "unknown"
    elif mutation == "lifetime":
        document["lifetime_seconds"] = True
    elif mutation == "extra":
        document["fallback"] = True
    elif mutation == "key":
        document["keys"][0]["private_key_b64"] = "not a key"
    elif mutation == "empty":
        document["keys"] = []
    else:
        document["keys"][0]["secret_key"] = "must not be used"
    with pytest.raises(signing.ContinuitySigningUnavailableError):
        signing.load_continuity_signing_policy(environment(document))


def test_offline_codecs_import_without_django_configuration_or_owner_models():
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys\n"
            "from maru.scheduling import continuity_protocol, continuity_payload\n"
            "from maru.scheduling import continuity_known_state\n"
            "assert 'django' not in sys.modules\n"
            "assert not any(name.endswith('.models') for name in sys.modules)\n",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
