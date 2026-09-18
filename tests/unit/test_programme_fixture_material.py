"""Actual ephemeral key separation and database-free bootstrap orchestration."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import override_settings

from maru.identity.invitation_key_config import (
    active_invitation_encryption_key,
    worker_invitation_private_keyring,
)
from maru.identity.invitation_token_keys import invitation_token_keyring
from tests.rehearsals import programme_fixture_material as material
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"


@pytest.fixture
def generated(monkeypatch):
    monkeypatch.setattr(
        material,
        "require_programme_rehearsal_request",
        Mock(return_value=SimpleNamespace(run_id=RUN)),
    )
    return material.generate_fixture_material(web_port=55443)


def test_real_key_parsers_accept_generated_material_without_private_key_in_web(
    generated,
):
    configuration = dict(generated.runtime_configuration)
    with override_settings(**configuration):
        public = active_invitation_encryption_key()
        private = worker_invitation_private_keyring(generated.worker_environment())
        assert private.matches(public)
        assert invitation_token_keyring().active_key_id == f"programme-{RUN}"
    assert material.PRIVATE_KEYS_ENV not in configuration
    assert material.PRIVATE_KEYS_ENV not in generated.owner_environment()
    assert material.ADMIN_PASSWORD_ENV not in configuration
    assert material.ADMIN_PASSWORD_ENV not in generated.worker_environment()
    assert configuration["MARU_PUBLIC_BASE_URL"] == "https://127.0.0.1:55443"
    assert generated.owner_environment()[material.ADMIN_PASSWORD_ENV] == (
        generated.administrator_password
    )
    assert generated.secret_key != generated.administrator_password
    assert len(generated.secret_key) >= 50
    assert len(generated.administrator_password) == 43
    assert generated.secret_key not in repr(generated)
    assert generated.administrator_password not in repr(generated)
    assert generated.invitation_private_keys not in repr(generated)
    with pytest.raises(TypeError):
        generated.runtime_configuration["MARU_PUBLIC_BASE_URL"] = (
            "https://foreign.invalid"
        )


def test_fixture_policy_is_explicitly_fictional_and_does_not_leak_mutable_state(
    generated,
):
    key = "MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON"
    policy = json.loads(generated.runtime_configuration[key])
    assert {name: value for name, value in policy.items() if name != "approved_at"} == (
        material.synthetic_retention_policy(RUN)
    )
    assert policy["jurisdiction_code"] == "SYNTHETIC"
    assert policy["approved_by_reference"] == "isolated-fixture-only"
    owner_environment = generated.owner_environment()
    owner_environment[key] = "changed"
    assert generated.owner_environment()[key] != "changed"


@pytest.mark.parametrize("port", [True, "55443", 1023, 65536, None])
def test_port_validation_precedes_key_generation(port, monkeypatch):
    monkeypatch.setattr(material, "require_programme_rehearsal_request", Mock())
    generator = Mock()
    monkeypatch.setattr(material.rsa, "generate_private_key", generator)
    with pytest.raises(
        ProgrammeRehearsalEnvironmentError, match="invalid_fixture_web_port"
    ):
        material.generate_fixture_material(web_port=port)
    generator.assert_not_called()


def test_deferred_policy_precedes_all_key_or_secret_generation(monkeypatch):
    monkeypatch.setattr(
        material,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    key = Mock()
    token = Mock()
    monkeypatch.setattr(material.rsa, "generate_private_key", key)
    monkeypatch.setattr(material.secrets, "token_bytes", token)
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="postgresql_deferred"):
        material.generate_fixture_material(web_port=55443)
    key.assert_not_called()
    token.assert_not_called()
