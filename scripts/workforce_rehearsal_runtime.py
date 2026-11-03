"""Run only bootstrap or real invitation workers inside the owned rehearsal."""

from __future__ import annotations

import os
import sys
from uuid import uuid4

import django
from django.conf import settings
from django.core.management import call_command
from django.db import connection


def main() -> int:
    """Execute the explicit process role after verifying its real database login.

    Returns
    -------
    int
        Zero after success; any boundary violation raises and stops the launcher.

    Raises
    ------
    RuntimeError
        If the settings, role, keys or initially empty account state are unsafe.
    """
    django.setup()
    from maru.authorization.activation import (  # noqa: PLC0415
        activate_authority_provenance,
    )
    from maru.authorization.database_role_safety import (  # noqa: PLC0415
        probe_runtime_database_role_safety,
    )
    from maru.identity.invitation_key_config import (  # noqa: PLC0415
        active_invitation_encryption_key,
    )
    from maru.identity.invitation_retention import (  # noqa: PLC0415
        activate_configured_invitation_retention_policy,
        configured_invitation_retention_policy,
    )
    from maru.identity.invitation_token_keys import (  # noqa: PLC0415
        invitation_token_keyring,
    )
    from maru.identity.models import Account  # noqa: PLC0415

    process = os.environ.get("MARU_WORKFORCE_REHEARSAL_PROCESS")
    expected_role = "maru_migration" if process == "bootstrap" else "maru_runtime"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), session_user, current_user")
        identity = cursor.fetchone()
    safety = probe_runtime_database_role_safety(role_name="maru_runtime")
    if not (
        process in {"bootstrap", "worker"}
        and settings.SETTINGS_MODULE == "scripts.workforce_rehearsal_settings"
        and identity == ("maru", expected_role, expected_role)
        and not settings.DEBUG
        and settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
        and settings.REQUIRE_PRIVILEGED_STEP_UP
        and settings.ENFORCE_EDITION_CLOSURE_GATES
        and not settings.IDENTITY_EXPOSE_TEST_TOKENS
        and not settings.MARU_EXPOSE_TEST_CREDENTIAL_TOKENS
        and not settings.DEMO_PAYMENT_ADAPTER_ENABLED
        and not settings.SILENCED_SYSTEM_CHECKS
        and safety.target_role_is_safe
        and (process == "bootstrap" or safety.current_session_is_safe)
    ):
        raise RuntimeError("Rehearsal settings or authenticated role are unsafe.")
    active_invitation_encryption_key()
    invitation_token_keyring()
    configured_invitation_retention_policy()
    if process == "bootstrap":
        if Account.objects.exists():
            raise RuntimeError("Bootstrap requires a new empty account store.")
        actor = Account.objects.create_superuser(
            email="workforce-platform@example.invalid",
            password=os.environ["MARU_WORKFORCE_BOOTSTRAP_PASSWORD"],
        )
        result = activate_authority_provenance(
            actor=actor,
            reason=(
                "Activate exact authority for the isolated synthetic "
                "Workforce rehearsal."
            ),
            correlation_id=uuid4(),
            acknowledge_processes_stopped=True,
            source_channel="operator",
        )
        if not result.activated or result.blocker_total:
            raise RuntimeError("Exact authority activation did not complete.")
        activate_configured_invitation_retention_policy()
    else:
        if "MARU_WORKFORCE_BOOTSTRAP_PASSWORD" in os.environ:
            raise RuntimeError("A worker must not receive the bootstrap password.")
        for command in (
            "platform_invitation_delivery",
            "expire_platform_account_invitations",
            "run_platform_invitation_retention",
        ):
            call_command(command, verbosity=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
