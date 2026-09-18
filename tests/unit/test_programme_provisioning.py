"""Database-free provisioning orchestration and source-boundary regression tests."""

import ast
import copy
import os
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest

from tests.rehearsals import programme_provisioning as provisioning
from tests.rehearsals import programme_runtime_environment as runtime
from tests.rehearsals.programme_database import (
    LABEL,
    OWNER_LABEL,
    POSTGRES_IMAGE,
    ProgrammeDatabaseLease,
)

RUN = "1234567890abcdef1234567890abcdef"
DATABASE = f"maru_programme_{RUN}"
LEASE = ProgrammeDatabaseLease(RUN, "a" * 64, "b" * 32, DATABASE, 55432, "A" * 43)
REQUEST = runtime.ProgrammeRehearsalRequest(RUN, 1800)


class ConnectionDouble:
    def __init__(self):
        self.statements = []
        self.identity = (DATABASE, "postgres", "postgres", 170011)
        self.roles = (False,)
        self.fail = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, query, **kwargs):
        rendered = query if isinstance(query, str) else query.as_string()
        self.statements.append((rendered, kwargs))
        if self.fail:
            raise self.fail
        if rendered.startswith("SELECT current_database()"):
            return SimpleNamespace(fetchone=lambda: self.identity)
        if rendered.startswith("SELECT EXISTS"):
            return SimpleNamespace(fetchone=lambda: self.roles)
        return SimpleNamespace(fetchone=lambda: None)


@pytest.fixture
def prepared(monkeypatch):
    connection = ConnectionDouble()
    connect = Mock(return_value=connection)
    monkeypatch.setattr(provisioning.psycopg, "connect", connect)
    request = Mock(return_value=REQUEST)
    monkeypatch.setattr(provisioning, "require_programme_rehearsal_request", request)
    inspection = {
        "id": LEASE.container_id,
        "name": f"/maru-programme-{RUN}",
        "labels": {LABEL: RUN, OWNER_LABEL: LEASE.owner_nonce},
        "image": POSTGRES_IMAGE,
        "ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]},
    }
    inspector = Mock(side_effect=lambda _name: copy.deepcopy(inspection))
    docker = Mock(return_value=SimpleNamespace(inspect=inspector))
    monkeypatch.setattr(provisioning, "_Docker", docker)
    child = Mock()
    monkeypatch.setattr(provisioning, "_child", child)
    monkeypatch.setattr(
        provisioning.secrets,
        "token_urlsafe",
        Mock(side_effect=["M" * 43, "R" * 43, "S" * 86]),
    )
    return SimpleNamespace(
        connection=connection,
        connect=connect,
        request=request,
        docker=docker,
        inspector=inspector,
        inspection=inspection,
        child=child,
    )


def test_exact_source_changes_only_five_database_references():
    source = provisioning.PROVISIONING_SOURCE.read_text(encoding="utf-8")
    rendered = provisioning.runtime_provisioning_sql(RUN)
    assert rendered.count(DATABASE) == 5
    assert rendered.replace(DATABASE, "maru") == source
    assert "BEGIN;" in rendered
    assert rendered.rstrip().endswith("COMMIT;")


@pytest.mark.parametrize("run_id", ["", "0" * 32, "A" * 32, RUN + "'", "other"])
def test_source_binding_rejects_noncanonical_database_identity(run_id):
    with pytest.raises(provisioning.ProgrammeProvisioningError, match="invalid_run"):
        provisioning.runtime_provisioning_sql(run_id)


@pytest.mark.parametrize("value", ["changed", OSError("private path"), UnicodeError()])
def test_changed_or_unavailable_source_is_never_executed(value, monkeypatch):
    reader = Mock()
    if isinstance(value, Exception):
        reader.side_effect = value
    else:
        reader.return_value = value
    monkeypatch.setattr(
        provisioning, "PROVISIONING_SOURCE", SimpleNamespace(read_text=reader)
    )
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="provisioning_source"
    ):
        provisioning.runtime_provisioning_sql(RUN)


