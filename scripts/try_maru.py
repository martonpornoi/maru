"""Run a disposable, loopback-only Maru demonstration with owned cleanup.

This is a development convenience, not restricted-runtime acceptance or CI.
The existing demo command supplies only fictional educational data.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:17-alpine"
LABEL = "org.maru.local-preview"
MIN_PORT = 1024
MAX_PORT = 65535


def child_environment() -> dict[str, str]:
    """Remove inherited application and database configuration.

    Returns
    -------
    dict[str, str]
        Process environment with only local Maru settings and a fresh secret.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("MARU_", "DJANGO_", "PG", "POSTGRES_"))
        and key.upper() not in {"DATABASE_URL", "PYTHONPATH", "PYTHONHOME"}
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="maru.settings.local",
        PYTHONPATH=str(ROOT / "src"),
        PYTHONUNBUFFERED="1",
        MARU_SECRET_KEY=secrets.token_urlsafe(48),
    )
    return environment


def preflight(port: int) -> str:
    """Check prerequisites before allocating disposable resources.

    Parameters
    ----------
    port : int
        Loopback port reserved for the development web server.

    Returns
    -------
    str
        Resolved Docker executable path.

    Raises
    ------
    RuntimeError
        Python, dependencies, Docker, or the requested web port is unavailable.
    """
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        raise RuntimeError("Use Python 3.12-3.14 through uv run --locked.")
    if any(importlib.util.find_spec(name) is None for name in ("django", "psycopg")):
        raise RuntimeError("Install dependencies with uv sync --locked --all-groups.")
    docker = shutil.which("docker.exe" if os.name == "nt" else "docker")
    if docker is None:
        raise RuntimeError("Install Docker and start its engine before trying Maru.")
    # A remote Docker context would create resources on someone else's host.
    endpoint = os.environ.get("DOCKER_HOST", "")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        context = subprocess.run(  # noqa: S603 -- read-only Docker context lookup
            [docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        endpoint = context.stdout.strip()
    if not endpoint.startswith(("npipe://", "unix://")):
        raise RuntimeError(
            "Select a local Docker context (Unix socket or Windows named pipe)."
        )
    subprocess.run(  # noqa: S603 -- resolved Docker executable, fixed arguments
        [docker, "info", "--format", "{{.ServerVersion}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise RuntimeError(
            f"Port {port} is unavailable. Choose --port <free-port>."
        ) from error
    return docker


class Preview:
    """Own exactly one disposable database and one foreground server process."""

    def __init__(self, docker: str, port: int) -> None:
        """Initialize ownership without starting any process.

        Parameters
        ----------
        docker : str
            Resolved Docker executable returned by preflight.
        port : int
            Loopback web port selected by the caller.
        """
        self.docker = docker
        self.port = port
        self.token = secrets.token_hex(12)
        self.container = ""
        self.server: subprocess.Popen[str] | None = None
        self.environment = child_environment()

    def docker_command(self, *arguments: str) -> str:
        """Run a bounded Docker operation without exposing container secrets.

        Parameters
        ----------
        *arguments : str
            Individually passed Docker arguments; no shell evaluation occurs.

        Returns
        -------
        str
            Captured standard output with surrounding whitespace removed.
        """
        result = subprocess.run(  # noqa: S603 -- fixed executable; no shell
            [self.docker, *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=self.environment,
        )
        return result.stdout.strip()

    def start_database(self) -> None:
        """Create a new database on a randomly allocated loopback port.

        Raises
        ------
        RuntimeError
            PostgreSQL does not become ready within sixty seconds.
        """
        self.environment["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
        self.container = f"maru-preview-{self.token}"
        self.container = self.docker_command(
            "create",
            "--name",
            f"maru-preview-{self.token}",
            "--label",
            f"{LABEL}={self.token}",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            "POSTGRES_USER=maru",
            "--env",
            "POSTGRES_DB=maru",
            IMAGE,
        )
        print(f"Disposable database: {self.container}", flush=True)
        self.docker_command("start", self.container)
        deadline = time.monotonic() + 60
        while True:
            try:
                self.docker_command("exec", self.container, "pg_isready", "-U", "maru")
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "PostgreSQL did not become ready within 60s."
                    ) from None
                time.sleep(0.5)
        bindings = json.loads(
            self.docker_command(
                "inspect",
                "--format",
                "{{json .NetworkSettings.Ports}}",
                self.container,
            )
        )
        port = int(bindings["5432/tcp"][0]["HostPort"])
        password = self.environment.pop("POSTGRES_PASSWORD")
        self.environment["MARU_DATABASE_URL"] = (
            f"postgresql://maru:{password}@127.0.0.1:{port}/maru"
        )

    def manage(self, *arguments: str) -> None:
        """Run a normal Django command against only this preview database.

        Parameters
        ----------
        *arguments : str
            Management command and its explicit arguments.
        """
        started = time.monotonic()
        print(f"Starting {arguments[0]}...", flush=True)
        subprocess.run(  # noqa: S603 -- same Python, checked-in manage.py
            [sys.executable, str(ROOT / "src/manage.py"), *arguments],
            cwd=ROOT,
            env=self.environment,
            check=True,
            timeout=900,
            stdout=subprocess.DEVNULL if arguments[0] == "seed_demo_data" else None,
        )
        print(f"{arguments[0]}: {time.monotonic() - started:.1f}s", flush=True)

    def start_server(self) -> None:
        """Start the normal development server and verify its login page.

        Raises
        ------
        RuntimeError
            The server exits or does not present its login form within 45 seconds.
        """
        self.server = subprocess.Popen(  # noqa: S603 -- local Django, no shell/reloader
            [
                sys.executable,
                str(ROOT / "src/manage.py"),
                "runserver",
                f"127.0.0.1:{self.port}",
                "--noreload",
            ],
            cwd=ROOT,
            env=self.environment,
            text=True,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and self.server.poll() is None:
            try:
                with opener.open(
                    f"http://127.0.0.1:{self.port}/admin/login/", timeout=2
                ) as response:
                    page = response.read().decode()
                    if (
                        'name="csrfmiddlewaretoken"' in page
                        and 'name="password"' in page
                    ):
                        return
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.25)
        raise RuntimeError(
            "The local server did not present its login form within 45s."
        )

    def close(self) -> None:
        """Stop the child and remove only the database carrying this run's label.

        Raises
        ------
        RuntimeError
            The container ownership label no longer matches; nothing is removed.
        """
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=10)
        if self.container:
            actual = self.docker_command(
                "inspect",
                "--format",
                f'{{{{index .Config.Labels "{LABEL}"}}}}',
                self.container,
            )
            if actual != self.token:
                raise RuntimeError("Database ownership mismatch; refusing cleanup.")
            self.docker_command("rm", "--force", "--volumes", self.container)
            print(
                "Disposable database removed. Other fixtures were not touched.",
                flush=True,
            )
            self.container = ""


def main() -> int:
    """Start the demo or run prerequisite checks without creating resources.

    Returns
    -------
    int
        Zero for success or a normal interruption, one for setup/cleanup failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, metavar="PORT")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check", action="store_true", help="Check prerequisites only; create nothing."
    )
    modes.add_argument(
        "--smoke",
        action="store_true",
        help="Start, check the login form, then clean up.",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=60,
        choices=range(1, 241),
        metavar="MINUTES",
        help="Automatically clean up after this many browser minutes (default: 60).",
    )
    args = parser.parse_args()
    if not MIN_PORT <= args.port <= MAX_PORT:
        parser.error("--port must be between 1024 and 65535")
    preview = None
    result = 0
    try:
        started = time.monotonic()
        docker = preflight(args.port)
        print(
            "Prerequisites passed (Python, dependencies, Docker, loopback port).",
            flush=True,
        )
        if args.check:
            return 0
        preview = Preview(docker, args.port)
        preview.start_database()
        preview.manage("migrate", "--noinput", "--verbosity", "0")
        preview.manage("check")
        preview.manage("seed_demo_data")
        preview.start_server()
        # Import the existing public fixture credential, not a second password source.
        sys.path.insert(0, str(ROOT / "src"))
        from maru.demo.constants import DEMO_ACCOUNT_PASSWORD  # noqa: PLC0415

        print(
            f"\nReady in {time.monotonic() - started:.1f}s: http://127.0.0.1:{args.port}/admin/\n"
            f"Email: demo.admin@maru.invalid\nPassword: {DEMO_ACCOUNT_PASSWORD}\n"
            "Fictional educational data; not all modules are activated.\n"
            "This is not restricted-runtime acceptance or certification.\n"
            "Ctrl+C stops the server and deletes this disposable database.\n"
            f"Automatic cleanup after {args.minutes} browser minutes.\n",
            flush=True,
        )
        if not args.smoke and preview.server is not None:
            try:
                result = preview.server.wait(timeout=args.minutes * 60)
            except subprocess.TimeoutExpired:
                print("Preview time expired; cleaning up.", flush=True)
    except KeyboardInterrupt:
        print("\nStopping preview...", flush=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        # Exception strings can contain a database URL or a subprocess environment.
        print(
            f"Preview failed ({type(error).__name__}). "
            "Check the last startup phase; run --check first.",
            file=sys.stderr,
        )
        result = 1
    finally:
        if preview is not None:
            try:
                preview.close()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                print(
                    f"Cleanup failed. Inspect owned database {preview.container} "
                    f"with label {LABEL}={preview.token}; "
                    "never prune other fixtures.",
                    file=sys.stderr,
                )
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
