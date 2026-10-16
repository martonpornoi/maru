"""Provision the two-edition practice scenario within one owned local preview."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


class Preview(Protocol):
    """Minimum owned launcher context needed by the convention scenario.

    Attributes
    ----------
    environment : dict[str, str]
        Fresh scrubbed environment belonging to this disposable preview.
    """

    environment: dict[str, str]

    def manage(self, *arguments: str) -> None:
        """Run a bounded command on this preview only.

        Parameters
        ----------
        *arguments : str
            Explicit management command and its arguments.
        """
        ...


def _manage_json(preview: Preview, *arguments: str) -> dict[str, Any]:
    """Run a local command with captured output and bounded, non-secret failure.

    Parameters
    ----------
    preview : Preview
        Exact launcher-owned database and child environment.
    *arguments : str
        Explicit Django command arguments.

    Returns
    -------
    dict[str, Any]
        Command's JSON result; never account passwords.

    Raises
    ------
    RuntimeError
        If the command fails without releasing its private output.
    """
    result = subprocess.run(  # noqa: S603 -- same Python and repository manage.py
        [sys.executable, str(ROOT / "src/manage.py"), *arguments],
        cwd=ROOT,
        env=preview.environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    if result.returncode:
        # Only this bounded, credential-free error contract may reach the console.
        detail = re.search(
            r"Convention demo preparation failed "
            r"\(([A-Za-z]+; [A-Za-z_]+\.py:[0-9]+)\)",
            result.stderr,
        )
        category = detail.group(1) if detail else "command unavailable"
        raise RuntimeError(
            f"The {arguments[0]} {arguments[1]} phase failed ({category}); "
            "no preview was exposed."
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(  # noqa: TRY004 -- failed command protocol, caught by launcher
            "Convention preparation returned an invalid result."
        )
    return payload


def prepare_convention_preview(preview: Preview) -> None:
    """Migrate with its owner, activate exact lineage, then seed with the runtime login.

    Parameters
    ----------
    preview : Preview
        Fresh database created and owned by this one launcher invocation.

    Raises
    ------
    RuntimeError
        If provisioning fails. The enclosing launcher still removes only its resource.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from maru.demo.convention_plan import (  # noqa: PLC0415 -- dependency-free plan
        ACCOUNT_KEYS,
        PREPARATION_REASON,
        account_identity,
        current_anchor,
    )

    environment = preview.environment
    administrator_url = environment["MARU_DATABASE_URL"]
    endpoint = urlsplit(administrator_url)
    migration_password, runtime_password = (secrets.token_urlsafe(32) for _ in range(2))
    passwords = {key: secrets.token_urlsafe(18) for key in ACCOUNT_KEYS}
    environment.update(
        MARU_SYNTHETIC_CONVENTION_DEMO="true",
        MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE="true",
        MARU_RUNTIME_DATABASE_ROLE="maru_runtime",
        MARU_DEMO_PASSWORDS=json.dumps(passwords),
        MARU_DEMO_ANCHOR=current_anchor(datetime.now(UTC)).isoformat(),
    )
    # Identifiers are fixed. Psycopg quotes credentials; no shell receives them.
    try:
        with psycopg.connect(administrator_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL(
                    "CREATE ROLE maru_migration LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Literal(migration_password))
            )
            admin.execute("ALTER DATABASE maru OWNER TO maru_migration")
            admin.execute("ALTER SCHEMA public OWNER TO maru_migration")
        environment["MARU_DATABASE_URL"] = (
            f"postgresql://maru_migration:{migration_password}@127.0.0.1:{endpoint.port}/maru"
        )
        # Before the runtime login exists migration checks correctly fail closed.
        preview.manage("migrate", "--noinput", "--verbosity", "0", "--skip-checks")
        with psycopg.connect(administrator_url, autocommit=True) as admin:
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
    except psycopg.Error as error:
        raise RuntimeError(
            "Local database role provisioning failed; no preview was exposed."
        ) from error

    _manage_json(preview, "prepare_convention_demo", "accounts")
    # This maintenance command owns its transaction while no web/worker process runs.
    preview.manage(
        "activate_authority_provenance",
        "--actor",
        account_identity("platform")[1],
        "--reason",
        PREPARATION_REASON,
        "--acknowledge-processes-stopped",
    )
    environment["MARU_DATABASE_URL"] = (
        f"postgresql://maru_runtime:{runtime_password}@127.0.0.1:{endpoint.port}/maru"
    )
    preview.manage("check")
    print("Preparing ongoing and future MaruCon practice work...", flush=True)
    manifest = _manage_json(preview, "prepare_convention_demo", "content")
    environment["MARU_DEMO_MANIFEST"] = json.dumps(manifest)
