"""Run a frozen PostgreSQL plan in bounded fresh local database workers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from uuid import uuid4

from scripts.ci_test_budget import (
    MAX_WORKERS,
    MEASURED_CEILING_SECONDS,
    OVERHEAD_SECONDS,
    SLOWDOWN_FACTOR,
    measured_headroom,
)
from scripts.ci_test_policy import ROOT

POSTGRES_IMAGE = (
    "postgres:17.11-alpine@sha256:"
    "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)
LOCAL_TEST_LIMIT = (MEASURED_CEILING_SECONDS - OVERHEAD_SECONDS) / SLOWDOWN_FACTOR


def _docker(*args: str) -> str:
    executable = shutil.which("docker.exe" if sys.platform == "win32" else "docker")
    if executable is None:
        raise RuntimeError("Docker is unavailable")
    return subprocess.run(  # noqa: S603 - resolved local tool, closed task-owned arguments
        [executable, *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def _database_port(container_id: str, stop: threading.Event) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise RuntimeError("Docker did not return an exact disposable container ID")
    for _attempt in range(90):
        if stop.is_set():
            raise RuntimeError("local pool interrupted")
        try:
            _docker("exec", container_id, "pg_isready", "-U", "maru", "-d", "maru")
            break
        except subprocess.CalledProcessError:
            time.sleep(1)
    else:
        raise RuntimeError("isolated PostgreSQL did not become ready")
    port = _docker("port", container_id, "5432/tcp").rsplit(":", 1)[-1]
    if not port.isdigit():
        raise RuntimeError("invalid loopback database port")
    return port


def _wait_for_test(
    process: subprocess.Popen[bytes], started: float, stop: threading.Event
) -> None:
    while process.poll() is None:
        if stop.is_set() or time.monotonic() - started > LOCAL_TEST_LIMIT:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
            raise RuntimeError("local timing headroom exhausted or pool interrupted")
        time.sleep(1)


def _test_arguments(index: int, plan: dict, manifest: Path, output: Path) -> list[str]:
    arguments = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "-m",
        "scripts.run_postgres_acceptance",
        "--history",
        plan["history"],
        "--plan-file",
        str(manifest),
        "--expected-plan",
        plan["fingerprint"],
        "--shard-index",
        str(index),
        "--evidence",
        str(output / "reports" / f"selection-{index}.json"),
    ]
    if plan["base"]:
        arguments.extend(["--base", plan["base"]])
    arguments.extend(
        [
            "--",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={output / 'reports' / f'integration-{index}.xml'}",
            "--durations=25",
        ]
    )
    return arguments


def _run_shard(
    index: int, plan: dict, manifest: Path, output: Path, stop: threading.Event
) -> dict:
    name = f"integration-{index}"
    container_id = None
    process = None
    result = {
        "shard": index,
        "status": "failed",
        "headroom": False,
        "container_removed": False,
    }
    started = time.monotonic()
    try:
        container_id = _docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            f"maru-cert-{name}-{uuid4().hex[:12]}",
            "--env",
            "POSTGRES_DB=maru",
            "--env",
            "POSTGRES_USER=maru",
            "--env",
            "POSTGRES_PASSWORD=maru",
            "--publish",
            "127.0.0.1::5432",
            "--mount",
            "type=tmpfs,destination=/var/lib/postgresql/data",
            POSTGRES_IMAGE,
        )
        resource_path = output / "reports" / f"pool-resource-{index}.json"
        with resource_path.open("x", encoding="utf-8") as resource:
            resource.write(json.dumps({"shard": index, "container_id": container_id}))
        port = _database_port(container_id, stop)
        temporary = output / "tmp" / name
        temporary.mkdir(parents=True, exist_ok=False)
        environment = {
            **os.environ,
            "MARU_DATABASE_URL": f"postgresql://maru:maru@127.0.0.1:{port}/maru",
            "COVERAGE_FILE": str(output / "coverage-parts" / f".coverage.{name}"),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "TMPDIR": str(temporary),
        }
        arguments = _test_arguments(index, plan, manifest, output)
        with (
            (output / "logs" / f"{name}.stdout.log").open(
                "x", encoding="utf-8"
            ) as stdout,
            (output / "logs" / f"{name}.stderr.log").open(
                "x", encoding="utf-8"
            ) as stderr,
        ):
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and validated manifest
                arguments, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr
            )
            _wait_for_test(process, started, stop)
        elapsed = time.monotonic() - started
        result.update(
            returncode=process.returncode,
            elapsed_seconds=round(elapsed, 3),
            headroom=measured_headroom(elapsed),
        )
        if process.returncode == 0 and result["headroom"]:
            result["status"] = "success"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        if container_id is not None and re.fullmatch(r"[0-9a-f]{64}", container_id):
            try:
                _docker("rm", "--force", container_id)
                result["container_removed"] = True
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                result.update(
                    status="failed", error=f"container cleanup failed: {error}"
                )
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # Cleanup time also belongs in the final measured headroom check.
        result["headroom"] = measured_headroom(result["elapsed_seconds"])
        if not result["headroom"]:
            result["status"] = "failed"
        (output / "reports" / f"pool-result-{index}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return result


def main() -> int:
    """Execute every frozen shard once, retaining results and verified cleanup.

    Returns
    -------
    int
        Zero only when all planned jobs pass with measured timing headroom.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error("workers must remain between one and eight")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        parser.error("pool output must remain below the repository")
    manifest = args.plan.resolve()
    plan = json.loads(manifest.read_text(encoding="utf-8-sig"))
    # The runner recomputes the complete policy, source and budget before any DB.
    validation = [
        sys.executable,
        "-m",
        "scripts.run_postgres_acceptance",
        "--history",
        plan["history"],
        "--plan-file",
        str(manifest),
        "--plan-only",
    ]
    if plan["base"]:
        validation.extend(["--base", plan["base"]])
    subprocess.run(validation, cwd=ROOT, check=True)  # noqa: S603 - same fixed interpreter and validator
    for directory in ("reports", "logs", "coverage-parts"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    results = []
    pending = iter(range(1, len(plan["shards"]) + 1))
    active: dict[Future, int] = {}
    executor = ThreadPoolExecutor(max_workers=args.workers)
    try:
        for _worker in range(min(args.workers, len(plan["shards"]))):
            index = next(pending)
            active[executor.submit(_run_shard, index, plan, manifest, output, stop)] = (
                index
            )
        while active:
            if (output / "cancel-pool").exists():
                stop.set()
            completed, _running = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in completed:
                active.pop(future)
                result = future.result()
                results.append(result)
                print(json.dumps(result, sort_keys=True), flush=True)
                if result["status"] != "success":
                    stop.set()
                if not stop.is_set():
                    index = next(pending, None)
                    if index is not None:
                        active[
                            executor.submit(
                                _run_shard, index, plan, manifest, output, stop
                            )
                        ] = index
    finally:
        stop.set()
        executor.shutdown(wait=True, cancel_futures=True)
        summary = {
            "plan_fingerprint": plan["fingerprint"],
            "expected_shards": len(plan["shards"]),
            "workers": args.workers,
            "results": sorted(results, key=lambda row: row["shard"]),
        }
        (output / "pool-result.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    return (
        0
        if len(results) == len(plan["shards"])
        and all(row["status"] == "success" for row in results)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