def test_policy_fence_precedes_every_external_operation(prepared):
    prepared.request.side_effect = runtime.ProgrammeRehearsalEnvironmentError(
        "deferred"
    )
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError, match="deferred"):
        provisioning.provision_programme_runtime(LEASE)
    prepared.docker.assert_not_called()
    prepared.connect.assert_not_called()
    prepared.child.assert_not_called()


def test_real_login_planes_ordered_source_and_final_role_probe(prepared):
    result = provisioning.provision_programme_runtime(LEASE)
    assert (
        result.database_url
        == f"postgresql://maru_runtime:{'R' * 43}@127.0.0.1:55432/{DATABASE}"
    )
    assert "R" * 43 not in repr(result)
    assert prepared.connect.call_args.kwargs["user"] == "postgres"
    assert prepared.connect.call_args.kwargs["password"] == LEASE.admin_password
    assert prepared.connect.call_args.kwargs["connect_timeout"] == 5
    statements = [entry[0] for entry in prepared.connection.statements]
    assert (
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in statements[2]
    )
    assert statements[3] == f'ALTER DATABASE "{DATABASE}" OWNER TO maru_migration'
    assert statements[4] == "ALTER SCHEMA public OWNER TO maru_migration"
    assert statements[5] == provisioning.runtime_provisioning_sql(RUN)
    assert prepared.connection.statements[5][1] == {"prepare": False}
    assert statements[6] == f"ALTER ROLE maru_runtime PASSWORD '{'R' * 43}'"
    assert prepared.child.call_count == 2
    migration, probe = prepared.child.call_args_list
    assert migration.args[0] == ["-m", "django", "migrate", "--noinput"]
    assert "maru_migration:" in migration.args[1]["MARU_DATABASE_URL"]
    assert "M" * 43 not in repr(migration.args[0])
    assert probe.args[0] == ["-c", provisioning._PROBE]
    assert "maru_runtime:" in probe.args[1]["MARU_DATABASE_URL"]
    assert probe.kwargs["expected_output"] == "programme-runtime-role-verified"
    assert prepared.inspector.call_count == 4


def test_explicit_candidate_overlay_runs_after_current_migrations_before_acl(prepared):
    provisioning.provision_programme_runtime(LEASE, candidate_schema=True)
    current, candidate, probe = prepared.child.call_args_list
    assert "MARU_PROGRAMME_REHEARSAL_SCHEMA" not in current.args[1]
    assert candidate.args[0] == ["-m", "django", "migrate", "--noinput"]
    assert candidate.args[1]["DJANGO_SETTINGS_MODULE"].endswith(
        "programme_candidate_schema_settings"
    )
    assert candidate.args[1]["MARU_PROGRAMME_REHEARSAL_SCHEMA"] == "candidate-v1"
    assert (
        candidate.args[1]["MARU_DATABASE_URL"] == current.args[1]["MARU_DATABASE_URL"]
    )
    assert "MARU_PROGRAMME_REHEARSAL_SCHEMA" not in probe.args[1]
    assert prepared.inspector.call_count == 5


def test_candidate_migration_failure_never_grants_runtime_acl(prepared):
    prepared.child.side_effect = [
        None,
        provisioning.ProgrammeProvisioningError("overlay_failed"),
    ]
    with pytest.raises(provisioning.ProgrammeProvisioningError, match="overlay_failed"):
        provisioning.provision_programme_runtime(LEASE, candidate_schema=True)
    assert len(prepared.connection.statements) == 5


@pytest.mark.parametrize("value", [1, "candidate-v1", None])
def test_candidate_option_is_closed_boolean(value, prepared):
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="invalid_candidate_schema_option"
    ):
        provisioning.provision_programme_runtime(LEASE, candidate_schema=value)
    prepared.docker.assert_not_called()
    prepared.connect.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": "c" * 32},
        {"database_name": "existing"},
        {"port": True},
        {"port": 1},
        {"admin_password": "secret\n"},
        {"owner_nonce": None},
        {"owner_nonce": ""},
    ],
)
def test_invalid_lease_cannot_open_an_administrator_connection(changes, prepared):
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="invalid_owned_lease"
    ):
        provisioning.provision_programme_runtime(replace(LEASE, **changes))
    prepared.docker.assert_not_called()
    prepared.connect.assert_not_called()


