"""Restore only an owned synthetic database; never repair or overwrite its source."""

import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager, suppress
from dataclasses import asdict, replace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from tests.rehearsals.programme_database import _Docker, _owned, _port
from tests.rehearsals.programme_excluded_state import _fingerprint, excluded_tables
from tests.rehearsals.programme_https import remaining_lease
from tests.rehearsals.programme_provisioning import ROOT, _child, _verify_lease
from tests.rehearsals.programme_restore_readiness import (
    verify_restored_readiness_faults,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

MAX_DUMP_BYTES = 67_108_864
_WORKER = (
    "from tests.rehearsals.programme_invitation_worker import "
    "run_invitation_worker_cycle; run_invitation_worker_cycle(); "
    "print('programme-invitation-cycle-verified')"
)


class ProgrammeLogicalRestoreError(RuntimeError):
    """Expose only a closed recovery failure, never secrets or dump contents."""


def _require(condition, code):
    if not condition:
        raise ProgrammeLogicalRestoreError(code)


def _runtime_data_state(runtime):
    """Compare bounded server-side row hashes, never move private rows into logs."""
    with psycopg.connect(
        runtime.database_url,
        connect_timeout=5,
        options="-c statement_timeout=10000 -c lock_timeout=1000",
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        _require(
            connection.execute(
                "SELECT current_database(), session_user, current_user"
            ).fetchone()
            == (runtime.database_name, "maru_runtime", "maru_runtime"),
            "restore_runtime_identity_mismatch",
        )
        names = tuple(
            row[0]
            for row in connection.execute(
                "SELECT c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname"
            ).fetchall()
        )
        _require(0 < len(names) <= 1000, "restore_relation_inventory_invalid")
        return tuple(_fingerprint(connection, name) for name in names)


def _docker_for_lease(lease):
    docker = _Docker()
    endpoint = docker.call(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    ).stdout.strip()
    _require(
        endpoint.startswith(("npipe:////./pipe/", "unix:///")),
        "restore_nonlocal_docker",
    )
    docker._host_endpoint = endpoint
    _check_container(docker, lease)
    return docker


def _check_container(docker, lease):
    observed = docker.inspect(lease.container_id)
    _owned(
        observed,
        name="maru-programme-" + lease.run_id,
        run_id=lease.run_id,
        owner=lease.owner_nonce,
        container_id=lease.container_id,
    )
    _require(_port(observed) == lease.port, "restore_source_port_changed")


def _dump_command(docker, lease, deadline, *arguments, payload=None):
    _check_container(docker, lease)
    timeout = min(180, remaining_lease(deadline))
    if payload is not None:
        _require(len(payload) <= MAX_DUMP_BYTES, "restore_dump_limit_exceeded")
    try:
        process = subprocess.Popen(  # noqa: S603 -- fixed tools on an inspected owned lease.
            [
                docker.executable,
                "--host",
                docker._host_endpoint,
                "exec",
                *(["-i"] if payload is not None else []),
                lease.container_id,
                *arguments,
            ],
            stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        expired = threading.Event()

        def expire():
            expired.set()
            with suppress(OSError):
                process.kill()

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            if payload is not None:
                process.stdin.write(payload)
                process.stdin.close()
            output = process.stdout.read(MAX_DUMP_BYTES + 1)
            _require(len(output) <= MAX_DUMP_BYTES, "restore_dump_limit_exceeded")
            process.wait(timeout=min(5, remaining_lease(deadline)))
            _require(not expired.is_set(), "restore_transport_timeout")
            _require(process.returncode == 0, "restore_dump_command_failed")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdin is not None:
                process.stdin.close()
            process.stdout.close()
    except (OSError, subprocess.TimeoutExpired):
        raise ProgrammeLogicalRestoreError("restore_transport_unavailable") from None
    remaining_lease(deadline)
    return output


def _admin_connection(lease):
    return psycopg.connect(
        host="127.0.0.1",
        port=lease.port,
        dbname=lease.database_name,
        user="postgres",
        password=lease.admin_password,
        connect_timeout=5,
        options="-c search_path=pg_catalog -c statement_timeout=30000",
        autocommit=True,
    )


@contextmanager
def _restored_database(fixture, *, omit_journal_for_negative=False):
    """Create a new database inside the original owned lease; do not extend it."""
    request = require_programme_rehearsal_request()
    lease = fixture._database_lease
    _verify_lease(lease, request)
    try:
        source_url = urlsplit(fixture.runtime.database_url)
        source_port = source_url.port
    except ValueError:
        raise ProgrammeLogicalRestoreError("restore_source_run_mismatch") from None
    _require(
        fixture.runtime.run_id == lease.run_id
        and fixture.runtime.database_name == lease.database_name
        and fixture.runtime.port == lease.port
        and source_url.scheme == "postgresql"
        and source_url.hostname == "127.0.0.1"
        and source_port == lease.port
        and source_url.username == "maru_runtime"
        and source_url.path == "/" + lease.database_name
        and not source_url.query
        and not source_url.fragment,
        "restore_source_run_mismatch",
    )
    remaining_lease(fixture.deadline)
    docker = _docker_for_lease(lease)
    source_state = _runtime_data_state(fixture.runtime)
    _require(type(omit_journal_for_negative) is bool, "restore_fault_option_invalid")
    if omit_journal_for_negative:
        _require(
            any(
                row[0] == "scheduling_schedulingreleasedependencychange" and row[1] > 0
                for row in source_state
            ),
            "restore_negative_requires_journal",
        )
    dump = _dump_command(
        docker,
        lease,
        fixture.deadline,
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        lease.database_name,
        "--format=custom",
        *(
            ["--exclude-table-data=public.scheduling_schedulingreleasedependencychange"]
            if omit_journal_for_negative
            else []
        ),
    )
    _require(dump.startswith(b"PGDMP"), "restore_dump_format_invalid")
    clone_id = uuid4().hex
    clone_name = "maru_programme_" + clone_id
    _require(clone_name != lease.database_name, "restore_source_target_overlap")
    clone_url = urlunsplit(source_url._replace(path="/" + clone_name))
    runtime = replace(
        fixture.runtime,
        run_id=clone_id,
        database_name=clone_name,
        database_url=clone_url,
    )
    created = False
    try:
        with _admin_connection(lease) as admin:
            _require(
                admin.execute(
                    "SELECT current_database(), session_user, current_user"
                ).fetchone()
                == (lease.database_name, "postgres", "postgres"),
                "restore_admin_identity_mismatch",
            )
            _require(
                admin.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_database "
                    "WHERE datname=%s)",
                    [clone_name],
                ).fetchone()
                == (False,),
                "restore_target_exists",
            )
            admin.execute(
                sql.SQL(
                    "CREATE DATABASE {} OWNER maru_migration TEMPLATE template0"
                ).format(sql.Identifier(clone_name))
            )
            created = True
            # Database-level ACLs are not part of a database-only custom dump.
            # Reuse the reviewed three-role boundary, not broad runtime grants.
            admin.execute(
                sql.SQL(
                    "REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC"
                ).format(sql.Identifier(clone_name))
            )
            admin.execute(
                sql.SQL(
                    "GRANT CONNECT, CREATE, TEMPORARY ON DATABASE {} TO maru_migration"
                ).format(sql.Identifier(clone_name))
            )
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO maru_runtime").format(
                    sql.Identifier(clone_name)
                )
            )
        _dump_command(
            docker,
            lease,
            fixture.deadline,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            clone_name,
            "--exit-on-error",
            payload=dump,
        )
        _require(
            _runtime_data_state(fixture.runtime) == source_state,
            "restore_source_changed",
        )
        _require(
            _runtime_data_state(runtime) == source_state,
            "restore_data_snapshot_mismatch",
        )
        yield runtime, source_state
    finally:
        if created:
            _check_container(docker, lease)
            with _admin_connection(lease) as admin:
                # Only the UUID-named database created above, no FORCE or source
                # replacement. Any lingering child connection makes cleanup fail.
                _require(
                    clone_name == "maru_programme_" + clone_id
                    and clone_name != lease.database_name,
                    "restore_cleanup_scope_invalid",
                )
                admin.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(clone_name))
                )


