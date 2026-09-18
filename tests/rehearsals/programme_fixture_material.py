"""Ephemeral synthetic fixture configuration with separate web/worker secrets.

Import is pure. Generation requires the tracked native policy and explicit run
opt-in, and opens no socket, file or database. Nothing here configures production.
"""

import base64
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
    require_programme_rehearsal_request,
)

BOOTSTRAP_VERSION = "foundation-v1"
ADMIN_PASSWORD_ENV = "MARU_PROGRAMME_REHEARSAL_ADMIN_PASSWORD"
PRIVATE_KEYS_ENV = "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON"


def synthetic_retention_policy(run_id):
    """Return a fictional one-day fixture policy, never a production approval."""
    return {
        "policy_id": f"synthetic-programme-{run_id}",
        "version": 1,
        "jurisdiction_code": "SYNTHETIC",
        "trigger": "terminal_transition",
        "period_days": 1,
        "action": "anonymize_abandoned_invitation_contact",
        "approved_by_reference": "isolated-fixture-only",
    }


@dataclass(frozen=True, slots=True)
class ProgrammeFixtureMaterial:
    """In-memory run material; never log, serialize or retain these fields."""

    run_id: str
    web_port: int
    secret_key: str = field(repr=False)
    administrator_password: str = field(repr=False)
    runtime_configuration: Mapping[str, str] = field(repr=False)
    invitation_private_keys: str = field(repr=False)

    def owner_environment(self):
        """Return only the stopped owner bootstrap configuration, no worker key."""
        return dict(self.runtime_configuration) | {
            "MARU_PROGRAMME_REHEARSAL_BOOTSTRAP": BOOTSTRAP_VERSION,
            ADMIN_PASSWORD_ENV: self.administrator_password,
        }

    def worker_environment(self):
        """Return only worker configuration, never the administrator password."""
        return dict(self.runtime_configuration) | {
            PRIVATE_KEYS_ENV: self.invitation_private_keys
        }


def generate_fixture_material(*, web_port):
    """Generate fresh keys for one opted-in future loopback HTTPS fixture.

    Parameters
    ----------
    web_port
        Exact future nonprivileged loopback HTTPS port owned by the launcher.
        This function does not bind it or claim transport readiness.

    Returns
    -------
    ProgrammeFixtureMaterial
        Distinct web HMAC/session, worker decryption and bootstrap credentials.
        The private delivery key is absent from web and owner environments.
    """
    request = require_programme_rehearsal_request()
    if type(web_port) is not int or not 1024 <= web_port <= 65535:
        raise ProgrammeRehearsalEnvironmentError("invalid_fixture_web_port")
    key_id = f"programme-{request.run_id}"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    policy = synthetic_retention_policy(request.run_id) | {
        # A fictional fixture approval, deliberately earlier than the DB clock;
        # actual activation and worker evidence still use native clock_timestamp.
        "approved_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    }
    configuration = MappingProxyType(
        {
            "MARU_PUBLIC_BASE_URL": f"https://127.0.0.1:{web_port}",
            "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID": key_id,
            "MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64": base64.b64encode(
                public_pem
            ).decode("ascii"),
            "MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID": key_id,
            "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON": json.dumps(
                {key_id: base64.b64encode(secrets.token_bytes(32)).decode("ascii")}
            ),
            "MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON": json.dumps(policy),
        }
    )
    return ProgrammeFixtureMaterial(
        request.run_id,
        web_port,
        secrets.token_urlsafe(64),
        secrets.token_urlsafe(32),
        configuration,
        json.dumps({key_id: base64.b64encode(private_pem).decode("ascii")}),
    )
