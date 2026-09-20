"""Test unsafe metadata only in the newly restored disposable database."""

import psycopg
from psycopg import sql

from tests.rehearsals.programme_https import remaining_lease
from tests.rehearsals.programme_provisioning import _child

_PROBE = """
import django
django.setup()
from tests.rehearsals.programme_runtime import (
    ProgrammeStartupError, build_candidate_application,
)
from tests.rehearsals.programme_compatibility import ProgrammeCompatibilityError
try:
    build_candidate_application()
except (ProgrammeStartupError, ProgrammeCompatibilityError) as error:
    if str(error) not in {
        'candidate_native_helper_unavailable',
        'candidate_native_readiness_unavailable',
        'candidate_system_check_failed',
    }:
        raise SystemExit(2) from None
    print('programme-restored-runtime-unavailable')
else:
    print('programme-restored-runtime-ready')
"""


def verify_restored_readiness_faults(fixture, runtime, environment):
    """Restore each injected clone-only fault before the next readiness check."""
    from tests.rehearsals.programme_logical_restore import (  # noqa: PLC0415
        _docker_for_lease,
        _require,
    )

    lease = fixture._database_lease
    _require(
        runtime.database_name == "maru_programme_" + runtime.run_id
        and len(runtime.run_id) == 32
        and all(character in "0123456789abcdef" for character in runtime.run_id)
        and runtime.database_name != lease.database_name
        and runtime.port == lease.port,
        "restore_fault_target_invalid",
    )
    _docker_for_lease(lease)

    def probe(*, available):
        _child(
            ["-c", _PROBE],
            environment,
            timeout=min(120, remaining_lease(fixture.deadline)),
            expected_output=(
                "programme-restored-runtime-ready"
                if available
                else "programme-restored-runtime-unavailable"
            ),
        )

    with psycopg.connect(
        host="127.0.0.1",
        port=lease.port,
        dbname=runtime.database_name,
        user="postgres",
        password=lease.admin_password,
        connect_timeout=5,
        options="-c search_path=pg_catalog -c statement_timeout=10000",
        autocommit=True,
    ) as admin:
        _require(
            admin.execute(
                "SELECT current_database(), session_user, current_user, "
                "has_database_privilege('maru_runtime', current_database(), 'CREATE')"
            ).fetchone()
            == (runtime.database_name, "postgres", "postgres", False),
            "restore_fault_initial_identity_invalid",
        )
        probe(available=True)
        try:
            admin.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO maru_runtime").format(
                    sql.Identifier(runtime.database_name)
                )
            )
            probe(available=False)
        finally:
            admin.execute(
                sql.SQL("REVOKE CREATE ON DATABASE {} FROM maru_runtime").format(
                    sql.Identifier(runtime.database_name)
                )
            )
        probe(available=True)
        _require(
            admin.execute(
                "SELECT prosecdef FROM pg_proc WHERE oid = "
                "'public.maru_events_release_change_valid(uuid,uuid,uuid,uuid)'"
                "::regprocedure"
            ).fetchone()
            == (False,),
            "restore_fault_function_initial_state_invalid",
        )
        try:
            admin.execute(
                "ALTER FUNCTION public.maru_events_release_change_valid"
                "(uuid,uuid,uuid,uuid) SECURITY DEFINER"
            )
            probe(available=False)
        finally:
            admin.execute(
                "ALTER FUNCTION public.maru_events_release_change_valid"
                "(uuid,uuid,uuid,uuid) SECURITY INVOKER"
            )
        probe(available=True)
