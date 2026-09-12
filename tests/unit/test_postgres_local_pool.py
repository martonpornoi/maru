"""Fresh database ownership, bounded concurrency, cleanup and timing failures."""

import json
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from scripts import run_postgres_pool as pool


@pytest.mark.parametrize("returncode", [0, 1])
def test_one_shard_uses_exact_manifest_isolated_database_and_cleans_only_its_id(
    monkeypatch, tmp_path, returncode
):
    for directory in ("reports", "logs", "coverage-parts"):
        (tmp_path / directory).mkdir()
    calls = []
    container_id = "a" * 64

    def docker(*args):
        calls.append(args)
        return (
            container_id
            if args[0] == "run"
            else "127.0.0.1:54321"
            if args[0] == "port"
            else ""
        )

    monkeypatch.setattr(pool, "_docker", docker)
    launched = []

    def launch(arguments, **kwargs):
        launched.append((arguments, kwargs))
        return SimpleNamespace(poll=lambda: returncode, returncode=returncode)

    monkeypatch.setattr(pool.subprocess, "Popen", launch)
    clock = iter((0, 1, 2))
    monkeypatch.setattr(pool.time, "monotonic", lambda: next(clock))
    plan = {"history": "all", "base": "b" * 40, "fingerprint": "c" * 64}
    result = pool._run_shard(
        15, plan, tmp_path / "plan.json", tmp_path, threading.Event()
    )
    assert result["status"] == ("success" if returncode == 0 else "failed")
    assert result["container_removed"]
    assert calls[-1] == ("rm", "--force", container_id)
    assert "127.0.0.1::5432" in calls[0]
    assert "type=tmpfs,destination=/var/lib/postgresql/data" in calls[0]
    arguments, kwargs = launched[0]
    assert arguments[arguments.index("--expected-plan") + 1] == "c" * 64
    assert arguments[arguments.index("--shard-index") + 1] == "15"
    assert kwargs["env"]["MARU_DATABASE_URL"].endswith(":54321/maru")
    assert kwargs["env"]["TEMP"].endswith("integration-15")
    assert "-k" not in arguments
    assert "-n" not in arguments
    assert json.loads((tmp_path / "reports/pool-result-15.json").read_text()) == result


@pytest.mark.parametrize("unresponsive", [False, True])
def test_deadline_stops_exact_test_process_before_hosted_limit(
    monkeypatch, unresponsive
):
    actions = []

    def wait(timeout):
        actions.append("wait")
        if unresponsive and "kill" not in actions:
            raise subprocess.TimeoutExpired("synthetic", timeout)

    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: actions.append("terminate"),
        kill=lambda: actions.append("kill"),
        wait=wait,
    )
    monkeypatch.setattr(pool.time, "monotonic", lambda: pool.LOCAL_TEST_LIMIT + 1)
    with pytest.raises(RuntimeError, match="headroom"):
        pool._wait_for_test(process, 0, threading.Event())
    assert actions[0] == "terminate"
    assert ("kill" in actions) is unresponsive


@pytest.mark.parametrize("failure", [False, True])
def test_pool_caps_parallelism_executes_complete_manifest_or_fails(
    monkeypatch, tmp_path, failure
):
    monkeypatch.setattr(pool, "ROOT", tmp_path)
    output = tmp_path / "output"
    manifest = tmp_path / "plan.json"
    manifest.write_text(
        json.dumps(
            {
                "shards": [[str(i)] for i in range(17)],
                "history": "all",
                "base": None,
                "fingerprint": "a" * 64,
            }
        )
    )
    monkeypatch.setattr(
        pool.sys,
        "argv",
        ["pool", "--plan", str(manifest), "--output", str(output), "--workers", "3"],
    )
    validations = []
    monkeypatch.setattr(
        pool.subprocess, "run", lambda args, **_kwargs: validations.append(args)
    )
    lock = threading.Lock()
    active = 0
    peak = 0
    seen = []

    def worker(index, plan, manifest, output, stop):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            seen.append(index)
        time.sleep(0.005)
        with lock:
            active -= 1
        return {
            "shard": index,
            "status": "failed" if failure and index == 1 else "success",
        }

    monkeypatch.setattr(pool, "_run_shard", worker)
    assert pool.main() == (1 if failure else 0)
    assert 1 <= peak <= 3
    assert len(seen) == len(set(seen))
    assert "--plan-only" in validations[0]
    assert "--plan-file" in validations[0]
    if not failure:
        assert sorted(seen) == list(range(1, 18))
    result = json.loads((output / "pool-result.json").read_text())
    assert result["expected_shards"] == 17
    assert result["plan_fingerprint"] == "a" * 64


def test_missing_docker_fails_without_launching_shell(monkeypatch):
    monkeypatch.setattr(pool.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="unavailable"):
        pool._docker("info")


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_database_startup_failure_retains_result_and_attempts_exact_cleanup(
    monkeypatch, tmp_path, cleanup_failure
):
    (tmp_path / "reports").mkdir()
    calls = []
    container_id = "d" * 64

    def docker(*args):
        calls.append(args)
        if args[0] == "run":
            return container_id
        if cleanup_failure:
            raise OSError("synthetic cleanup failure")
        return ""

    def unavailable(*_args):
        raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(pool, "_docker", docker)
    monkeypatch.setattr(pool, "_database_port", unavailable)
    result = pool._run_shard(1, {}, tmp_path / "plan.json", tmp_path, threading.Event())
    assert result["status"] == "failed"
    assert result["container_removed"] is not cleanup_failure
    assert calls[-1] == ("rm", "--force", container_id)
    assert (
        "cleanup" in result["error"]
        if cleanup_failure
        else "startup" in result["error"]
    )
    assert json.loads((tmp_path / "reports/pool-result-1.json").read_text()) == result
