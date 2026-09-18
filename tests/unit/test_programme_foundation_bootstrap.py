"""Stopped bootstrap guards and real-owner call order, without database evidence."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import django
import django.conf
import django.db
import pytest

from maru.authorization import activation
from maru.identity import (
    invitation_key_config,
    invitation_retention,
    invitation_token_keys,
)
from maru.identity.models import Account
from tests.rehearsals import programme_foundation_bootstrap as bootstrap
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"


@pytest.fixture
def guarded_environment(monkeypatch):
    request = Mock(return_value=SimpleNamespace(run_id=RUN))
    process = Mock()
    monkeypatch.setattr(bootstrap, "require_programme_rehearsal_request", request)
    monkeypatch.setattr(bootstrap, "require_provisioning_process_environment", process)
    values = {
        "DJANGO_SETTINGS_MODULE": "tests.rehearsals.programme_provisioning_settings",
        "MARU_PROGRAMME_REHEARSAL_PROCESS": "maru_migration",
        "MARU_PROGRAMME_REHEARSAL_BOOTSTRAP": bootstrap.BOOTSTRAP_VERSION,
        bootstrap.ADMIN_PASSWORD_ENV: "S" * 43,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(bootstrap.PRIVATE_KEYS_ENV, raising=False)
    return SimpleNamespace(request=request, process=process)


def test_policy_precedes_owner_environment_and_setup(guarded_environment, monkeypatch):
    guarded_environment.request.side_effect = ProgrammeRehearsalEnvironmentError(
        "deferred"
    )
    setup = Mock()
    monkeypatch.setattr(django, "setup", setup)
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        bootstrap.bootstrap_stopped_foundation()
    guarded_environment.process.assert_not_called()
    setup.assert_not_called()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DJANGO_SETTINGS_MODULE", "maru.settings.test"),
        ("MARU_PROGRAMME_REHEARSAL_PROCESS", "maru_runtime"),
        ("MARU_PROGRAMME_REHEARSAL_PROCESS", "postgres"),
        ("MARU_PROGRAMME_REHEARSAL_BOOTSTRAP", ""),
        (bootstrap.ADMIN_PASSWORD_ENV, ""),
        (bootstrap.ADMIN_PASSWORD_ENV, "private malformed credential"),
        (bootstrap.PRIVATE_KEYS_ENV, ""),
    ],
)
def test_environment_drift_never_reaches_django(
    guarded_environment, monkeypatch, name, value
):
    monkeypatch.setenv(name, value)
    setup = Mock()
    monkeypatch.setattr(django, "setup", setup)
    with pytest.raises(
        bootstrap.ProgrammeProvisioningError, match="environment_invalid"
    ):
        bootstrap.bootstrap_stopped_foundation()
    setup.assert_not_called()


@pytest.fixture
def owners(guarded_environment, monkeypatch):
    policy = bootstrap.synthetic_retention_policy(RUN) | {
        "approved_at": "2026-01-01T00:00:00Z"
    }
    settings = SimpleNamespace(
        SETTINGS_MODULE="tests.rehearsals.programme_provisioning_settings",
        REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
        REQUIRE_PRIVILEGED_STEP_UP=True,
        DEBUG=False,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        IDENTITY_EXPOSE_TEST_TOKENS=False,
        MARU_EXPOSE_TEST_CREDENTIAL_TOKENS=False,
        SILENCED_SYSTEM_CHECKS=[],
        MARU_PUBLIC_BASE_URL="https://127.0.0.1:55443",
        MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON=json.dumps(policy),
    )
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchone.side_effect = [
        (f"maru_programme_{RUN}", "maru_migration", "maru_migration", 170011),
        (True, False, False, False, False, False),
    ]
    connection = Mock(in_atomic_block=False)
    connection.get_autocommit.return_value = True
    connection.cursor.return_value = cursor
    monkeypatch.setattr(django, "setup", Mock())
    monkeypatch.setattr(django.conf, "settings", settings)
    monkeypatch.setattr(django.db, "connection", connection)
    ordered = Mock()
    mappings = (
        (invitation_key_config, "active_invitation_encryption_key", "public_key"),
        (invitation_token_keys, "invitation_token_keyring", "digest_key"),
        (invitation_retention, "configured_invitation_retention_policy", "policy"),
        (Account.objects, "create_superuser", "account"),
        (activation, "activate_authority_provenance", "activation"),
        (
            invitation_retention,
            "activate_configured_invitation_retention_policy",
            "retention",
        ),
        (invitation_retention, "invitation_retention_policy_control_is_ready", "ready"),
    )
    for module, name, alias in mappings:
        command = Mock()
        monkeypatch.setattr(module, name, command)
        ordered.attach_mock(command, alias)
    ordered.activation.return_value = SimpleNamespace(
        activated=True, production_status="ready", blocker_total=0
    )
    ordered.ready.return_value = True
    return SimpleNamespace(
        settings=settings,
        cursor=cursor,
        connection=connection,
        ordered=ordered,
        policy=policy,
    )


def test_fresh_stopped_fixture_uses_public_owners_in_order(owners):
    assert bootstrap.bootstrap_stopped_foundation() is None
    assert [call[0] for call in owners.ordered.mock_calls] == [
        "public_key",
        "digest_key",
        "policy",
        "account",
        "activation",
        "retention",
        "ready",
    ]
    assert owners.ordered.account.call_args.kwargs == {
        "email": f"programme-platform-{RUN}@example.invalid",
        "password": "S" * 43,
        "display_name": "Synthetic Programme platform administrator",
    }
    arguments = owners.ordered.activation.call_args.kwargs
    assert arguments["actor"] is owners.ordered.account.return_value
    assert arguments["acknowledge_processes_stopped"] is True
    assert arguments["source_channel"] == "programme_fixture"
    assert "S" * 43 not in str(arguments["reason"])
    assert owners.cursor.execute.call_count == 2


@pytest.mark.parametrize("defect", ["identity", "version", "populated", "schema"])
def test_unproven_native_boundary_never_calls_writers(defect, owners):
    identity = (f"maru_programme_{RUN}", "maru_migration", "maru_migration", 170011)
    fresh = (True, False, False, False, False, False)
    if defect == "identity":
        identity = ("foreign", *identity[1:])
    elif defect == "version":
        identity = (*identity[:3], 160000)
    elif defect == "populated":
        fresh = (True, True, False, False, False, False)
    else:
        fresh = (False, False, False, False, False, False)
    owners.cursor.fetchone.side_effect = [identity, fresh]
    with pytest.raises(bootstrap.ProgrammeProvisioningError):
        bootstrap.bootstrap_stopped_foundation()
    assert not owners.ordered.mock_calls


@pytest.mark.parametrize("defect", ["settings", "transaction", "policy", "keys"])
def test_configuration_failure_never_creates_an_account(defect, owners):
    if defect == "settings":
        owners.settings.REQUIRE_PRIVILEGED_STEP_UP = False
    elif defect == "transaction":
        owners.connection.in_atomic_block = True
    elif defect == "policy":
        owners.settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON = json.dumps(
            owners.policy | {"jurisdiction_code": "REAL"}
        )
    else:
        owners.ordered.public_key.side_effect = ValueError("configuration unavailable")
    with pytest.raises((bootstrap.ProgrammeProvisioningError, ValueError)):
        bootstrap.bootstrap_stopped_foundation()
    owners.ordered.account.assert_not_called()


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:55443",
        "https://foreign.invalid:55443",
        "https://127.0.0.1:1000",
        "https://127.0.0.1:99999",
        "https://127.0.0.1:55443/path",
    ],
)
def test_bootstrap_origin_must_be_exact_nonprivileged_loopback_https(origin, owners):
    owners.settings.MARU_PUBLIC_BASE_URL = origin
    with pytest.raises(bootstrap.ProgrammeProvisioningError, match="settings_invalid"):
        bootstrap.bootstrap_stopped_foundation()
    assert not owners.ordered.mock_calls
    owners.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    "defect", ["already_active", "blocker", "not_ready", "retention"]
)
def test_partial_owner_failure_is_never_reported_as_success(defect, owners):
    result = owners.ordered.activation.return_value
    if defect == "already_active":
        result.activated = False
    elif defect == "blocker":
        result.blocker_total = 1
    elif defect == "not_ready":
        result.production_status = "blocked"
    else:
        owners.ordered.ready.return_value = False
    with pytest.raises(bootstrap.ProgrammeProvisioningError):
        bootstrap.bootstrap_stopped_foundation()
    if defect != "retention":
        owners.ordered.retention.assert_not_called()
