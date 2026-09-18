"""Host-only #102 provisioning proof; no routine discovery or deferred execution."""

from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals.programme_database import isolated_programme_database
from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    provision_programme_runtime,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_migration_runtime_separation_and_reprovision_refusal(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_database() as lease:
        runtime = provision_programme_runtime(lease)
        with psycopg.connect(
            runtime.database_url,
            connect_timeout=5,
            options="-c search_path=public,pg_temp",
        ) as connection:
            assert connection.execute(
                "SELECT current_database(), session_user, current_user"
            ).fetchone() == (lease.database_name, "maru_runtime", "maru_runtime")
            assert connection.execute(
                "SELECT pg_catalog.pg_get_userbyid(datdba) "
                "FROM pg_catalog.pg_database WHERE datname = current_database()"
            ).fetchone() == ("maru_migration",)
            with (
                pytest.raises(psycopg.errors.InsufficientPrivilege),
                connection.transaction(),
            ):
                connection.execute(
                    "CREATE TABLE public.forbidden_runtime_ddl (id integer)"
                )
        with pytest.raises(
            ProgrammeProvisioningError, match="existing_provisioning_roles"
        ):
            provision_programme_runtime(lease)