def test_owned_container_port_must_still_match(prepared):
    prepared.inspection["ports"]["5432/tcp"][0]["HostPort"] = "55433"
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="owned_port_changed"
    ):
        provisioning.provision_programme_runtime(LEASE)
    prepared.connect.assert_not_called()


@pytest.mark.parametrize(
    "identity",
    [
        None,
        ("other", "postgres", "postgres", 170011),
        (DATABASE, "maru_migration", "postgres", 170011),
        (DATABASE, "postgres", "maru_runtime", 170011),
        (DATABASE, "postgres", "postgres", 160010),
    ],
)
def test_wrong_native_identity_stops_before_ddl(identity, prepared):
    prepared.connection.identity = identity
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="identity_mismatch"
    ):
        provisioning.provision_programme_runtime(LEASE)
    assert len(prepared.connection.statements) == 1
    prepared.child.assert_not_called()


def test_existing_roles_are_not_adopted_or_rewritten(prepared):
    prepared.connection.roles = (True,)
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="existing_provisioning_roles"
    ):
        provisioning.provision_programme_runtime(LEASE)
    assert len(prepared.connection.statements) == 2
    prepared.child.assert_not_called()


def test_database_failure_omits_driver_output_and_never_launches_migrations(prepared):
    prepared.connection.fail = psycopg.OperationalError(
        "private credential and endpoint"
    )
    with pytest.raises(provisioning.ProgrammeProvisioningError) as caught:
        provisioning.provision_programme_runtime(LEASE)
    assert str(caught.value) == "database_provisioning_failed"
    prepared.child.assert_not_called()


def test_migration_failure_never_applies_runtime_grants(prepared):
    prepared.child.side_effect = provisioning.ProgrammeProvisioningError(
        "migration failed"
    )
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="migration failed"
    ):
        provisioning.provision_programme_runtime(LEASE)
    assert len(prepared.connection.statements) == 5
    assert prepared.child.call_count == 1


def test_failed_real_runtime_probe_returns_no_endpoint(prepared):
    prepared.child.side_effect = [
        None,
        provisioning.ProgrammeProvisioningError("unsafe"),
    ]
    with pytest.raises(provisioning.ProgrammeProvisioningError, match="unsafe"):
        provisioning.provision_programme_runtime(LEASE)
    assert prepared.child.call_count == 2


@pytest.mark.parametrize(
    "passwords", [["A" * 43, "R" * 43], ["same" * 10, "R" * 43], ["M" * 43, "M" * 43]]
)
def test_credential_collision_or_bad_generator_cannot_connect(
    passwords, prepared, monkeypatch
):
    monkeypatch.setattr(
        provisioning.secrets, "token_urlsafe", Mock(side_effect=passwords)
    )
    with pytest.raises(
        provisioning.ProgrammeProvisioningError, match="credential_generation"
    ):
        provisioning.provision_programme_runtime(LEASE)
    prepared.connect.assert_not_called()


def test_child_environment_removes_ambient_targeting_secrets_and_weak_settings(
    monkeypatch,
):
    monkeypatch.setattr(
        provisioning,
        "os",
        SimpleNamespace(
            environ={
                "PATH": "safe-path",
                "SystemRoot": "windows",
                "PGOPTIONS": "unsafe",
                "MARU_DATABASE_URL": "private-existing-db",
                "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE": "false",
                "DJANGO_SETTINGS_MODULE": "maru.settings.test",
                "PYTHONPATH": "foreign",
                "AWS_SECRET_ACCESS_KEY": "private-provider-secret",
            },
            path=os.path,
            pathsep=os.pathsep,
        ),
    )
    child = provisioning._child_environment(
        LEASE, REQUEST, role="maru_runtime", password="R" * 43, secret_key="S" * 86
    )
    assert child["PATH"] == "safe-path"
    assert child["SystemRoot"] == "windows"
    assert "PGOPTIONS" not in child
    assert "AWS_SECRET_ACCESS_KEY" not in child
    assert child["MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE"] == "true"
    assert child["DJANGO_SETTINGS_MODULE"].endswith("programme_provisioning_settings")
    assert "private-existing-db" not in repr(child)
    assert "foreign" not in child["PYTHONPATH"]


