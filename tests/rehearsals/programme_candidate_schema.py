"""Native empty-database guards for the isolated Events migration overlay.

These are preparation only while tracked PostgreSQL policy is deferred. The
server deparses an independent, literal reference constraint before comparison;
no whitespace normalization or inferred native fingerprint is used.
"""

import os

from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    require_provisioning_process_environment,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

_CURRENT = """
    (adoption_profile_code = 'full_convention' AND adoption_profile_version = 1)
    OR (adoption_profile_code = 'workforce_only' AND adoption_profile_version = 1)
"""
_CANDIDATE = (
    _CURRENT
    + """
    OR (adoption_profile_code = 'programme_operations' AND adoption_profile_version = 1)
"""
)


def _require_empty_schema(schema_editor, *, candidate):
    request = require_programme_rehearsal_request()
    require_provisioning_process_environment()
    connection = schema_editor.connection
    if (
        os.environ.get("MARU_PROGRAMME_REHEARSAL_SCHEMA") != "candidate-v1"
        or os.environ.get("MARU_PROGRAMME_REHEARSAL_PROCESS") != "maru_migration"
        or connection.vendor != "postgresql"
        or not connection.in_atomic_block
    ):
        raise ProgrammeProvisioningError("candidate_schema_context_required")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), session_user, current_user, "
            "current_setting('server_version_num')::integer"
        )
        identity = cursor.fetchone()
        if (
            identity is None
            or identity[:3]
            != (f"maru_programme_{request.run_id}", "maru_migration", "maru_migration")
            or not 170000 <= identity[3] < 180000
        ):
            raise ProgrammeProvisioningError("candidate_schema_identity_mismatch")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        cursor.execute("LOCK TABLE public.events_eventedition IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM public.events_eventedition)")
        if cursor.fetchone() != (False,):
            raise ProgrammeProvisioningError("candidate_schema_requires_empty_editions")
        # Fixed local SQL, never input from configuration, the database or a caller.
        expression = _CANDIDATE if candidate else _CURRENT
        cursor.execute(
            "CREATE TEMPORARY TABLE maru_programme_profile_reference ("
            "adoption_profile_code varchar(40) NOT NULL, "
            "adoption_profile_version integer NOT NULL, "
            "CONSTRAINT expected_profile CHECK (" + expression + ")) ON COMMIT DROP"
        )
        cursor.execute(
            "SELECT pg_catalog.pg_get_constraintdef(actual.oid) = "
            "pg_catalog.pg_get_constraintdef(expected.oid), actual.convalidated "
            "FROM pg_catalog.pg_constraint actual "
            "CROSS JOIN pg_catalog.pg_constraint expected "
            "WHERE actual.conrelid = 'public.events_eventedition'::regclass "
            "AND actual.conname = 'edition_adoption_profile_supported' "
            "AND actual.contype = 'c' "
            "AND expected.conrelid = "
            "'pg_temp.maru_programme_profile_reference'::regclass "
            "AND expected.conname = 'expected_profile' AND expected.contype = 'c'"
        )
        if cursor.fetchall() != [(True, True)]:
            raise ProgrammeProvisioningError("candidate_schema_constraint_drift")
        cursor.execute("DROP TABLE pg_temp.maru_programme_profile_reference")


def require_empty_current_schema(apps, schema_editor) -> None:
    """Require genuine scoped migration login, empty editions and the old constraint."""
    _require_empty_schema(schema_editor, candidate=False)


def require_empty_candidate_schema(apps, schema_editor) -> None:
    """Fence reversal before changing any field or constraint once editions exist."""
    _require_empty_schema(schema_editor, candidate=True)
