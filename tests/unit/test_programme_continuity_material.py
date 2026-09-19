"""Actual independent key/policy codecs; no fixture server, database or native proof."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from maru.scheduling.continuity_offline import decode_continuity_trust_policy
from maru.scheduling.continuity_signing import load_continuity_signing_policy
from tests.rehearsals import programme_continuity_material as material
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


@pytest.fixture
def permitted(monkeypatch):
    monkeypatch.setattr(
        material,
        "require_programme_rehearsal_request",
        Mock(return_value=SimpleNamespace(run_id="a" * 32, lease_seconds=3600)),
    )
    monkeypatch.setattr(material, "remaining_lease", Mock(return_value=1800.0))
    return SimpleNamespace(organization_id=uuid4(), edition_id=uuid4())


def test_dedicated_key_and_independent_trust_decode_through_actual_contracts(permitted):
    result = material.generate_continuity_material(permitted, deadline=1900.0)
    policy = load_continuity_signing_policy(
        environment={material.SIGNING_ENV: result.signing_policy}
    )
    trust = decode_continuity_trust_policy(result.trust_policy)
    assert policy.lifetime_seconds == 300
    assert len(policy.keys) == 1
    assert len(trust) == 1
    assert policy.keys[0].trust == trust[0]
    assert trust[0].organization_id == permitted.organization_id
    assert trust[0].edition_id == permitted.edition_id
    assert (trust[0].not_after - trust[0].not_before).total_seconds() == 1801
    signature = policy.keys[0].private_key.sign(b"independent-fixture-trust")
    Ed25519PublicKey.from_public_bytes(trust[0].public_key).verify(
        signature, b"independent-fixture-trust"
    )
    private = json.loads(result.signing_policy)["keys"][0]["private_key_b64"]
    assert len(base64.b64decode(private)) == 32
    assert private not in repr(result)
    assert private.encode() not in result.trust_policy
    assert b"private_key" not in result.trust_policy
    second = material.generate_continuity_material(permitted, deadline=1900.0)
    assert second.signing_policy != result.signing_policy
    assert second.trust_policy != result.trust_policy


@pytest.mark.parametrize("remaining", [300.0, 301.0, 3601.0])
def test_short_or_extended_lease_cannot_generate_keys(
    permitted, monkeypatch, remaining
):
    monkeypatch.setattr(material, "remaining_lease", Mock(return_value=remaining))
    with pytest.raises(material.ProgrammeHttpsError, match="lease_insufficient"):
        material.generate_continuity_material(permitted, deadline=1900.0)


@pytest.mark.parametrize("value", [UUID(int=0), None, "not-a-scope"])
def test_unbound_scope_cannot_generate_keys(permitted, value):
    permitted.edition_id = value
    with pytest.raises(material.ProgrammeHttpsError, match="scope_invalid"):
        material.generate_continuity_material(permitted, deadline=1900.0)


def test_native_deferral_precedes_scope_or_crypto(monkeypatch):
    monkeypatch.setattr(
        material,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        material.generate_continuity_material(None, deadline=None)
