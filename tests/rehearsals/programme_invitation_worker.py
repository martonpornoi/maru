"""One real isolated invitation-worker cycle; never a web process or fake heartbeat."""

import os
from io import StringIO

from tests.rehearsals.programme_fixture_material import (
    ADMIN_PASSWORD_ENV,
    PRIVATE_KEYS_ENV,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)


def run_invitation_worker_cycle():
    """Run genuine bounded delivery, expiry and retention, then demand readiness.

    Returns
    -------
    tuple
        Explicitly accounted-for dormant check IDs, not production acceptance.

    Notes
    -----
    The future owned launcher supplies only the worker's private-key environment.
    All ordinary checks run through the isolated compatibility contract before
    invoking existing management commands. Those commands retain their own guards,
    native timestamps, transactions and heartbeat recording. In-memory delivery
    is synthetic transport, not proof of external delivery or human acceptance.
    """
    environment = require_programme_runtime_environment()
    from tests.rehearsals.programme_provisioning import (  # noqa: PLC0415
        ProgrammeProvisioningError,
    )

    if (
        os.environ.get("DJANGO_SETTINGS_MODULE")
        != "tests.rehearsals.programme_runtime_settings"
        or ADMIN_PASSWORD_ENV in os.environ
        or "MARU_PROGRAMME_REHEARSAL_BOOTSTRAP" in os.environ
        or not os.environ.get(PRIVATE_KEYS_ENV)
    ):
        raise ProgrammeProvisioningError("invitation_worker_environment_invalid")
    import django  # noqa: PLC0415
    from django.conf import settings  # noqa: PLC0415
    from django.core.management import call_command  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    django.setup()
    from maru.authorization.database_role_safety import (  # noqa: PLC0415
        probe_runtime_database_role_safety,
    )
    from maru.identity.invitation_key_config import (  # noqa: PLC0415
        active_invitation_encryption_key,
        worker_invitation_private_keyring,
    )
    from tests.rehearsals.programme_compatibility import (  # noqa: PLC0415
        check_isolated_candidate,
    )
    from tests.rehearsals.programme_effects import (  # noqa: PLC0415
        install_isolated_candidate_handlers,
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        _require_native_readiness,
        _runtime_configuration_is_strict,
    )
    from tests.rehearsals.programme_runtime_privileges import (  # noqa: PLC0415
        install_isolated_candidate_privilege_contract,
        require_candidate_reference_boundary,
    )

    if not _runtime_configuration_is_strict(settings):
        raise ProgrammeProvisioningError("invitation_worker_settings_invalid")
    install_isolated_candidate_privilege_contract()
    install_isolated_candidate_handlers()
    accounted = check_isolated_candidate()
    # Heartbeat-dependent full readiness cannot precede the first worker cycle.
    # Genuine native identity/privileges must still precede every worker write.
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), session_user, current_user")
        if cursor.fetchone() != (
            environment.database_name,
            "maru_runtime",
            "maru_runtime",
        ):
            raise ProgrammeProvisioningError("invitation_worker_identity_invalid")
        require_candidate_reference_boundary(cursor)
    if not probe_runtime_database_role_safety(
        role_name="maru_runtime"
    ).current_session_is_safe:
        raise ProgrammeProvisioningError("invitation_worker_runtime_unsafe")
    if not worker_invitation_private_keyring().matches(
        active_invitation_encryption_key()
    ):
        raise ProgrammeProvisioningError("invitation_worker_key_mismatch")
    # call_command's normal programmatic check behavior is appropriate only
    # after the complete isolated check contract above. No owner guard is replaced.
    for command, options in (
        ("platform_invitation_delivery", {"delivery_limit": 100}),
        ("expire_platform_account_invitations", {"limit": 100}),
        ("run_platform_invitation_retention", {"limit": 100}),
    ):
        call_command(command, **options, stdout=StringIO(), stderr=StringIO())
    _require_native_readiness(environment)
    return accounted
