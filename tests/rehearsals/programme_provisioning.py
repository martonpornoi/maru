"""Prepare genuine migration/runtime planes inside an owned rehearsal database.

Native execution remains fenced by tracked policy. This installs the current
schema and runtime ACLs, not the Programme candidate or any domain records.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from tests.rehearsals.programme_database import (
    ProgrammeDatabaseLease,
    _Docker,
    _owned,
    _port,
)
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRuntimeEnvironment,
    require_programme_rehearsal_request,
    require_programme_runtime_environment,
)

ROOT = Path(__file__).resolve().parents[2]
PROVISIONING_SOURCE = (
    ROOT / "docs/operations/postgresql-runtime-role-provisioning.sql.example"
)
PROVISIONING_SHA256 = "9a7ee52f30eb2dd071e548676999934a10faf296280d4a83b5a8cbbcdec15c17"
_PASSWORD = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_PROCESS_ENVIRONMENT = frozenset(
    {"systemroot", "windir", "comspec", "path", "pathext", "temp", "tmp", "home"}
)
_PROBE = """
import django
django.setup()
from maru.authorization.database_role_safety import probe_runtime_database_role_safety
result = probe_runtime_database_role_safety(role_name="maru_runtime")
if not result.current_session_is_safe:
    raise SystemExit(2)