@pytest.mark.parametrize(
    "failure", [OSError("secret"), subprocess.TimeoutExpired("secret", 1)]
)
def test_child_transport_failure_is_minimized(failure, monkeypatch):
    monkeypatch.setattr(provisioning.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(provisioning.ProgrammeProvisioningError) as caught:
        provisioning._child(["-c", provisioning._PROBE], {}, timeout=5)
    assert str(caught.value) == "provisioning_process_unavailable"


@pytest.mark.parametrize(
    ("returncode", "output"),
    [(1, "secret"), (0, "almost verified"), (0, "marker\nsecret")],
)
def test_child_failure_or_unexpected_probe_output_is_not_acceptance(
    returncode, output, monkeypatch
):
    monkeypatch.setattr(
        provisioning.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=returncode, stdout=output)),
    )
    with pytest.raises(provisioning.ProgrammeProvisioningError, match="process_failed"):
        provisioning._child(
            ["-c", provisioning._PROBE], {}, timeout=5, expected_output="marker"
        )


@pytest.mark.parametrize("role", ["maru_migration", "maru_runtime"])
def test_exact_child_environment_passes_configuration_fence(role, monkeypatch):
    environment = provisioning._child_environment(
        LEASE, REQUEST, role=role, password="R" * 43, secret_key="S" * 86
    )
    proxy = SimpleNamespace(environ=environment)
    monkeypatch.setattr(provisioning, "os", proxy)
    monkeypatch.setattr(runtime, "os", proxy)
    monkeypatch.setattr(
        runtime.ci_development_policy,
        "postgresql_policy_mode",
        Mock(return_value="required"),
    )
    provisioning.require_provisioning_process_environment()


@pytest.mark.parametrize(
    "changes",
    [
        {"MARU_PROGRAMME_REHEARSAL_PROCESS": "postgres"},
        {"PGOPTIONS": "unsafe"},
        {"MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE": "false"},
        {"MARU_SECRET_KEY": "short"},
        {
            "MARU_DATABASE_URL": "postgresql://maru_migration:secret@remote:5432/existing"
        },
        {
            "MARU_DATABASE_URL": (
                f"postgresql://maru_migration:{'M' * 43}@127.0.0.1:65536/{DATABASE}"
            )
        },
        {"MARU_RUNTIME_DATABASE_ROLE": "postgres"},
    ],
)
def test_unsafe_child_configuration_is_rejected(changes, monkeypatch):
    environment = (
        provisioning._child_environment(
            LEASE,
            REQUEST,
            role="maru_migration",
            password="M" * 43,
            secret_key="S" * 86,
        )
        | changes
    )
    proxy = SimpleNamespace(environ=environment)
    monkeypatch.setattr(provisioning, "os", proxy)
    monkeypatch.setattr(runtime, "os", proxy)
    monkeypatch.setattr(
        runtime.ci_development_policy,
        "postgresql_policy_mode",
        Mock(return_value="required"),
    )
    with pytest.raises(provisioning.ProgrammeProvisioningError):
        provisioning.require_provisioning_process_environment()


def test_settings_use_base_without_test_authority_or_guard_silencing():
    path = provisioning.ROOT / "tests/rehearsals/programme_provisioning_settings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert "maru.settings.base" in imports
    assert "maru.settings.test" not in imports
    assert "maru.settings.local" not in imports
    flags = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
    }
    assert flags == {
        "REQUIRE_EXACT_AUTHORITY_PROVENANCE": True,
        "REQUIRE_PRIVILEGED_STEP_UP": True,
        "DEBUG": False,
        "DEMO_PAYMENT_ADAPTER_ENABLED": False,
        "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    }