def verify_logical_restore(
    fixture, proposal, review, items, planning, physical, staffing, released, changed
):
    """Exercise real restored authority and invalidation while leaving source intact."""
    fixture.refresh_workers()
    fixture.verify_excluded_state()
    sources = dict(
        zip(
            (
                "setup",
                "proposal",
                "review",
                "items",
                "planning",
                "physical",
                "staffing",
                "release",
            ),
            map(
                asdict,
                (
                    fixture.scenario,
                    proposal,
                    review,
                    items,
                    planning,
                    physical,
                    staffing,
                    released,
                ),
            ),
            strict=True,
        )
    )
    with _restored_database(fixture) as (runtime, source_state):
        connection_environment = {
            "MARU_DATABASE_URL": runtime.database_url,
            "MARU_PROGRAMME_REHEARSAL_RUN_ID": runtime.run_id,
        }
        # Real worker liveness on the restored copy, never a synthetic heartbeat.
        _child(
            ["-c", _WORKER],
            fixture._worker_environment | connection_environment,
            timeout=min(180, remaining_lease(fixture.deadline)),
            expected_output="programme-invitation-cycle-verified",
        )
        verify_restored_readiness_faults(
            fixture,
            runtime,
            fixture._application_environment | connection_environment,
        )
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.rehearsals.programme_logical_restore_scenario",
                ],
                cwd=ROOT,
                env=fixture._application_environment | connection_environment,
                input=json.dumps(
                    {"sources": sources, "change": asdict(changed)}, default=str
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=min(180, remaining_lease(fixture.deadline)),
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ProgrammeLogicalRestoreError("restore_scenario_unavailable") from None
        _require(
            result.returncode == 0
            and result.stdout.strip() == "programme-logical-restore-verified",
            "restore_scenario_failed",
        )
        excluded = set(excluded_tables())
        _require(
            tuple(row for row in _runtime_data_state(runtime) if row[0] in excluded)
            == tuple(row for row in source_state if row[0] in excluded),
            "restore_excluded_owner_changed",
        )
        _require(
            _runtime_data_state(fixture.runtime) == source_state,
            "restore_source_changed",
        )
    fixture.verify_excluded_state()


def verify_incomplete_backup_rejected(fixture):
    """Reject a genuine incomplete backup before any restored worker is allowed."""
    try:
        with _restored_database(fixture, omit_journal_for_negative=True):
            _require(condition=False, code="restore_partial_backup_was_accepted")
    except ProgrammeLogicalRestoreError as error:
        if str(error) != "restore_data_snapshot_mismatch":
            raise
    fixture.verify_excluded_state()
