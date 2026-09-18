"""Explicit host-only native transport checks for #102, never routine collection.

Run only after tracked PostgreSQL restoration and explicit rehearsal opt-in.
These checks create one disposable database at a time and are not part of the
eight-worker application pool. They prove transport/expiry/cleanup only, never
Programme schema, runtime-role correctness or P01-P12 acceptance.
"""

import json
import os
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals.programme_database import (
    _Docker,
    _owned,
    isolated_programme_database,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

# Refuse even explicit module collection without the tracked policy and opt-in.
# Ordinary tests/unit discovery never imports this module.
require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def unique_short_lease(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "60")


def wait_for_removal(container_id):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        if _Docker().inspect(container_id) is None:
            return
        time.sleep(1)
    pytest.fail("Owned fixture container did not expire within the native bound")


def test_native_loopback_database_identity_and_normal_cleanup():
    with isolated_programme_database() as lease:
        with psycopg.connect(
            host="127.0.0.1",
            port=lease.port,
            dbname=lease.database_name,
            user="postgres",
            password=lease.admin_password,
            connect_timeout=5,
        ) as connection:
            assert connection.execute(
                "SELECT current_database(), current_user"
            ).fetchone() == (
                lease.database_name,
                "postgres",
            )
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
            assert 170000 <= version < 180000
        container_id = lease.container_id
    assert _Docker().inspect(container_id) is None


def test_native_body_failure_cleans_owned_container():
    identities = []

    def fail_inside_context():
        with isolated_programme_database() as lease:
            identities.append(lease.container_id)
            raise ValueError("synthetic failure")

    with pytest.raises(ValueError, match="synthetic failure"):
        fail_inside_context()
    assert len(identities) == 1
    assert _Docker().inspect(identities[0]) is None


def test_native_lease_expiry_removes_database_while_controller_is_alive():
    with isolated_programme_database() as lease:
        wait_for_removal(lease.container_id)


def test_native_lease_survives_abrupt_controller_exit():
    source = (
        "import os, json; "
        "from tests.rehearsals.programme_database import isolated_programme_database; "
        "context = isolated_programme_database(); lease = context.__enter__(); "
        "print(json.dumps({'id': lease.container_id, 'owner': lease.owner_nonce}), "
        "flush=True); os._exit(0)"
    )
    result = subprocess.run(  # noqa: S603 - same interpreter and fixed synthetic code
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
        env=dict(os.environ),
    )
    identity = json.loads(result.stdout)
    assert set(identity) == {"id", "owner"}
    container_id = identity["id"]
    run_id = os.environ["MARU_PROGRAMME_REHEARSAL_RUN_ID"]
    docker = _Docker()
    try:
        _owned(
            docker.inspect(container_id),
            name=f"maru-programme-{run_id}",
            run_id=run_id,
            owner=identity["owner"],
            container_id=container_id,
        )
        wait_for_removal(container_id)
    finally:
        # A failed expiry assertion must not itself strand a disposable database.
        value = docker.inspect(container_id)
        if value is not None:
            owned_id = _owned(
                value,
                name=f"maru-programme-{run_id}",
                run_id=run_id,
                owner=identity["owner"],
                container_id=container_id,
            )
            docker.call("container", "rm", "--force", owned_id)
            assert docker.inspect(owned_id) is None
