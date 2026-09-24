"""Fault injection stays on the new synthetic clone and always repairs its ACL."""

import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest

from tests.rehearsals import programme_logical_restore as restore
from tests.rehearsals import programme_restore_readiness as faults
from tests.rehearsals.programme_runtime_environment import ProgrammeRuntimeEnvironment


@pytest.fixture
def fault_world(monkeypatch):
    runtime = ProgrammeRuntimeEnvironment(
        "b" * 32,
        "maru_programme_" + "b" * 32,
        51919,
        3600,
        "postgresql://maru_runtime:synthetic@127.0.0.1:51919/maru_programme_"
        + "b" * 32,
    )
    fixture = SimpleNamespace(
        deadline=100,
        _database_lease=SimpleNamespace(
            database_name="maru_programme_" + "a" * 32,
            port=51919,
            admin_password="synthetic-test-only",
        ),
    )
    calls = []
    probes = []
    options = {"fail_probe": None}

    class Admin:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query):
            text = str(query)
            calls.append(text)
            row = (
                (runtime.database_name, "postgres", "postgres", False)
                if "SELECT current_database" in text
                else (False,)
            )
            return SimpleNamespace(fetchone=lambda: row)

    def connect(**kwargs):
        assert kwargs["dbname"] == runtime.database_name
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["autocommit"] is True
        return Admin()

    def child(_args, _environment, *, timeout, expected_output):
        assert timeout == 7
        probes.append(expected_output)
        if options["fail_probe"] == len(probes):
            raise RuntimeError("synthetic_probe_failure")

    monkeypatch.setattr(faults.psycopg, "connect", connect)
    monkeypatch.setattr(faults, "_child", child)
    monkeypatch.setattr(faults, "remaining_lease", lambda _deadline: 7)
    monkeypatch.setattr(restore, "_docker_for_lease", lambda _lease: None)
    return SimpleNamespace(
        fixture=fixture, runtime=runtime, calls=calls, probes=probes, options=options
    )


def test_metadata_faults_each_require_denial_then_restored_readiness(fault_world):
    world = fault_world
    faults.verify_restored_readiness_faults(world.fixture, world.runtime, {})
    assert world.probes == [
        "programme-restored-runtime-ready",
        "programme-restored-runtime-unavailable",
        "programme-restored-runtime-ready",
        "programme-restored-runtime-unavailable",
        "programme-restored-runtime-ready",
    ]
    assert sum("GRANT CREATE" in query for query in world.calls) == 1
    assert sum("REVOKE CREATE" in query for query in world.calls) == 1
    assert sum("SECURITY DEFINER" in query for query in world.calls) == 1
    assert sum("SECURITY INVOKER" in query for query in world.calls) == 1


@pytest.mark.parametrize("failure_probe", [2, 4])
def test_failed_negative_probe_still_reverts_exact_injected_fault(
    fault_world, failure_probe
):
    world = fault_world
    world.options["fail_probe"] = failure_probe
    with pytest.raises(RuntimeError, match=r"^synthetic_probe_failure$"):
        faults.verify_restored_readiness_faults(world.fixture, world.runtime, {})
    expected = "REVOKE CREATE" if failure_probe == 2 else "SECURITY INVOKER"
    assert expected in world.calls[-1]


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": "a" * 32, "database_name": "maru_programme_" + "a" * 32},
        {"run_id": "not-a-uuid"},
        {"database_name": "unrelated_database"},
        {"port": 51920},
    ],
)
def test_metadata_faults_refuse_source_or_foreign_targets(fault_world, changes):
    world = fault_world
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError, match=r"^restore_fault_target_invalid$"
    ):
        faults.verify_restored_readiness_faults(
            world.fixture, replace(world.runtime, **changes), {}
        )
    assert not world.calls
    assert not world.probes


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "programme-restored-runtime-ready"),
        (
            "candidate_native_readiness_unavailable",
            "programme-restored-runtime-unavailable",
        ),
        ("candidate_system_check_failed", "programme-restored-runtime-unavailable"),
    ],
)
def test_probe_initializes_django_before_loading_model_dependent_checks(
    monkeypatch, capsys, failure, expected
):
    initialized = []

    class StartupError(RuntimeError):
        pass

    class CompatibilityError(RuntimeError):
        pass

    def build():
        assert initialized == [True]
        if failure == "candidate_system_check_failed":
            raise CompatibilityError(failure)
        if failure is not None:
            raise StartupError(failure)

    class CheckedModule(ModuleType):
        def __getattr__(self, name):
            if name == "__path__":
                raise AttributeError(name)
            assert initialized == [True], "Django must precede model-dependent imports"
            return {
                "ProgrammeStartupError": StartupError,
                "ProgrammeCompatibilityError": CompatibilityError,
                "build_candidate_application": build,
            }[name]

    monkeypatch.setitem(
        sys.modules, "django", SimpleNamespace(setup=lambda: initialized.append(True))
    )
    for name in (
        "tests.rehearsals.programme_runtime",
        "tests.rehearsals.programme_compatibility",
    ):
        monkeypatch.setitem(sys.modules, name, CheckedModule(name))
    exec(faults._PROBE, {})  # noqa: S102 -- fixed maintained source with inert imports.
    assert capsys.readouterr().out.strip() == expected
