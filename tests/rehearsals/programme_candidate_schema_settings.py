"""Non-serving candidate-schema migration settings; no profile registration."""

import os

from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    require_provisioning_process_environment,
)

require_provisioning_process_environment()
if (
    os.environ.get("MARU_PROGRAMME_REHEARSAL_SCHEMA") != "candidate-v1"
    or os.environ.get("MARU_PROGRAMME_REHEARSAL_PROCESS") != "maru_migration"
):
    raise ProgrammeProvisioningError("candidate_schema_context_required")

from tests.rehearsals.programme_provisioning_settings import *  # noqa: F403, E402

MIGRATION_MODULES = {"events": "tests.rehearsals.programme_event_migrations"}
