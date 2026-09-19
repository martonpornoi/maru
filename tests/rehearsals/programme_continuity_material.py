"""Dedicated ephemeral signing and independent offline trust for one native fixture."""

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

SIGNING_ENV = "MARU_PROGRAMME_CONTINUITY_SIGNING_KEYS_JSON"
LIFETIME_SECONDS = 300


def _canonical(document):
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


@dataclass(frozen=True, slots=True)
class ProgrammeContinuityMaterial:
    """Keep the issuer secret separate from independently provisioned verifier trust."""

    organization_id: UUID
    edition_id: UUID
    signing_policy: str = field(repr=False)
    trust_policy: bytes = field(repr=False)


def generate_continuity_material(setup, *, deadline):
    """Generate a synthetic five-minute policy without extending the owned lease."""
    request = require_programme_rehearsal_request()
    remaining = remaining_lease(deadline)
    if remaining <= LIFETIME_SECONDS + 1 or remaining > request.lease_seconds:
        raise ProgrammeHttpsError("fixture_continuity_lease_insufficient")
    if any(
        type(value) is not UUID or value.int == 0
        for value in (setup.organization_id, setup.edition_id)
    ):
        raise ProgrammeHttpsError("fixture_continuity_scope_invalid")
    now = datetime.now(UTC)
    key = Ed25519PrivateKey.generate()
    shared = {
        "organization_id": str(setup.organization_id),
        "edition_id": str(setup.edition_id),
        "key_id": "fixture-" + request.run_id,
        "not_before": (now - timedelta(seconds=1)).isoformat(),
        "not_after": (now + timedelta(seconds=remaining)).isoformat(),
    }
    signing = {
        "contract": "scheduling.programme-continuity-signing-policy@1",
        "lifetime_seconds": LIFETIME_SECONDS,
        "keys": [
            shared
            | {
                "private_key_b64": base64.b64encode(key.private_bytes_raw()).decode(
                    "ascii"
                )
            }
        ],
    }
    trust = {
        "contract": "scheduling.programme-continuity-trust@1",
        "keys": [
            shared
            | {
                "public_key_b64": base64.b64encode(
                    key.public_key().public_bytes_raw()
                ).decode("ascii")
            }
        ],
    }
    return ProgrammeContinuityMaterial(
        setup.organization_id,
        setup.edition_id,
        _canonical(signing),
        _canonical(trust).encode("utf-8"),
    )