print("programme-runtime-role-verified")
"""


class ProgrammeProvisioningError(RuntimeError):
    """Report a stable provisioning failure without credentials or subprocess logs."""


def require_provisioning_process_environment() -> None:
    """Fence the dedicated child settings before importing Django configuration.

    Raises
    ------
    ProgrammeProvisioningError
        For an unexpected role, URI, secret, ambient libpq override or weakened
        provenance setting. Configuration alone does not prove database safety.
    """
    request = require_programme_rehearsal_request()
    if (
        any(key.upper().startswith("PG") and value for key, value in os.environ.items())
        or os.environ.get("MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE") != "true"
        or len(os.environ.get("MARU_SECRET_KEY", "")) < 50
    ):
        raise ProgrammeProvisioningError("invalid_provisioning_environment")
    role = os.environ.get("MARU_PROGRAMME_REHEARSAL_PROCESS")
    if role == "maru_runtime":
        require_programme_runtime_environment()
        return
    if role != "maru_migration":
        raise ProgrammeProvisioningError("invalid_process_role")
    match = re.fullmatch(
        r"postgresql://maru_migration:[A-Za-z0-9_-]{43}@127\.0\.0\.1:"
        r"([1-9][0-9]{3,4})/maru_programme_" + request.run_id,
        os.environ.get("MARU_DATABASE_URL", ""),
    )
    if (
        match is None
        or not 1024 <= int(match[1]) <= 65535
        or os.environ.get("MARU_RUNTIME_DATABASE_ROLE") != "maru_runtime"
    ):
        raise ProgrammeProvisioningError("invalid_migration_database_scope")


def runtime_provisioning_sql(run_id: str) -> str:
    """Bind the exact reviewed ACL source only to the synthetic database name.

    Parameters
    ----------
    run_id : str
        Nonzero lowercase 32-hex synthetic run identity.

    Returns
    -------
    str
        Transaction-wrapped owner ACL source with only five database-name
        references replaced. Role, relation and function grants are unchanged.

    Raises
    ------
    ProgrammeProvisioningError
        For invalid identity or unreadable, changed or unexpectedly shaped source.
    """
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None or run_id == "0" * 32:
        raise ProgrammeProvisioningError("invalid_run_identity")
    try:
        source = PROVISIONING_SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ProgrammeProvisioningError("provisioning_source_unavailable") from None
    if hashlib.sha256(source.encode()).hexdigest() != PROVISIONING_SHA256:
        raise ProgrammeProvisioningError("provisioning_source_changed")
    database = f"maru_programme_{run_id}"
    guard = "pg_catalog.current_database() <> 'maru'"
    target = "ON DATABASE maru "
    if source.count(guard) != 1 or source.count(target) != 4:
        raise ProgrammeProvisioningError("provisioning_source_shape_changed")
    return source.replace(
        guard, f"pg_catalog.current_database() <> '{database}'"
    ).replace(target, f"ON DATABASE {database} ")


def _verify_lease(lease, request):
    if (
        not isinstance(lease, ProgrammeDatabaseLease)
        or lease.run_id != request.run_id
        or lease.database_name != f"maru_programme_{request.run_id}"
        or not isinstance(lease.owner_nonce, str)
        or re.fullmatch(r"[0-9a-f]{32}", lease.owner_nonce) is None
        or not isinstance(lease.admin_password, str)
        or _PASSWORD.fullmatch(lease.admin_password) is None
        or isinstance(lease.port, bool)
        or not isinstance(lease.port, int)
        or not 1024 <= lease.port <= 65535
    ):
        raise ProgrammeProvisioningError("invalid_owned_lease")
    value = _Docker().inspect(lease.container_id)
    _owned(
        value,
        name=f"maru-programme-{request.run_id}",
        run_id=request.run_id,
        owner=lease.owner_nonce,
        container_id=lease.container_id,
    )
    if _port(value) != lease.port:
        raise ProgrammeProvisioningError("owned_port_changed")


def _child_environment(lease, request, *, role, password, secret_key):
    if role not in {"maru_migration", "maru_runtime"}:
        raise ProgrammeProvisioningError("invalid_process_role")
    return {
        key: value
        for key, value in os.environ.items()
        if key.casefold() in _PROCESS_ENVIRONMENT
    } | {
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "DJANGO_SETTINGS_MODULE": "tests.rehearsals.programme_provisioning_settings",
        "MARU_PROGRAMME_REHEARSAL": "isolated",
        "MARU_PROGRAMME_REHEARSAL_RUN_ID": request.run_id,
        "MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS": str(request.lease_seconds),
        "MARU_PROGRAMME_REHEARSAL_PROCESS": role,
        "MARU_DATABASE_URL": (
            f"postgresql://{role}:{password}@127.0.0.1:{lease.port}/{lease.database_name}"
        ),
        "MARU_RUNTIME_DATABASE_ROLE": "maru_runtime",
        "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE": "true",
        "MARU_SECRET_KEY": secret_key,
    }


def _child(arguments, environment, *, timeout, expected_output=None):
    try:
        result = subprocess.run(  # noqa: S603 - fixed interpreter and command vectors
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProgrammeProvisioningError("provisioning_process_unavailable") from None
    if result.returncode or (
        expected_output is not None and result.stdout.strip() != expected_output
    ):
        raise ProgrammeProvisioningError("provisioning_process_failed")


def provision_programme_runtime(
    lease: ProgrammeDatabaseLease,
) -> ProgrammeRuntimeEnvironment:
    """Install current schema and verify a genuine restricted runtime connection.

    Parameters
    ----------
    lease : ProgrammeDatabaseLease
        Still-live exact resource yielded by ``isolated_programme_database``.
        This function must finish within that context; it never extends its lease.

    Returns
    -------
    ProgrammeRuntimeEnvironment
        Secret-bearing runtime endpoint after real role-safety verification.
        Do not log or serialize the URI. This is not Programme readiness proof.

    Raises
    ------
    ProgrammeProvisioningError
        For foreign identity, changed source, existing roles, migration or ACL
        failure, or unsuccessful runtime verification. Failed resources must be
        discarded by the owning context; no partial-install retry is supported.

    Notes
    -----
    Tracked policy is checked before any Docker, connection or process operation.
    Administrator, migration and runtime credentials are distinct. No role
    impersonation, fake migration, test settings or authorization substitute is
    used. Native execution and role/ACL evidence remain deferred under #102.
    """
    request = require_programme_rehearsal_request()
    _verify_lease(lease, request)
    source = runtime_provisioning_sql(request.run_id)
    migration_password = secrets.token_urlsafe(32)
    runtime_password = secrets.token_urlsafe(32)
    if (
        _PASSWORD.fullmatch(migration_password) is None
        or _PASSWORD.fullmatch(runtime_password) is None
        or len({lease.admin_password, migration_password, runtime_password}) != 3
    ):
        raise ProgrammeProvisioningError("credential_generation_failed")
    secret_key = secrets.token_urlsafe(64)
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=lease.port,
            dbname=lease.database_name,
            user="postgres",
            password=lease.admin_password,
            connect_timeout=5,
            options="-c search_path=pg_catalog -c statement_timeout=30000",
            autocommit=True,
        ) as connection:
            identity = connection.execute(
                "SELECT current_database(), session_user, current_user, "
                "current_setting('server_version_num')::integer"
            ).fetchone()
            if (
                identity is None
                or identity[:3] != (lease.database_name, "postgres", "postgres")
                or not 170000 <= identity[3] < 180000
            ):
                raise ProgrammeProvisioningError("database_identity_mismatch")
            if connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles "
                "WHERE rolname IN ('maru_migration', 'maru_runtime'))"
            ).fetchone() != (False,):
                raise ProgrammeProvisioningError("existing_provisioning_roles")
            with connection.transaction():
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE maru_migration LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Literal(migration_password))
                )
                connection.execute(
                    sql.SQL("ALTER DATABASE {} OWNER TO maru_migration").format(
                        sql.Identifier(lease.database_name)
                    )
                )
                connection.execute("ALTER SCHEMA public OWNER TO maru_migration")
            _verify_lease(lease, request)
            _child(
                ["-m", "django", "migrate", "--noinput"],
                _child_environment(
                    lease,
                    request,
                    role="maru_migration",
                    password=migration_password,
                    secret_key=secret_key,
                ),
                timeout=min(1800, request.lease_seconds),
            )
            _verify_lease(lease, request)
            connection.execute(source, prepare=False)
            connection.execute(
                sql.SQL("ALTER ROLE maru_runtime PASSWORD {}").format(
                    sql.Literal(runtime_password)
                )
            )
    except psycopg.Error:
        raise ProgrammeProvisioningError("database_provisioning_failed") from None
    _verify_lease(lease, request)
    runtime_environment = _child_environment(
        lease,
        request,
        role="maru_runtime",
        password=runtime_password,
        secret_key=secret_key,
    )
    _child(
        ["-c", _PROBE],
        runtime_environment,
        timeout=min(60, request.lease_seconds),
        expected_output="programme-runtime-role-verified",
    )
    return ProgrammeRuntimeEnvironment(
        run_id=request.run_id,
        database_name=lease.database_name,
        port=lease.port,
        lease_seconds=request.lease_seconds,
        database_url=runtime_environment["MARU_DATABASE_URL"],
    )
