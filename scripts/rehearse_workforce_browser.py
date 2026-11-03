"""Start a fresh restricted-runtime Workforce browser rehearsal, or inspect its end.

Only a bootstrap platform account is created. Every ordinary account and all
Workforce work are entered through the normal browser. Secrets and local mail
remain in an ignored private run directory; no real mail provider is contacted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg import sql
from scripts.try_maru import (
    LABEL,
    MAX_PORT,
    MIN_PORT,
    ROOT,
    Preview,
    child_environment,
    preflight,
)

IMAGE = (
    "postgres:17.11-alpine@sha256:"
    "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)
PLATFORM = "workforce-platform@example.invalid"
PRIVATE_KEY = "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON"


def _save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def _source() -> dict[str, object]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    command = ["git", "--work-tree=" + str(ROOT)]
    names = (
        subprocess.check_output(  # noqa: S603 -- fixed git command; no shell
            [*command, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            env=environment,
            timeout=30,
        )
        .decode("utf-8")
        .rstrip("\0")
        .split("\0")
    )
    files = {}
    for name in sorted(set(names)):
        path = ROOT / name
        payload = (
            str(path.readlink()).encode()
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else None
        )
        files[name] = (
            hashlib.sha256(payload).hexdigest() if payload is not None else "deleted"
        )
    head = (
        subprocess.check_output(  # noqa: S603 -- read-only repository identity
            [*command, "rev-parse", "HEAD"],
            cwd=ROOT,
            env=environment,
            timeout=30,
        )
        .decode("ascii")
        .strip()
    )
    return {
        "head": head,
        "files": files,
        "digest": hashlib.sha256(
            json.dumps(files, sort_keys=True).encode()
        ).hexdigest(),
    }


def _directory(value: Path, *, create: bool) -> Path:
    directory = value.resolve()
    if not directory.is_relative_to(ROOT / ".tools") or directory == ROOT / ".tools":
        raise RuntimeError(
            "Choose a new private run directory beneath this checkout's .tools."
        )
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    elif not directory.is_dir():
        raise RuntimeError("The existing rehearsal directory is unavailable.")
    return directory


def _keys(environment: dict[str, str]) -> str:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encode = lambda value: base64.b64encode(value).decode("ascii")  # noqa: E731
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_id = "workforce-rehearsal-v1"
    environment.update(
        MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID=key_id,
        MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64=encode(public_pem),
        MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID=key_id,
        MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON=json.dumps(
            {key_id: encode(secrets.token_bytes(32))}
        ),
        MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON=json.dumps(
            {
                "policy_id": "synthetic-workforce-rehearsal",
                "version": 1,
                "jurisdiction_code": "SYNTHETIC",
                "trigger": "terminal_transition",
                "period_days": 1,
                "action": "anonymize_abandoned_invitation_contact",
                "approved_by_reference": "synthetic-rehearsal-facilitator",
                "approved_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    return json.dumps({key_id: encode(private_pem)})


def _run(directory: Path, environment: dict[str, str], *arguments: str) -> None:
    with (directory / "process.private.log").open("a", encoding="utf-8") as log:
        result = subprocess.run(  # noqa: S603 -- argument arrays, owned environment
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(
            "A rehearsal subprocess failed; inspect process.private.log locally."
        )


def _inspect(
    directory: Path,
    environment: dict[str, str],
    *,
    edition: str = "",
    volunteer: str = "",
) -> None:
    arguments = [
        "-m",
        "scripts.inspect_workforce_rehearsal",
        "final" if edition else "baseline",
        "--confirm-dedicated-synthetic",
        "--platform-email",
        PLATFORM,
        "--output",
        str(directory / ("after.json" if edition else "before.json")),
    ]
    if edition:
        arguments += [
            "--edition",
            edition,
            "--volunteer-email",
            volunteer,
            "--baseline",
            str(directory / "before.json"),
        ]
    _run(directory, environment, *arguments)


def _provision(preview: Preview, directory: Path) -> str:
    environment = preview.environment
    admin_url = environment["MARU_DATABASE_URL"]
    port = urlsplit(admin_url).port
    migration_password, runtime_password, bootstrap_password = (
        secrets.token_urlsafe(32) for _ in range(3)
    )
    environment.update(
        PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "src"))),
        DJANGO_SETTINGS_MODULE="scripts.workforce_rehearsal_settings",
        MARU_WORKFORCE_REHEARSAL="owned-loopback",
        MARU_WORKFORCE_REHEARSAL_DIRECTORY=str(directory),
        MARU_PUBLIC_BASE_URL=f"http://127.0.0.1:{preview.port}",
        MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE="true",
        MARU_RUNTIME_DATABASE_ROLE="maru_runtime",
    )
    private_keys = _keys(environment)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            sql.SQL(
                "CREATE ROLE maru_migration LOGIN PASSWORD {} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(sql.Literal(migration_password))
        )
        admin.execute("ALTER DATABASE maru OWNER TO maru_migration")
        admin.execute("ALTER SCHEMA public OWNER TO maru_migration")
    environment["MARU_DATABASE_URL"] = (
        f"postgresql://maru_migration:{migration_password}@127.0.0.1:{port}/maru"
    )
    print("Applying real migrations with the migration owner...", flush=True)
    _run(
        directory,
        environment,
        str(ROOT / "src/manage.py"),
        "migrate",
        "--noinput",
        "--verbosity",
        "0",
        "--skip-checks",
    )
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            (
                ROOT
                / "docs/operations/postgresql-runtime-role-provisioning.sql.example"
            ).read_text(encoding="utf-8")
        )
        admin.execute(
            sql.SQL("ALTER ROLE maru_runtime PASSWORD {}").format(
                sql.Literal(runtime_password)
            )
        )
    _run(
        directory,
        {
            **environment,
            "MARU_WORKFORCE_REHEARSAL_PROCESS": "bootstrap",
            "MARU_WORKFORCE_BOOTSTRAP_PASSWORD": bootstrap_password,
        },
        "-m",
        "scripts.workforce_rehearsal_runtime",
    )
    environment["MARU_DATABASE_URL"] = (
        f"postgresql://maru_runtime:{runtime_password}@127.0.0.1:{port}/maru"
    )
    _save(
        directory / "bootstrap.private.json",
        {"email": PLATFORM, "password": bootstrap_password},
    )
    _save(
        directory / "runtime.private.json",
        {
            key: value
            for key, value in environment.items()
            if key.startswith(("MARU_", "DJANGO_")) or key == "PYTHONPATH"
        },
    )
    _run(directory, environment, str(ROOT / "src/manage.py"), "check")
    return private_keys


def _worker(directory: Path, environment: dict[str, str], private_keys: str) -> None:
    _run(
        directory,
        {
            **environment,
            PRIVATE_KEY: private_keys,
            "MARU_WORKFORCE_REHEARSAL_PROCESS": "worker",
        },
        "-m",
        "scripts.workforce_rehearsal_runtime",
    )


def _verify_resource(
    preview: Preview, environment: dict[str, str]
) -> dict[str, object]:
    info = json.loads(preview.docker_command("inspect", preview.container))[0]
    endpoint = urlsplit(environment["MARU_DATABASE_URL"])
    bindings = info.get("NetworkSettings", {}).get("Ports", {})
    expected = [{"HostIp": "127.0.0.1", "HostPort": str(endpoint.port)}]
    if not (
        info.get("Id") == preview.container
        and info.get("Name") == f"/maru-preview-{preview.token}"
        and info.get("Config", {}).get("Labels", {}).get(LABEL) == preview.token
        and info.get("Config", {}).get("Image") == IMAGE
        and info.get("State", {}).get("Running") is True
        and bindings == {"5432/tcp": expected}
        and endpoint.hostname == "127.0.0.1"
        and endpoint.username == "maru_runtime"
        and endpoint.path == "/maru"
    ):
        raise RuntimeError(
            "The exact owned database, image or loopback runtime endpoint changed."
        )
    return {
        "container": preview.container,
        "token": preview.token,
        "image": IMAGE,
        "image_id": info["Image"],
        "web_port": preview.port,
    }


def _ready(port: int) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/health/ready", timeout=30) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError("Restricted runtime readiness did not pass.")


def _start(args: argparse.Namespace) -> int:
    docker = preflight(args.port)
    preview = Preview(docker, args.port, image=IMAGE)
    if preview.docker_command("ps", "-q"):
        raise RuntimeError(
            "Finish the current container workload before this rehearsal; "
            "nothing was stopped."
        )
    if args.check:
        print("Prerequisites passed; no fixture was created.")
        return 0
    directory = _directory(args.directory, create=True)
    source = _source()
    _save(directory / "source-before.json", source)
    ready = False
    cleanup = False
    finished = False
    try:
        preview.start_database()
        private_keys = _provision(preview, directory)
        _save(
            directory / "resource.json", _verify_resource(preview, preview.environment)
        )
        _worker(directory, preview.environment, private_keys)
        _inspect(directory, preview.environment)
        if _source() != source:
            raise RuntimeError("Source changed while preparing the fixture.")
        # --insecure serves repository static assets with DEBUG=False on loopback.
        # It changes only staticfiles handling; all application guards stay active.
        with (directory / "web.private.log").open("a", encoding="utf-8") as web_log:
            preview.server = subprocess.Popen(  # noqa: S603 -- exact local development server
                [
                    sys.executable,
                    str(ROOT / "src/manage.py"),
                    "runserver",
                    f"127.0.0.1:{args.port}",
                    "--noreload",
                    "--insecure",
                ],
                cwd=ROOT,
                env=preview.environment,
                stdout=web_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            deadline = time.monotonic() + 60
            while True:
                try:
                    _ready(args.port)
                    break
                except OSError:
                    if (
                        preview.server.poll() is not None
                        or time.monotonic() >= deadline
                    ):
                        raise RuntimeError(
                            "The restricted web process did not become ready."
                        ) from None
                    time.sleep(0.5)
            ready = True
            _save(
                directory / "ready.json",
                {
                    "status": "ready",
                    "origin": f"http://127.0.0.1:{args.port}",
                    "source_digest": source["digest"],
                    "started_at": datetime.now(UTC).isoformat(),
                    "minutes": args.minutes,
                    "baseline": "before.json",
                },
            )
            print(
                f"Ready: http://127.0.0.1:{args.port}/admin/\n"
                f"Private bootstrap login: {directory / 'bootstrap.private.json'}\n"
                f"Private local letters: {directory / 'mail.private'}\n"
                "Stop: Ctrl+C, or create an empty 'stop' file in this run directory.\n"
                f"Automatic cleanup after {args.minutes} minutes.\n"
                "No ordinary accounts or Workforce work were prefilled.",
                flush=True,
            )
            deadline = time.monotonic() + args.minutes * 60
            while (
                not args.smoke
                and time.monotonic() < deadline
                and not (directory / "stop").exists()
            ):
                if preview.server.poll() is not None:
                    raise RuntimeError("The owned web process exited early.")
                _worker(directory, preview.environment, private_keys)
                time.sleep(5)
            finished = True
    finally:
        try:
            preview.close()
            cleanup = True
        finally:
            _save(directory / "source-after.json", _source())
            _save(
                directory / "completion.json",
                {
                    "status": "completed" if finished else "failed_or_interrupted",
                    "ready": ready,
                    "owned_cleanup": cleanup,
                    "source_unchanged": _source() == source,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "acceptance": (
                        "startup only; browser journey and final inspection "
                        "are separate"
                    ),
                },
            )
    return 0


def _final(args: argparse.Namespace) -> int:
    directory = _directory(args.directory, create=False)
    source = json.loads((directory / "source-before.json").read_text(encoding="utf-8"))
    if _source() != source:
        raise RuntimeError(
            "Source changed; do not combine this evidence with the original fixture."
        )
    resource = json.loads((directory / "resource.json").read_text(encoding="utf-8"))
    # Resolve the local daemon without requiring the deliberately occupied web port.
    docker = preflight(0)
    preview = Preview(docker, resource["web_port"], image=IMAGE)
    preview.container, preview.token = resource["container"], resource["token"]
    environment = child_environment()
    environment.update(
        json.loads((directory / "runtime.private.json").read_text(encoding="utf-8"))
    )
    if (
        environment.get("MARU_WORKFORCE_REHEARSAL_DIRECTORY") != str(directory)
        or PRIVATE_KEY in environment
    ):
        raise RuntimeError(
            "The private runtime configuration does not match this fixture."
        )
    _verify_resource(preview, environment)
    _inspect(
        directory,
        environment,
        edition=str(args.edition),
        volunteer=args.volunteer_email,
    )
    print(f"Final read-only inspection passed: {directory / 'after.json'}")
    return 0


def main() -> int:
    """Run a bounded local fixture or its read-only final check.

    Returns
    -------
    int
        Zero on success; one for a safely reported setup, worker or cleanup failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--directory", type=Path, required=True)
    start.add_argument("--port", type=int, default=8766)
    start.add_argument(
        "--minutes", type=int, choices=range(1, 241), default=120, metavar="MINUTES"
    )
    modes = start.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    final = commands.add_parser("inspect-final")
    final.add_argument("--directory", type=Path, required=True)
    final.add_argument("--edition", type=UUID, required=True)
    final.add_argument("--volunteer-email", default="workforce-casey@example.invalid")
    args = parser.parse_args()
    if args.command == "start" and not MIN_PORT <= args.port <= MAX_PORT:
        parser.error("--port must be between 1024 and 65535")
    try:
        return _start(args) if args.command == "start" else _final(args)
    except KeyboardInterrupt:
        print("Rehearsal interrupted; owned cleanup was attempted.")
        return 1
    except Exception as error:  # noqa: BLE001 -- never release DSNs, keys or private logs
        print(
            f"Rehearsal stopped ({type(error).__name__}); "
            "inspect the private run log locally. No acceptance is claimed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
