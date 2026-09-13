"""Real bounded temporary-file verification, never PostgreSQL or a network relay."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maru.scheduling import continuity_offline as offline
from maru.scheduling.continuity_payload import (
    ContinuityEntry,
    ContinuityProjection,
    encode_continuity_payload,
)
from maru.scheduling.continuity_protocol import (
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityScope,
    ContinuitySupersededError,
    sign_continuity_package,
)

NOW = datetime(2030, 8, 2, 12, tzinfo=UTC)


def encoded(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def fixture(tmp_path):
    key = Ed25519PrivateKey.generate()
    scope = ContinuityScope(UUID(int=1), UUID(int=2), "public")
    projection = ContinuityProjection(
        scope,
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
        (
            ContinuityEntry(
                f"public:{UUID(int=4)}",
                "public_event",
                "Synthetic opening",
                NOW,
                NOW + timedelta(hours=1),
                UUID(int=5),
                UUID(int=6),
                None,
                (),
            ),
        ),
    )
    manifest = ContinuityManifest(
        scope,
        "ephemeral",
        NOW,
        NOW,
        NOW + timedelta(hours=1),
        "Europe/Budapest",
        "available",
        1,
        UUID(int=3),
        hashlib.sha256(encode_continuity_payload(projection)).hexdigest(),
    )
    package = tmp_path / "pack.json"
    package.write_bytes(
        sign_continuity_package(
            encode_continuity_payload(projection), manifest, key=key
        )
    )
    trust = tmp_path / "trust.json"
    trust.write_bytes(
        encoded(
            {
                "contract": offline.TRUST_POLICY_CONTRACT,
                "keys": [
                    {
                        "organization_id": str(scope.organization_id),
                        "edition_id": str(scope.edition_id),
                        "key_id": "ephemeral",
                        "public_key_b64": base64.b64encode(
                            key.public_key().public_bytes_raw()
                        ).decode(),
                        "not_before": (NOW - timedelta(days=1)).isoformat(),
                        "not_after": (NOW + timedelta(days=1)).isoformat(),
                    }
                ],
            }
        )
    )
    arguments = {
        "package_path": package,
        "trust_path": trust,
        "known_state_path": tmp_path / "known.json",
        "output_path": tmp_path / "copy.html",
        "expected_scope": scope,
        "now": NOW,
        "initialize": True,
    }
    return key, projection, manifest, arguments


def test_real_file_initialization_and_replay_keep_complete_dated_copy(fixture):
    _key, _projection, _manifest, arguments = fixture
    offline.verify_continuity_files(**arguments)
    html = arguments["output_path"].read_text(encoding="utf-8")
    assert "Synthetic opening" in html
    assert "not a live verifier" in html
    known = arguments["known_state_path"].read_bytes()
    assert b"Synthetic opening" not in known
    assert json.loads(known)["last_verified_at"] == NOW.isoformat()
    assert not arguments["known_state_path"].with_suffix(".json.lock").exists()
    offline.verify_continuity_files(
        **(
            arguments
            | {
                "initialize": False,
                "output_path": arguments["output_path"].with_name("next-copy.html"),
                "now": NOW + timedelta(minutes=1),
            }
        )
    )
    assert (
        json.loads(arguments["known_state_path"].read_bytes())["last_verified_at"]
        == (NOW + timedelta(minutes=1)).isoformat()
    )


@pytest.mark.parametrize(
    "mutation", ["signature", "expired", "scope", "missing_history", "missing_trust"]
)
def test_failed_verification_never_creates_normal_html_or_history(fixture, mutation):
    _key, _projection, _manifest, arguments = fixture
    if mutation == "signature":
        document = json.loads(arguments["package_path"].read_bytes())
        document["signature"] = base64.b64encode(b"x" * 64).decode()
        arguments["package_path"].write_bytes(encoded(document))
    elif mutation == "expired":
        arguments["now"] = NOW + timedelta(hours=1)
    elif mutation == "scope":
        arguments["expected_scope"] = replace(
            arguments["expected_scope"], edition_id=UUID(int=9)
        )
    elif mutation == "missing_history":
        arguments["initialize"] = False
    else:
        arguments["trust_path"].unlink()
    with pytest.raises((ContinuityInvalidError, OSError)):
        offline.verify_continuity_files(**arguments)
    assert not arguments["output_path"].exists()
    assert not arguments["known_state_path"].exists()


def test_existing_output_and_path_collision_are_never_overwritten(fixture):
    _key, _projection, _manifest, arguments = fixture
    arguments["output_path"].write_bytes(b"preserve this")
    with pytest.raises(ContinuityInvalidError):
        offline.verify_continuity_files(**arguments)
    assert arguments["output_path"].read_bytes() == b"preserve this"
    original = arguments["trust_path"].read_bytes()
    with pytest.raises(ContinuityInvalidError):
        offline.verify_continuity_files(
            **(arguments | {"output_path": arguments["trust_path"]})
        )
    assert arguments["trust_path"].read_bytes() == original


def test_locked_purpose_and_existing_history_are_never_implicitly_reset(fixture):
    _key, _projection, _manifest, arguments = fixture
    lock = arguments["known_state_path"].with_suffix(".json.lock")
    lock.write_bytes(b"another verifier or interrupted recovery")
    with pytest.raises(FileExistsError):
        offline.verify_continuity_files(**arguments)
    assert lock.read_bytes() == b"another verifier or interrupted recovery"
    lock.unlink()
    arguments["known_state_path"].write_bytes(b"corrupt or existing history")
    with pytest.raises(ContinuityInvalidError):
        offline.verify_continuity_files(**arguments)
    assert arguments["known_state_path"].read_bytes() == b"corrupt or existing history"


def test_newer_withdrawal_is_saved_and_refuses_older_signed_file(fixture):
    key, projection, manifest, arguments = fixture
    offline.verify_continuity_files(**arguments)
    old = arguments["package_path"].read_bytes()
    later = NOW + timedelta(minutes=1)
    suppressed = replace(
        projection,
        observed_at=later,
        release_state="withdrawn",
        pointer_version=2,
        release_id=None,
        published_at=None,
        entries=(),
    )
    payload = encode_continuity_payload(suppressed)
    overlay = replace(
        manifest,
        observed_at=later,
        issued_at=later,
        release_state="withdrawn",
        pointer_version=2,
        release_id=None,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    arguments["package_path"].write_bytes(
        sign_continuity_package(payload, overlay, key=key)
    )
    destination = arguments["output_path"].with_name("withdrawn.html")
    current = arguments | {
        "initialize": False,
        "now": later,
        "output_path": destination,
    }
    offline.verify_continuity_files(**current)
    assert "Synthetic opening" not in destination.read_text(encoding="utf-8")
    assert "Programme withdrawn" in destination.read_text(encoding="utf-8")
    arguments["package_path"].write_bytes(old)
    with pytest.raises(ContinuitySupersededError):
        offline.verify_continuity_files(
            **(current | {"output_path": destination.with_name("refused.html")})
        )
    assert not destination.with_name("refused.html").exists()
    assert (
        json.loads(arguments["known_state_path"].read_bytes())["latest"]["manifest"][
            "pointer_version"
        ]
        == 2
    )


def test_signed_newer_metadata_is_retained_even_when_payload_cannot_render(fixture):
    key, _projection, manifest, arguments = fixture
    malformed = b"not a complete payload"
    newer = replace(
        manifest,
        pointer_version=2,
        payload_sha256=hashlib.sha256(malformed).hexdigest(),
    )
    arguments["package_path"].write_bytes(
        sign_continuity_package(malformed, newer, key=key)
    )
    with pytest.raises(ContinuityInvalidError):
        offline.verify_continuity_files(**arguments)
    assert not arguments["output_path"].exists()
    assert (
        json.loads(arguments["known_state_path"].read_bytes())["latest"]["manifest"][
            "pointer_version"
        ]
        == 2
    )


def test_state_persistence_failure_prevents_rendering_and_output(fixture, monkeypatch):
    _key, _projection, _manifest, arguments = fixture
    calls = []

    def failed_save(path, _data, *, replace_existing):
        calls.append(path)
        raise OSError("synthetic full disk")

    monkeypatch.setattr(offline, "_save", failed_save)
    with pytest.raises(OSError, match="synthetic full disk"):
        offline.verify_continuity_files(**arguments)
    assert calls == [arguments["known_state_path"]]
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize(
    "document",
    [
        {"contract": offline.TRUST_POLICY_CONTRACT, "keys": []},
        {
            "contract": offline.TRUST_POLICY_CONTRACT,
            "keys": [{"url": "https://example.invalid/key"}],
        },
        {"contract": "untrusted", "keys": []},
    ],
)
def test_trust_requires_independent_closed_policy_not_key_urls(document):
    with pytest.raises(ContinuityInvalidError):
        offline.decode_continuity_trust_policy(encoded(document))


def test_cli_has_no_clock_override_and_reports_no_private_failure_content(
    fixture, capsys
):
    _key, _projection, _manifest, arguments = fixture
    args = [
        "--package",
        str(arguments["package_path"]),
        "--trust",
        str(arguments["trust_path"]),
        "--known-state",
        str(arguments["known_state_path"]),
        "--output",
        str(arguments["output_path"]),
        "--organization",
        str(UUID(int=1)),
        "--edition",
        str(UUID(int=2)),
        "--audience",
        "public",
        "--kind",
        "public",
    ]
    assert offline.main(args) == 2
    stderr = capsys.readouterr().err
    assert "Do not reuse an older copy" in stderr
    assert "Synthetic opening" not in stderr
    with pytest.raises(SystemExit) as raised:
        offline.main([*args, "--at", NOW.isoformat()])
    assert raised.value.code == 2
